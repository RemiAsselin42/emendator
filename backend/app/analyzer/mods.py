"""Ingest a Fabric ``mods/`` folder into the conflict-map model.

Each ``.jar`` is opened as a zip and its ``fabric.mod.json`` is read. Jars
without that metadata (plain libraries, non-Fabric mods) or that fail to parse
are not fatal: they are collected as :class:`ScanError` so the UI can report
them without aborting the whole scan.

Only top-level jars are scanned in Phase 0; nested jars (``jars`` field /
``META-INF/jars``) are deferred to the static analyzer (Phase 1).
"""

import json
import zipfile
from pathlib import Path

from app.models import (
    Environment,
    Mod,
    ScanCounts,
    ScanError,
    ScanResult,
    UntestableMod,
)

FABRIC_METADATA = "fabric.mod.json"
CLIENT_REASON = "environment:client not loaded by server boot"
_VALID_ENVIRONMENTS: tuple[Environment, ...] = ("server", "client", "*")


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


def parse_jar(jar_path: Path) -> tuple[Mod | None, ScanError | None]:
    """Parse one jar. Returns ``(mod, None)`` on success or ``(None, error)``."""
    try:
        with zipfile.ZipFile(jar_path) as zf:
            raw = zf.read(FABRIC_METADATA)
    except KeyError:
        return None, ScanError(jar=jar_path.name, reason="no fabric.mod.json (not a Fabric mod)")
    except zipfile.BadZipFile:
        return None, ScanError(jar=jar_path.name, reason="not a valid jar/zip")
    except OSError as exc:
        return None, ScanError(jar=jar_path.name, reason=f"could not read jar: {exc}")

    try:
        # strict=False tolerates literal control characters (newlines/tabs) that
        # real fabric.mod.json files embed in string values; Fabric's own loader
        # is lenient here, so we must be too (e.g. Debugify).
        data = json.loads(raw, strict=False)
    except json.JSONDecodeError as exc:
        return None, ScanError(jar=jar_path.name, reason=f"invalid fabric.mod.json: {exc}")

    if not isinstance(data, dict):
        return None, ScanError(jar=jar_path.name, reason="fabric.mod.json is not an object")

    mod_id = data.get("id")
    if not isinstance(mod_id, str) or not mod_id:
        return None, ScanError(jar=jar_path.name, reason="fabric.mod.json missing 'id'")

    depends = data.get("depends")
    mod = Mod(
        id=mod_id,
        name=data.get("name") if isinstance(data.get("name"), str) else None,
        version=str(data["version"]) if "version" in data else None,
        mc_version=_coerce_mc_version(depends),
        environment=_coerce_environment(data.get("environment")),
        depends=depends if isinstance(depends, dict) else {},
        jar=jar_path.name,
    )
    return mod, None


def scan_mods_folder(folder: Path, profile: str) -> ScanResult:
    """Scan every top-level ``.jar`` in ``folder`` into a :class:`ScanResult`."""
    jars = sorted(folder.glob("*.jar"))
    mods: list[Mod] = []
    untestable: list[UntestableMod] = []
    errors: list[ScanError] = []

    for jar_path in jars:
        mod, error = parse_jar(jar_path)
        if error is not None:
            errors.append(error)
            continue
        assert mod is not None  # parse_jar returns exactly one of (mod, error)
        mods.append(mod)
        if mod.environment == "client":
            untestable.append(UntestableMod(id=mod.id, reason=CLIENT_REASON))

    counts = ScanCounts(
        total=len(jars),
        mods=len(mods),
        testable=len(mods) - len(untestable),
        untestable=len(untestable),
        errors=len(errors),
    )
    return ScanResult(
        profile=profile,
        mods_path=str(folder),
        mods=mods,
        untestable=untestable,
        errors=errors,
        counts=counts,
    )
