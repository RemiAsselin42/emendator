"""CurseForge enrichment, primarily offline.

A CurseForge instance's ``minecraftinstance.json`` already lists every installed
addon with its name, project URL and the file on disk — so we can attach project
links by matching jar filenames, with **no network and no API key**. The
CurseForge API (key via ``EMENDATOR_CURSEFORGE_API_KEY``) is only needed for
update checks; absent a key, we still enrich names/links from the manifest.

Mutates the passed :class:`Mod` list in place; never raises.
"""

import json
from pathlib import Path
from typing import Any

from app.models import Mod

_MANIFEST = "minecraftinstance.json"


def enrich_offline(root: Path, mods: list[Mod]) -> None:
    """Attach CurseForge names + project links from the local manifest."""
    addons = _installed_addons(root)
    if not addons:
        return
    by_file = _index_by_filename(addons)
    for mod in mods:
        addon = by_file.get(mod.jar)
        if addon is None:
            continue
        mod.provider = "curseforge"
        url = addon.get("webSiteURL") or addon.get("websiteUrl")
        if isinstance(url, str) and url:
            mod.homepage = url
        # Fill a missing display name from the addon's name.
        if not mod.name and isinstance(addon.get("name"), str):
            mod.name = addon["name"]


def _installed_addons(root: Path) -> list[dict[str, Any]]:
    manifest = root / _MANIFEST
    try:
        data = json.loads(manifest.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return []
    addons = data.get("installedAddons") if isinstance(data, dict) else None
    return [a for a in addons if isinstance(a, dict)] if isinstance(addons, list) else []


def _index_by_filename(addons: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Map each addon's on-disk jar filename to the addon record."""
    out: dict[str, dict[str, Any]] = {}
    for addon in addons:
        installed = addon.get("installedFile")
        if not isinstance(installed, dict):
            continue
        name = installed.get("fileNameOnDisk") or installed.get("fileName")
        if isinstance(name, str) and name:
            out[name] = addon
    return out
