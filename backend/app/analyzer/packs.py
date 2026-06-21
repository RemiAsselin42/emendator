"""Inventory and override detection for content beyond mods.

Resource packs (``resourcepacks/``), datapacks (a global ``datapacks/`` plus each
world's ``saves/<world>/datapacks``) and shader packs (``shaderpacks/``) each ship
as a ``.zip`` or a folder. We read ``pack.mcmeta`` for a quick inventory, and for
resource packs / datapacks we flag **overrides**: the same inner path provided by
two or more packs (a texture, a recipe, a loot table). Overrides are expected —
load order decides the winner — so they are ``info``: a heads-up, not an error.
"""

import json
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.models import Conflict, ConflictType, Datapack, ResourcePack, ShaderPack

_MCMETA = "pack.mcmeta"
# Cap the path list embedded in an override conflict; the count carries the rest.
_MAX_OVERRIDE_PATHS = 50


def scan_resourcepacks(folder: Path | None) -> tuple[list[ResourcePack], list[Conflict]]:
    """Inventory ``resourcepacks/`` and flag assets overridden by ≥2 packs."""
    packs: list[ResourcePack] = []
    by_source: dict[str, set[str]] = {}
    for entry in _pack_candidates(folder):
        meta, files = _read_pack(entry)
        pack_format, description = _pack_meta(meta)
        assets = {f for f in files if f.startswith("assets/")}
        source = "zip" if entry.suffix.lower() == ".zip" else "dir"
        packs.append(
            ResourcePack(
                name=entry.name,
                pack_format=pack_format,
                description=description,
                asset_count=len(assets),
                source=source,
            )
        )
        by_source[entry.name] = assets
    return packs, _overrides(by_source, "asset_override")


def scan_datapacks(dirs: list[str]) -> tuple[list[Datapack], list[Conflict]]:
    """Inventory every datapack directory and flag data overridden by ≥2 packs."""
    packs: list[Datapack] = []
    by_source: dict[str, set[str]] = {}
    for raw_dir in dirs:
        dp_dir = Path(raw_dir)
        location = dp_dir.parent.name  # the world (or instance) folder name
        for entry in _pack_candidates(dp_dir):
            meta, files = _read_pack(entry)
            pack_format, description = _pack_meta(meta)
            data_files = {f for f in files if f.startswith("data/")}
            source = "zip" if entry.suffix.lower() == ".zip" else "dir"
            packs.append(
                Datapack(
                    name=entry.name,
                    location=location,
                    pack_format=pack_format,
                    description=description,
                    data_count=len(data_files),
                    source=source,
                )
            )
            # Key by world + pack so identically-named packs in different worlds
            # don't get merged (and don't false-collide across worlds).
            by_source[f"{location}/{entry.name}"] = data_files
    return packs, _overrides(by_source, "datapack_override")


def scan_shaderpacks(folder: Path | None) -> list[ShaderPack]:
    """Inventory ``shaderpacks/`` (opaque — listed only, no override analysis)."""
    return [
        ShaderPack(name=entry.name, source="zip" if entry.suffix.lower() == ".zip" else "dir")
        for entry in _pack_candidates(folder)
    ]


# --- override detection -------------------------------------------------------


def _overrides(by_source: dict[str, set[str]], conflict_type: ConflictType) -> list[Conflict]:
    """Group inner paths owned by ≥2 packs into one conflict per colliding set.

    Mirrors :func:`detect_recipe_collisions` for content packs but keys on the
    raw inner path (no id parsing): any file two packs both ship is an override.
    """
    path_owners: dict[str, set[str]] = defaultdict(set)
    for source, paths in by_source.items():
        for path in paths:
            path_owners[path].add(source)

    by_members: dict[frozenset[str], list[str]] = defaultdict(list)
    for path, owners in path_owners.items():
        if len(owners) > 1:
            by_members[frozenset(owners)].append(path)

    conflicts: list[Conflict] = []
    for members, paths in by_members.items():
        ordered = sorted(paths)
        conflicts.append(
            Conflict(
                type=conflict_type,
                severity="info",
                members=sorted(members),
                detail={"paths": ordered[:_MAX_OVERRIDE_PATHS], "count": len(ordered)},
            )
        )
    conflicts.sort(key=lambda c: (-len(c.detail.get("paths", [])), c.members))
    return conflicts


# --- pack reading -------------------------------------------------------------


def _pack_candidates(folder: Path | None) -> list[Path]:
    """Pack-like entries in ``folder``: each ``.zip`` file or sub-directory."""
    if folder is None or not folder.is_dir():
        return []
    entries = [e for e in folder.iterdir() if e.is_dir() or e.suffix.lower() == ".zip"]
    return sorted(entries, key=lambda p: p.name)


def _read_pack(entry: Path) -> tuple[dict[str, Any] | None, list[str]]:
    """``(parsed pack.mcmeta, inner file paths)`` for a zip or folder pack."""
    if entry.is_file() and entry.suffix.lower() == ".zip":
        try:
            with zipfile.ZipFile(entry) as zf:
                names = [n for n in zf.namelist() if not n.endswith("/")]
                meta = _parse_mcmeta(zf.read(_MCMETA)) if _MCMETA in set(names) else None
        except (zipfile.BadZipFile, OSError, KeyError):
            return None, []
        return meta, names
    if entry.is_dir():
        names = [p.relative_to(entry).as_posix() for p in entry.rglob("*") if p.is_file()]
        mcmeta = entry / _MCMETA
        meta = _parse_mcmeta(mcmeta.read_bytes()) if mcmeta.is_file() else None
        return meta, names
    return None, []


def _parse_mcmeta(raw: bytes) -> dict[str, Any] | None:
    try:
        data = json.loads(raw, strict=False)
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _pack_meta(meta: dict[str, Any] | None) -> tuple[int | None, str | None]:
    """Pull ``pack_format`` and a string ``description`` out of ``pack.mcmeta``."""
    if not isinstance(meta, dict):
        return None, None
    pack = meta.get("pack")
    if not isinstance(pack, dict):
        return None, None
    fmt = pack.get("pack_format")
    desc = pack.get("description")
    return (
        fmt if isinstance(fmt, int) else None,
        desc if isinstance(desc, str) else None,
    )
