"""Ingest a mod set (Fabric/Quilt/Forge/NeoForge) and run static conflict detection.

Each ``.jar`` is opened **once**: its loader metadata becomes a :class:`Mod`
(see :mod:`app.analyzer.metadata`), and the files the detectors need (recipes,
item tags, mixin target classes — located via the :class:`VersionProfile`, never
hardcoded) are read into a :class:`JarIndex`. Detection then runs purely in
memory.

Jars without recognized loader metadata, or that fail to parse, are non-fatal:
they are collected as :class:`ScanError`. Nested jars (jars-in-jars) contribute
their mod ids and mixins; nested recipes/tags are intentionally excluded (see
:func:`_collect_nested`).
"""

import hashlib
import io
import json
import re
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.analyzer.detectors import JarIndex, MixinMethodPatch, MixinToggleSystem, detect_conflicts
from app.analyzer.metadata import FABRIC_METADATA, QUILT_METADATA, parse_mod_metadata
from app.analyzer.mixin_targets import (
    DEFAULT_PRIORITY,
    INSTRUCTION_EXCLUSIVE_KINDS,
    MixinTargets,
    class_string_constants,
    extract_mixin_targets,
)
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


@dataclass
class _JarMixins:
    """The jar-level mixin footprint: flattened targets + per-method patch info."""

    classes: set[str] = field(default_factory=set)
    methods: set[str] = field(default_factory=set)
    patches: dict[str, MixinMethodPatch] = field(default_factory=dict)
    toggles: MixinToggleSystem | None = None

    def merge(self, other: "_JarMixins") -> None:
        self.classes |= other.classes
        self.methods |= other.methods
        for key, patch in other.patches.items():
            self.patches.setdefault(key, MixinMethodPatch()).merge(patch)
        self._merge_toggles(other.toggles)

    def _merge_toggles(self, toggles: MixinToggleSystem | None) -> None:
        """Union keys when the same file, keep the first system otherwise."""
        if toggles is None:
            return
        if self.toggles is None:
            self.toggles = toggles
        elif self.toggles.file == toggles.file:
            self.toggles.keys.update(toggles.keys)

    def add(self, targets: MixinTargets, priority: int, required: bool, mixin_class: str) -> None:
        """Fold one mixin class's extraction in; ``priority``/``required`` are config defaults."""
        self.classes |= targets.classes
        self.methods |= targets.methods
        effective = targets.priority if targets.priority is not None else priority
        for injection in targets.injections:
            owners = [injection.owner] if injection.owner else sorted(targets.classes)
            for owner in owners:
                patch = self.patches.setdefault(f"{owner}#{injection.method}", MixinMethodPatch())
                patch.kinds.add(injection.kind)
                patch.priorities.add(effective)
                patch.required = patch.required or required
                patch.mixin_classes.add(mixin_class)
                if injection.kind in INSTRUCTION_EXCLUSIVE_KINDS:
                    patch.exclusive_at.update(injection.at_targets)


def _declared_mixin_configs(zf: zipfile.ZipFile, names: list[str]) -> set[str]:
    """Mixin config paths declared in loader metadata, whatever their file name.

    The suffix glob (``*.mixins.json``) catches the convention; this catches the
    rest: Fabric's ``"mixins"`` array (strings or ``{"config": ...}`` objects),
    Quilt's ``"mixin"`` (string or list), and the Forge/NeoForge
    ``MixinConfigs`` manifest attribute (comma-separated).
    """
    declared: set[str] = set()
    present = set(names)

    def _entries(value: Any) -> list[str]:
        out: list[str] = []
        for entry in value if isinstance(value, list) else [value]:
            if isinstance(entry, str) and entry:
                out.append(entry)
            elif isinstance(entry, dict) and isinstance(entry.get("config"), str):
                out.append(entry["config"])
        return out

    for metadata_name, key in ((FABRIC_METADATA, "mixins"), (QUILT_METADATA, "mixin")):
        if metadata_name not in present:
            continue
        try:
            data = json.loads(zf.read(metadata_name), strict=False)
        except (json.JSONDecodeError, KeyError, OSError):
            continue
        if isinstance(data, dict):
            declared.update(_entries(data.get(key)))

    manifest_name = "META-INF/MANIFEST.MF"
    if manifest_name in present:
        try:
            manifest = zf.read(manifest_name).decode("utf-8", "replace")
        except (KeyError, OSError):
            manifest = ""
        # Manifest values wrap at 72 bytes with a leading-space continuation.
        manifest = manifest.replace("\r\n", "\n").replace("\n ", "")
        for line in manifest.splitlines():
            if line.lower().startswith("mixinconfigs:"):
                declared.update(
                    part.strip() for part in line.split(":", 1)[1].split(",") if part.strip()
                )

    return {config for config in declared if config in present}


def _read_refmap(zf: zipfile.ZipFile, name: Any) -> dict[str, dict[str, str]]:
    """The config's refmap json: mixin class (internal name) -> dev selector -> runtime.

    Distributed jars keep annotation *strings* dev-named (Yarn/Mojmap); Mixin
    resolves them at runtime through this file. Reading it makes our extracted
    method/target names runtime-correct — and comparable across mods built
    against different dev mappings. Prefers the loader-specific slice under
    ``data`` (e.g. ``named:intermediary``), falling back to ``mappings``.
    """
    if not isinstance(name, str) or not name:
        return {}
    try:
        data = json.loads(zf.read(name), strict=False)
    except (json.JSONDecodeError, KeyError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    mappings: Any = None
    nested = data.get("data")
    if isinstance(nested, dict):
        for slice_ in nested.values():
            if isinstance(slice_, dict) and slice_:
                mappings = slice_
                break
    if mappings is None:
        mappings = data.get("mappings")
    if not isinstance(mappings, dict):
        return {}
    return {
        cls: {k: v for k, v in entries.items() if isinstance(k, str) and isinstance(v, str)}
        for cls, entries in mappings.items()
        if isinstance(cls, str) and isinstance(entries, dict)
    }


# A CaffeineMC-style plugin holds its properties path as a string constant.
_TOGGLE_PROPERTIES_RE = re.compile(r"^(?:\./)?config/([\w.\-]+\.properties)$")
# Debugify encodes the bug id in each mixin's package: ...mixins.basic.mc100991.FooMixin
_DEBUGIFY_BUG_RE = re.compile(r"\.mc(\d+)\.")
_DEBUGIFY_PLUGIN_PREFIX = "dev.isxander.debugify."


def _toggle_properties_file(zf: zipfile.ZipFile, plugin: str) -> str | None:
    """The CaffeineMC-style properties path baked into the config's plugin class.

    Sodium/Lithium/ModernFix (and clones) keep the exact file name — e.g.
    ``./config/lithium.properties`` — as a constant in the plugin class that
    loads it. Library adopters resolving the path elsewhere are missed (rare;
    they can be added as known ids later).
    """
    try:
        constants = class_string_constants(zf.read(plugin.replace(".", "/") + ".class"))
    except (KeyError, OSError):
        return None
    for constant in constants:
        match = _TOGGLE_PROPERTIES_RE.match(constant)
        if match:
            return f"config/{match.group(1)}"
    return None


def _toggle_key(kind: str, entry: str, full_class: str) -> str | None:
    """The option key that gates one mixin class, per system.

    CaffeineMC family: ``mixin.<subpackage>`` — per-package granularity, so a
    class sitting directly in the config root has no key. Debugify: the
    ``MC-<id>`` encoded in the package path.
    """
    if kind == "debugify":
        match = _DEBUGIFY_BUG_RE.search(f".{full_class.rsplit('.', 1)[0]}.")
        return f"MC-{match.group(1)}" if match else None
    package, _, _ = entry.rpartition(".")
    return f"mixin.{package}" if package else None


def _collect_mixin_targets(zf: zipfile.ZipFile, names: list[str]) -> _JarMixins:
    """``@Mixin`` targets, ``Class#method`` pairs and patch info across the jar."""
    out = _JarMixins()
    candidates = {name for name in names if name.endswith(".mixins.json")}
    candidates |= _declared_mixin_configs(zf, names)
    for name in sorted(candidates):
        try:
            config = json.loads(zf.read(name), strict=False)
        except (json.JSONDecodeError, KeyError, OSError):
            continue
        if not isinstance(config, dict) or not isinstance(config.get("package"), str):
            continue
        package = config["package"]
        base = package.replace(".", "/")
        refmap = _read_refmap(zf, config.get("refmap"))
        config_priority = config.get("priority")
        default_priority = config_priority if isinstance(config_priority, int) else DEFAULT_PRIORITY
        required = config.get("required") is True
        injectors = config.get("injectors")
        if isinstance(injectors, dict):
            default_require = injectors.get("defaultRequire")
            if isinstance(default_require, int) and default_require >= 1:
                required = True

        plugin = config.get("plugin")
        toggles: MixinToggleSystem | None = None
        if isinstance(plugin, str) and plugin:
            if plugin.startswith(_DEBUGIFY_PLUGIN_PREFIX):
                toggles = MixinToggleSystem(kind="debugify", file="config/debugify.json")
            else:
                properties_file = _toggle_properties_file(zf, plugin)
                if properties_file:
                    toggles = MixinToggleSystem(kind="properties", file=properties_file)

        for section in _MIXIN_SECTIONS:
            mixin_classes = config.get(section)
            if not isinstance(mixin_classes, list):
                continue
            for class_name in mixin_classes:
                if not isinstance(class_name, str):
                    continue
                internal = f"{base}/{class_name.replace('.', '/')}"
                try:
                    targets = extract_mixin_targets(
                        zf.read(f"{internal}.class"), refmap.get(internal)
                    )
                except KeyError:
                    continue
                full_class = f"{package}.{class_name}"
                out.add(targets, default_priority, required, full_class)
                if toggles is not None:
                    key = _toggle_key(toggles.kind, class_name, full_class)
                    if key:
                        toggles.keys[full_class] = key
        if toggles is not None and toggles.keys:
            out._merge_toggles(toggles)
    return out


_MAX_NEST_DEPTH = 4


@dataclass
class _Nested:
    """What we harvest from a jar's nested jars (jars-in-jars)."""

    ids: set[str] = field(default_factory=set)
    mixins: _JarMixins = field(default_factory=_JarMixins)


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
                result.mixins.merge(_collect_mixin_targets(nested, nested_names))
                deeper = _collect_nested(nested, nested_names, depth + 1)
                result.ids |= deeper.ids
                result.mixins.merge(deeper.mixins)
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
            mixins = _collect_mixin_targets(zf, names)
            nested = _collect_nested(zf, names)
            mixins.merge(nested.mixins)
            index = JarIndex(
                jar=jar_path.name,
                mod=mod,
                sha256=sha256,
                recipes=_read_data_jsons(zf, names, profile.recipe_path),
                item_tags=_read_data_jsons(zf, names, profile.tag_path),
                mixin_targets=mixins.classes,
                mixin_method_targets=mixins.methods,
                mixin_method_patches=mixins.patches,
                mixin_toggles=mixins.toggles,
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
