"""Online metadata enrichment, best-effort and offline-first.

Orchestrates the providers over a scanned set: CurseForge first (offline, from the
instance manifest) for CurseForge instances, then Modrinth (hashed lookup +
update check) for everything. Controlled by ``settings.enrich_online``; any
failure is swallowed so a scan is never blocked or broken by enrichment.
"""

from pathlib import Path

from app.config import settings
from app.enrich import curseforge, modrinth
from app.models import Instance, Loader, Mod


def enrich_mods(instance: Instance, jars: list[Path], mods: list[Mod], game_version: str) -> None:
    """Enrich ``mods`` in place with provider links + update status.

    ``game_version`` is the exact version the scan resolved to (the Modrinth
    update check needs a concrete version, not a range).
    """
    if not settings.enrich_online or not mods:
        return
    try:
        if instance.source == "curseforge":
            curseforge.enrich_offline(Path(instance.root), mods)
        modrinth.enrich(jars, mods, game_version, _loader(instance, mods))
    except Exception:  # noqa: BLE001 — enrichment must never break a scan
        return


def _loader(instance: Instance, mods: list[Mod]) -> Loader:
    """The loader to query updates for: instance manifest, else the mods' own."""
    if instance.loader != "unknown":
        return instance.loader
    for mod in mods:
        if mod.loader != "unknown":
            return mod.loader
    return "unknown"
