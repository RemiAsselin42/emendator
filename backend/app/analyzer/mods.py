"""Ingest a Fabric ``mods/`` folder and run static conflict detection.

Each ``.jar`` is opened **once**: its ``fabric.mod.json`` becomes a
:class:`Mod`, and the files the detectors need (recipes, item tags, mixin
target classes — located via the :class:`VersionProfile`, never hardcoded) are
read into a :class:`JarIndex`. Detection then runs purely in memory.

Jars without ``fabric.mod.json`` or that fail to parse are non-fatal: they are
collected as :class:`ScanError`. Only top-level jars are scanned (nested
``META-INF/jars`` deferred).
"""

import hashlib
import io
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.analyzer.detectors import JarIndex, detect_conflicts
from app.analyzer.mixin_targets import extract_mixin_targets
from app.models import (
    Environment,
    Mod,
    ScanCounts,
    ScanError,
    ScanResult,
    UntestableMod,
)
from app.profile import VersionProfile, resolve_profile

FABRIC_METADATA = "fabric.mod.json"
CLIENT_REASON = "environment:client not loaded by server boot"
_VALID_ENVIRONMENTS: tuple[Environment, ...] = ("server", "client", "*")
_MIXIN_SECTIONS = ("mixins", "client", "server")


def _coerce_environment(value: object) -> Environment:
    """Map the raw ``environment`` field to the contract; default to ``"*"``."""
    if value in _VALID_ENVIRONMENTS:
        return value  # type: ignore[return-value]
    return "*"


def _coerce_mc_version(depends: object) -> str | None:
    """Pull the Minecraft version constraint out of ``depends`` (str or list)."""
    if not isinstance(depends, dict):
        return None
    mc = depends.get("minecraft")
    if isinstance(mc, list):
        mc = mc[0] if mc else None
    if mc is None:
        return None
    return mc if isinstance(mc, str) else str(mc)


def _metadata_to_mod(raw: bytes, jar_name: str) -> tuple[Mod | None, ScanError | None]:
    """Parse ``fabric.mod.json`` bytes into a :class:`Mod`."""
    try:
        # strict=False tolerates literal control characters (newlines/tabs) that
        # real fabric.mod.json files embed in string values; Fabric's own loader
        # is lenient here, so we must be too (e.g. Debugify).
        data = json.loads(raw, strict=False)
    except json.JSONDecodeError as exc:
        return None, ScanError(jar=jar_name, reason=f"invalid fabric.mod.json: {exc}")

    if not isinstance(data, dict):
        return None, ScanError(jar=jar_name, reason="fabric.mod.json is not an object")

    mod_id = data.get("id")
    if not isinstance(mod_id, str) or not mod_id:
        return None, ScanError(jar=jar_name, reason="fabric.mod.json missing 'id'")

    depends = data.get("depends")
    version = data.get("version")
    name = data.get("name")
    provides = data.get("provides")
    mod = Mod(
        id=mod_id,
        name=name if isinstance(name, str) else None,
        version=str(version) if version is not None else None,
        mc_version=_coerce_mc_version(depends),
        environment=_coerce_environment(data.get("environment")),
        depends=depends if isinstance(depends, dict) else {},
        provides=[p for p in provides if isinstance(p, str)] if isinstance(provides, list) else [],
        jar=jar_name,
    )
    return mod, None


def _matches_template(name: str, template: str) -> bool:
    """Does ``name`` sit under ``template`` (``{mod}`` = wildcard) with a file leaf?"""
    if not name.endswith(".json"):
        return False
    name_parts = name.split("/")
    template_parts = template.split("/")
    if len(name_parts) <= len(template_parts):
        return False
    # template is the shorter prefix; zip stops at its length by design.
    return all(t == "{mod}" or n == t for n, t in zip(name_parts, template_parts, strict=False))


def _read_data_jsons(
    zf: zipfile.ZipFile, names: list[str], template: str
) -> dict[str, dict[str, Any]]:
    """Read every JSON object under a profile path template, keyed by inner path."""
    out: dict[str, dict[str, Any]] = {}
    for name in names:
        if not _matches_template(name, template):
            continue
        try:
            parsed = json.loads(zf.read(name), strict=False)
        except (json.JSONDecodeError, KeyError, OSError):
            continue
        if isinstance(parsed, dict):
            out[name] = parsed
    return out


def _collect_mixin_targets(zf: zipfile.ZipFile, names: list[str]) -> tuple[set[str], set[str]]:
    """``@Mixin`` class targets and ``Class#method`` pairs across the jar's mixins."""
    classes: set[str] = set()
    methods: set[str] = set()
    for name in names:
        if not name.endswith(".mixins.json"):
            continue
        try:
            config = json.loads(zf.read(name), strict=False)
        except (json.JSONDecodeError, KeyError, OSError):
            continue
        if not isinstance(config, dict) or not isinstance(config.get("package"), str):
            continue
        base = config["package"].replace(".", "/")
        for section in _MIXIN_SECTIONS:
            mixin_classes = config.get(section)
            if not isinstance(mixin_classes, list):
                continue
            for class_name in mixin_classes:
                if not isinstance(class_name, str):
                    continue
                class_path = f"{base}/{class_name.replace('.', '/')}.class"
                try:
                    targets = extract_mixin_targets(zf.read(class_path))
                except KeyError:
                    continue
                classes |= targets.classes
                methods |= targets.methods
    return classes, methods


_MAX_NEST_DEPTH = 4


@dataclass
class _Nested:
    """What we harvest from a jar's nested jars (jars-in-jars)."""

    ids: set[str] = field(default_factory=set)
    mixin_classes: set[str] = field(default_factory=set)
    mixin_methods: set[str] = field(default_factory=set)


def _collect_nested(zf: zipfile.ZipFile, names: list[str], depth: int = 0) -> _Nested:
    """Recursively harvest ids/provides and mixin targets from nested jars.

    Fabric ships libraries — and the Fabric API's own modules, which carry many
    mixins — as ``.jar`` files bundled inside a mod jar. Their ids satisfy
    dependencies, and their mixins matter for overlap detection (the API patches
    plenty of vanilla classes). Nested recipes/tags are intentionally *not*
    merged: two mods bundling the same library would look like a false content
    collision, and the loader dedupes them at runtime anyway.
    """
    result = _Nested()
    if depth >= _MAX_NEST_DEPTH:
        return result
    for name in names:
        if not name.endswith(".jar"):
            continue
        try:
            blob = zf.read(name)
            with zipfile.ZipFile(io.BytesIO(blob)) as nested:
                nested_names = nested.namelist()
                try:
                    data = json.loads(nested.read(FABRIC_METADATA), strict=False)
                except (KeyError, json.JSONDecodeError):
                    data = None
                if isinstance(data, dict):
                    nested_id = data.get("id")
                    if isinstance(nested_id, str) and nested_id:
                        result.ids.add(nested_id)
                    provides = data.get("provides")
                    if isinstance(provides, list):
                        result.ids.update(p for p in provides if isinstance(p, str))
                nested_classes, nested_methods = _collect_mixin_targets(nested, nested_names)
                result.mixin_classes |= nested_classes
                result.mixin_methods |= nested_methods
                deeper = _collect_nested(nested, nested_names, depth + 1)
                result.ids |= deeper.ids
                result.mixin_classes |= deeper.mixin_classes
                result.mixin_methods |= deeper.mixin_methods
        except (KeyError, zipfile.BadZipFile, OSError):
            continue
    return result


def build_jar_index(
    jar_path: Path, profile: VersionProfile
) -> tuple[JarIndex | None, ScanError | None]:
    """Open ``jar_path`` once and read everything the detectors need."""
    try:
        sha256 = hashlib.sha256(jar_path.read_bytes()).hexdigest()
        with zipfile.ZipFile(jar_path) as zf:
            names = zf.namelist()
            try:
                raw = zf.read(FABRIC_METADATA)
            except KeyError:
                return None, ScanError(
                    jar=jar_path.name, reason="no fabric.mod.json (not a Fabric mod)"
                )
            mod, error = _metadata_to_mod(raw, jar_path.name)
            if error is not None:
                return None, error
            assert mod is not None
            mixin_classes, mixin_methods = _collect_mixin_targets(zf, names)
            nested = _collect_nested(zf, names)
            index = JarIndex(
                jar=jar_path.name,
                mod=mod,
                sha256=sha256,
                recipes=_read_data_jsons(zf, names, profile.recipe_path),
                item_tags=_read_data_jsons(zf, names, profile.tag_path),
                mixin_targets=mixin_classes | nested.mixin_classes,
                mixin_method_targets=mixin_methods | nested.mixin_methods,
                bundled_ids=nested.ids,
            )
    except zipfile.BadZipFile:
        return None, ScanError(jar=jar_path.name, reason="not a valid jar/zip")
    except OSError as exc:
        return None, ScanError(jar=jar_path.name, reason=f"could not read jar: {exc}")
    return index, None


def read_mods_metadata(folder: Path) -> tuple[list[Mod], list[ScanError]]:
    """Cheap first pass for version detection: read only each jar's metadata.

    Opens every top-level ``.jar`` and parses just its ``fabric.mod.json`` (no
    recipes/tags/mixins), so :func:`app.profile.detect_version` can choose a
    profile *before* the full, profile-dependent scan runs.
    """
    mods: list[Mod] = []
    errors: list[ScanError] = []
    for jar_path in sorted(folder.glob("*.jar")):
        try:
            with zipfile.ZipFile(jar_path) as zf:
                try:
                    raw = zf.read(FABRIC_METADATA)
                except KeyError:
                    errors.append(
                        ScanError(jar=jar_path.name, reason="no fabric.mod.json (not a Fabric mod)")
                    )
                    continue
        except zipfile.BadZipFile:
            errors.append(ScanError(jar=jar_path.name, reason="not a valid jar/zip"))
            continue
        except OSError as exc:
            errors.append(ScanError(jar=jar_path.name, reason=f"could not read jar: {exc}"))
            continue
        mod, error = _metadata_to_mod(raw, jar_path.name)
        if error is not None:
            errors.append(error)
        elif mod is not None:
            mods.append(mod)
    return mods, errors


def scan_mods_folder(folder: Path, version: str) -> ScanResult:
    """Scan every top-level ``.jar`` in ``folder`` and detect static conflicts."""
    version_profile = resolve_profile(version)
    jars = sorted(folder.glob("*.jar"))
    indexes: list[JarIndex] = []
    untestable: list[UntestableMod] = []
    errors: list[ScanError] = []

    for jar_path in jars:
        index, error = build_jar_index(jar_path, version_profile)
        if error is not None:
            errors.append(error)
            continue
        assert index is not None
        indexes.append(index)
        if index.mod.environment == "client":
            untestable.append(UntestableMod(id=index.mod.id, reason=CLIENT_REASON))

    conflicts = detect_conflicts(indexes, version_profile)
    mods = [index.mod for index in indexes]
    counts = ScanCounts(
        total=len(jars),
        mods=len(mods),
        testable=len(mods) - len(untestable),
        untestable=len(untestable),
        errors=len(errors),
        conflicts=len(conflicts),
    )
    return ScanResult(
        profile=version_profile.profile,
        mods_path=str(folder),
        mods=mods,
        untestable=untestable,
        conflicts=conflicts,
        errors=errors,
        counts=counts,
    )
