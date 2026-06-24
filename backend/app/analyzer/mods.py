"""Ingest a mod set (Fabric/Quilt/Forge/NeoForge) and run static conflict detection.

Each ``.jar`` is opened **once**: its loader metadata becomes a :class:`Mod`
(see :mod:`app.analyzer.metadata`), and the files the detectors need (recipes,
item tags, mixin target classes — located via the :class:`VersionProfile`, never
hardcoded) are read into a :class:`JarIndex`. Detection then runs purely in
memory.

Jars without recognized loader metadata, or that fail to parse, are non-fatal:
they are collected as :class:`ScanError`. Only top-level jars are scanned (nested
``META-INF/jars`` deferred).
"""

import hashlib
import io
import json
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.analyzer.detectors import JarIndex, detect_conflicts
from app.analyzer.metadata import FABRIC_METADATA, parse_mod_metadata
from app.analyzer.mixin_targets import extract_mixin_targets
from app.models import (
    Mod,
    ScanCounts,
    ScanError,
    ScanResult,
    UntestableMod,
)
from app.profile import VersionProfile, resolve_profile

CLIENT_REASON = "environment:client not loaded by server boot"
_MIXIN_SECTIONS = ("mixins", "client", "server")


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
            mod, error = parse_mod_metadata(zf, names, jar_path.name)
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


def read_jars_metadata(jars: list[Path]) -> tuple[list[Mod], list[ScanError]]:
    """Cheap first pass for version detection: read only each jar's metadata.

    Opens every jar and parses just its loader metadata (no recipes/tags/mixins),
    so :func:`app.profile.detect_version` can choose a profile *before* the full,
    profile-dependent scan runs.
    """
    mods: list[Mod] = []
    errors: list[ScanError] = []
    for jar_path in jars:
        try:
            with zipfile.ZipFile(jar_path) as zf:
                mod, error = parse_mod_metadata(zf, zf.namelist(), jar_path.name)
        except zipfile.BadZipFile:
            errors.append(ScanError(jar=jar_path.name, reason="not a valid jar/zip"))
            continue
        except OSError as exc:
            errors.append(ScanError(jar=jar_path.name, reason=f"could not read jar: {exc}"))
            continue
        if error is not None:
            errors.append(error)
        elif mod is not None:
            mods.append(mod)
    return mods, errors


def read_mods_metadata(folder: Path) -> tuple[list[Mod], list[ScanError]]:
    """:func:`read_jars_metadata` over every top-level ``.jar`` in ``folder``."""
    return read_jars_metadata(sorted(folder.glob("*.jar")))


def scan_jars(
    jars: list[Path],
    profile: VersionProfile,
    mods_path: str = "",
    on_progress: Callable[[int, int], None] | None = None,
) -> ScanResult:
    """Scan an explicit list of jars and detect static conflicts.

    The unit the instance layer drives over a resolved ``mods/`` folder;
    :func:`scan_mods_folder` is a thin wrapper that globs a folder.

    ``on_progress(done, total)`` is invoked after each jar is indexed (the
    dominant per-jar cost), so a caller can stream live scan progress.
    """
    indexes: list[JarIndex] = []
    untestable: list[UntestableMod] = []
    errors: list[ScanError] = []

    total = len(jars)
    for done, jar_path in enumerate(jars, start=1):
        index, error = build_jar_index(jar_path, profile)
        if on_progress is not None:
            on_progress(done, total)
        if error is not None:
            errors.append(error)
            continue
        assert index is not None
        indexes.append(index)
        if index.mod.environment == "client":
            untestable.append(UntestableMod(id=index.mod.id, reason=CLIENT_REASON))

    conflicts = detect_conflicts(indexes, profile)
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
        profile=profile.profile,
        mods_path=mods_path,
        mods=mods,
        untestable=untestable,
        conflicts=conflicts,
        errors=errors,
        counts=counts,
    )


def scan_mods_folder(folder: Path, version: str) -> ScanResult:
    """Scan every top-level ``.jar`` in ``folder`` and detect static conflicts."""
    return scan_jars(sorted(folder.glob("*.jar")), resolve_profile(version), str(folder))
