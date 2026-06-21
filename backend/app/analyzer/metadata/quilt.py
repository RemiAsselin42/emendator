"""Parse a Quilt ``quilt.mod.json`` into the common :class:`Mod`.

Quilt's manifest nests everything under ``quilt_loader`` and expresses version
specifiers as a string, or an object with ``any`` (OR) / ``all`` (AND). We
normalise those into the same ``str | list[str]`` shape Fabric uses, so version
detection (:func:`app.profile.detect_version`) treats every loader uniformly.
"""

import json
from typing import Any

from app.models import Mod, ScanError


def _normalize_versions(spec: object) -> str | list[str]:
    """A Quilt version specifier -> a value ``parse_constraint`` understands."""
    if isinstance(spec, str):
        return spec
    if isinstance(spec, dict):
        any_of = spec.get("any")
        if isinstance(any_of, list):  # OR -> a list of constraints
            return [s for s in (_flatten(v) for v in any_of) if s]
        all_of = spec.get("all")
        if isinstance(all_of, list):  # AND -> space-joined (intersection)
            return " ".join(s for s in (_flatten(v) for v in all_of) if s) or "*"
    return "*"


def _flatten(spec: object) -> str:
    """Collapse a single specifier to one string (best-effort)."""
    norm = _normalize_versions(spec)
    return norm if isinstance(norm, str) else " ".join(norm)


def _depends_map(depends: object) -> dict[str, str | list[str]]:
    """Build ``{id: versions}`` from Quilt's depends list, dropping optionals."""
    out: dict[str, str | list[str]] = {}
    if not isinstance(depends, list):
        return out
    for entry in depends:
        if isinstance(entry, str):
            out[entry] = "*"
        elif isinstance(entry, dict) and isinstance(entry.get("id"), str):
            if entry.get("optional") is True:
                continue
            out[entry["id"]] = _normalize_versions(entry.get("versions"))
    return out


def _provides(provides: object) -> list[str]:
    out: list[str] = []
    if not isinstance(provides, list):
        return out
    for entry in provides:
        if isinstance(entry, str):
            out.append(entry)
        elif isinstance(entry, dict) and isinstance(entry.get("id"), str):
            out.append(entry["id"])
    return out


def parse_quilt(raw: bytes, jar_name: str) -> tuple[Mod | None, ScanError | None]:
    """Parse ``quilt.mod.json`` bytes into a :class:`Mod`."""
    try:
        data = json.loads(raw, strict=False)
    except json.JSONDecodeError as exc:
        return None, ScanError(jar=jar_name, reason=f"invalid quilt.mod.json: {exc}")
    if not isinstance(data, dict):
        return None, ScanError(jar=jar_name, reason="quilt.mod.json is not an object")

    loader: Any = data.get("quilt_loader")
    if not isinstance(loader, dict):
        return None, ScanError(jar=jar_name, reason="quilt.mod.json missing 'quilt_loader'")
    mod_id = loader.get("id")
    if not isinstance(mod_id, str) or not mod_id:
        return None, ScanError(jar=jar_name, reason="quilt.mod.json missing 'quilt_loader.id'")

    metadata = loader.get("metadata")
    name = metadata.get("name") if isinstance(metadata, dict) else None
    version = loader.get("version")
    depends = _depends_map(loader.get("depends"))
    mc = depends.get("minecraft")
    mc_version = mc if isinstance(mc, str) else (mc[0] if isinstance(mc, list) and mc else None)
    mod = Mod(
        id=mod_id,
        name=name if isinstance(name, str) else None,
        version=str(version) if version is not None else None,
        mc_version=mc_version,
        environment="*",
        loader="quilt",
        depends=depends,
        provides=_provides(loader.get("provides")),
        jar=jar_name,
    )
    return mod, None
