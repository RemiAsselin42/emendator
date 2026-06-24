"""Resolve a dropped path into an :class:`Instance` (launcher-native ingestion).

Emendator historically took a bare ``mods/`` folder. Launchers instead lay out a
whole instance — ``mods/``, ``resourcepacks/``, ``saves/`` —
next to a manifest that names the pack, loader and Minecraft version. This module
recognises the common launchers from their manifest and locates those content
sub-folders, so the rest of the pipeline can scan them uniformly. A folder that
is just full of jars (the old input) stays supported as ``raw_mods``.

Detection is best-effort and offline: an unrecognised or malformed manifest never
raises — we fall back to scanning whatever folders are present.
"""

import json
from pathlib import Path

from app.models import Instance, InstanceFolders, Loader

_CF_MANIFEST = "minecraftinstance.json"
_MODRINTH_MANIFEST = "profile.json"
_PRISM_CFG = "instance.cfg"
_PRISM_PACK = "mmc-pack.json"

# mmc-pack component uid -> loader (Prism/MultiMC).
_PRISM_UID_LOADER: dict[str, Loader] = {
    "net.minecraftforge": "forge",
    "net.neoforged": "neoforge",
    "net.fabricmc.fabric-loader": "fabric",
    "org.quiltmc.quilt-loader": "quilt",
}


def detect_instance(root: Path) -> Instance:
    """Classify ``root`` and resolve its content folders into an :class:`Instance`."""
    root = root.resolve()
    cf = root / _CF_MANIFEST
    if cf.is_file():
        return _curseforge(root, cf)
    modrinth = root / _MODRINTH_MANIFEST
    if modrinth.is_file():
        inst = _modrinth(root, modrinth)
        if inst is not None:
            return inst
    prism = _prism(root)
    if prism is not None:
        return prism
    # A bare folder of jars dropped directly (the historical input): the mods
    # are the root itself, not a `mods/` sub-folder.
    if _count_jars(root) > 0 and not (root / "mods").is_dir():
        return _build(
            root, "raw_mods", base=root, name=None, loader="unknown", mc_version=None, mods_dir=root
        )
    # A .minecraft-style layout with no recognised manifest.
    return _build(root, "vanilla", base=root, name=root.name, loader="unknown", mc_version=None)


def mods_jars(instance: Instance) -> list[Path]:
    """The top-level ``.jar`` files in the instance's mods folder (sorted)."""
    if not instance.folders.mods:
        return []
    return sorted(Path(instance.folders.mods).glob("*.jar"))


# --- launcher-specific parsing ------------------------------------------------


def _curseforge(root: Path, manifest: Path) -> Instance:
    data = _read_json(manifest) or {}
    name = data.get("name") if isinstance(data.get("name"), str) else None
    base_loader = data.get("baseModLoader")
    mc = data.get("gameVersion")
    if not isinstance(mc, str) and isinstance(base_loader, dict):
        mc = base_loader.get("minecraftVersion")
    return _build(
        root,
        "curseforge",
        base=root,
        name=name,
        loader=_cf_loader(base_loader),
        mc_version=mc if isinstance(mc, str) else None,
    )


def _cf_loader(base_loader: object) -> Loader:
    if not isinstance(base_loader, dict):
        return "unknown"
    name = str(base_loader.get("name", "")).lower()
    for key in ("neoforge", "fabric", "quilt", "forge"):
        if name.startswith(key):
            return key  # type: ignore[return-value]
    return "unknown"


def _modrinth(root: Path, manifest: Path) -> Instance | None:
    data = _read_json(manifest)
    if not isinstance(data, dict):
        return None
    meta = data.get("metadata") if isinstance(data.get("metadata"), dict) else None
    looks_modrinth = meta is not None or "game_version" in data or "install_stage" in data
    if not looks_modrinth and not (root / "mods").is_dir():
        return None
    src = meta or data
    name = src.get("name")
    mc = src.get("game_version")
    return _build(
        root,
        "modrinth",
        base=root,
        name=name if isinstance(name, str) else None,
        loader=_normalize_loader(src.get("loader")),
        mc_version=mc if isinstance(mc, str) else None,
    )


def _prism(root: Path) -> Instance | None:
    cfg = root / _PRISM_CFG
    pack = root / _PRISM_PACK
    if not cfg.is_file() and not pack.is_file():
        return None
    base = root / ".minecraft"
    src_name = "prism"
    if not base.is_dir():
        base = root / "minecraft"
        src_name = "multimc"
    if not base.is_dir():
        return None
    name = _ini_value(cfg, "name") if cfg.is_file() else root.name
    loader, mc = _prism_components(pack)
    return _build(root, src_name, base=base, name=name, loader=loader, mc_version=mc)  # type: ignore[arg-type]


def _prism_components(pack: Path) -> tuple[Loader, str | None]:
    data = _read_json(pack)
    loader: Loader = "unknown"
    mc: str | None = None
    if not isinstance(data, dict):
        return loader, mc
    components = data.get("components")
    if not isinstance(components, list):
        return loader, mc
    for comp in components:
        if not isinstance(comp, dict):
            continue
        uid = comp.get("uid")
        version = comp.get("version")
        if uid == "net.minecraft" and isinstance(version, str):
            mc = version
        elif isinstance(uid, str) and uid in _PRISM_UID_LOADER:
            loader = _PRISM_UID_LOADER[uid]
    return loader, mc


# --- folder resolution + counts ----------------------------------------------


def _build(
    root: Path,
    source: str,
    *,
    base: Path,
    name: str | None,
    loader: Loader,
    mc_version: str | None,
    mods_dir: Path | None = None,
) -> Instance:
    """Assemble an :class:`Instance` from a resolved base directory.

    ``mods_dir`` overrides where mods live (used by ``raw_mods``, whose jars sit
    in the dropped folder itself rather than a ``mods/`` sub-folder).
    """
    mods = mods_dir if mods_dir is not None else base / "mods"
    resourcepacks = base / "resourcepacks"
    config = base / "config"
    datapacks = _datapack_dirs(base)
    folders = InstanceFolders(
        mods=_dir_or_none(mods),
        resourcepacks=_dir_or_none(resourcepacks),
        config=_dir_or_none(config),
        datapacks=datapacks,
    )
    return Instance(
        root=str(root),
        source=source,  # type: ignore[arg-type]
        name=name,
        loader=loader,
        mc_version=mc_version,
        folders=folders,
        mod_count=_count_jars(mods),
        resourcepack_count=_count_packs(resourcepacks),
        datapack_count=sum(_count_packs(Path(d)) for d in datapacks),
    )


def _datapack_dirs(base: Path) -> list[str]:
    """Every datapack directory: a global ``datapacks/`` plus each world's."""
    out: list[str] = []
    glob_dp = base / "datapacks"
    if glob_dp.is_dir():
        out.append(str(glob_dp))
    saves = base / "saves"
    if saves.is_dir():
        for world in sorted(saves.iterdir()):
            world_dp = world / "datapacks"
            if world_dp.is_dir():
                out.append(str(world_dp))
    return out


def _dir_or_none(path: Path) -> str | None:
    return str(path) if path.is_dir() else None


def _count_jars(folder: Path) -> int:
    return len(list(folder.glob("*.jar"))) if folder.is_dir() else 0


def _count_packs(folder: Path) -> int:
    """Pack-like entries: a ``.zip`` file or a sub-directory."""
    if not folder.is_dir():
        return 0
    return sum(1 for e in folder.iterdir() if e.is_dir() or e.suffix.lower() == ".zip")


# --- small helpers ------------------------------------------------------------


def _read_json(path: Path) -> dict | None:
    """Read a top-level JSON object, or ``None`` on any error / non-object."""
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _ini_value(path: Path, key: str) -> str | None:
    """Read ``key=value`` from a simple INI file (Prism ``instance.cfg``)."""
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip()
    except OSError:
        return None
    return None


def _normalize_loader(value: object) -> Loader:
    text = str(value).lower() if value is not None else ""
    for key in ("neoforge", "fabric", "quilt", "forge"):
        if key in text:
            return key  # type: ignore[return-value]
    return "unknown"
