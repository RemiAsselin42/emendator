"""Discover modpack instances already installed by the common launchers.

Scans the well-known instance directories of CurseForge, Modrinth, Prism and
MultiMC (plus the vanilla ``.minecraft``) and resolves each child folder with
:func:`detect_instance`, keeping only those that actually contain mods. The
launcher the folder came from is trusted as the ``source`` (Modrinth App profiles
often carry no per-folder manifest, so detection alone can't tell them apart).

Best-effort and offline: missing directories and unreadable folders are skipped.
Cross-platform paths are probed; non-existent ones are simply ignored.
"""

import os
from pathlib import Path

from app.models import Instance, InstanceSource
from app.sources.instance import detect_instance

# Cap the list so an unusual setup can't make discovery unbounded.
_MAX_DISCOVERED = 80


def discover_instances() -> list[Instance]:
    """Every installed instance with mods, across known launchers (deduped)."""
    seen: set[str] = set()
    out: list[Instance] = []

    for parent, source in _candidate_parents():
        if not parent.is_dir():
            continue
        try:
            children = sorted(p for p in parent.iterdir() if p.is_dir())
        except OSError:
            continue
        for child in children:
            inst = _resolve(child, source, seen)
            if inst is not None:
                out.append(inst)

    for single, source in _candidate_singles():
        inst = _resolve(single, source, seen)
        if inst is not None:
            out.append(inst)

    # Richest packs first, then alphabetical — the most likely picks on top.
    out.sort(key=lambda i: (-i.mod_count, (i.name or "").lower()))
    return out[:_MAX_DISCOVERED]


def _resolve(root: Path, source: InstanceSource, seen: set[str]) -> Instance | None:
    """Detect ``root`` as an instance, trust the launcher ``source``, dedupe."""
    try:
        if not root.is_dir():
            return None
        inst = detect_instance(root)
    except OSError:
        return None
    if inst.mod_count == 0:  # not a modpack (empty or freshly-created profile)
        return None
    if inst.root in seen:
        return None
    seen.add(inst.root)
    inst.source = source
    if not inst.name:
        inst.name = root.name
    return inst


def _env_path(var: str) -> Path | None:
    value = os.environ.get(var)
    return Path(value) if value else None


def _candidate_parents() -> list[tuple[Path, InstanceSource]]:
    """Directories whose children are instances, paired with their launcher source."""
    home = Path.home()
    appdata = _env_path("APPDATA")  # Windows roaming
    userprofile = _env_path("USERPROFILE") or home
    mac = home / "Library" / "Application Support"
    config = home / ".config"
    share = home / ".local" / "share"

    parents: list[tuple[Path, InstanceSource]] = [
        (userprofile / "curseforge" / "minecraft" / "Instances", "curseforge"),
        (home / "curseforge" / "minecraft" / "Instances", "curseforge"),
    ]
    for base in _existing(appdata, config, share, mac):
        parents.append((base / "ModrinthApp" / "profiles", "modrinth"))
        parents.append((base / "com.modrinth.theseus" / "profiles", "modrinth"))
        parents.append((base / "PrismLauncher" / "instances", "prism"))
    for base in _existing(appdata):
        parents.append((base / "MultiMC" / "instances", "multimc"))
    return _dedupe(parents)


def _candidate_singles() -> list[tuple[Path, InstanceSource]]:
    """Single-instance roots (the vanilla ``.minecraft`` per platform)."""
    home = Path.home()
    appdata = _env_path("APPDATA")
    singles: list[tuple[Path, InstanceSource]] = [(home / ".minecraft", "vanilla")]
    if appdata:
        singles.append((appdata / ".minecraft", "vanilla"))
    singles.append((home / "Library" / "Application Support" / "minecraft", "vanilla"))
    return _dedupe(singles)


def _existing(*paths: Path | None) -> list[Path]:
    return [p for p in paths if p is not None]


def _dedupe(pairs: list[tuple[Path, InstanceSource]]) -> list[tuple[Path, InstanceSource]]:
    out: list[tuple[Path, InstanceSource]] = []
    seen: set[str] = set()
    for path, source in pairs:
        key = str(path)
        if key not in seen:
            seen.add(key)
            out.append((path, source))
    return out
