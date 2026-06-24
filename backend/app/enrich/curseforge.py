"""CurseForge enrichment (offline) and install fallback (online).

A CurseForge instance's ``minecraftinstance.json`` already lists every installed
addon with its name, project URL and the file on disk — so we can attach project
links by matching jar filenames, with **no network and no API key**.

The CurseForge API (key via ``EMENDATOR_CURSEFORGE_API_KEY``) powers the *install
fallback*: when Modrinth has no match for a missing dependency,
:func:`find_install` resolves the loader-declared mod id to a CurseForge project
and returns its newest matching file. Requires a key; mods whose authors opted out
of third-party API distribution expose no ``downloadUrl`` and are skipped.

Mutates the passed :class:`Mod` list in place; never raises.
"""

import json
import logging
from pathlib import Path
from typing import Any

import httpx

from app.enrich import modrinth
from app.models import Loader, Mod

_log = logging.getLogger(__name__)

_MANIFEST = "minecraftinstance.json"

_BASE = "https://api.curseforge.com"
_UA = "emendator/0.1 (modpack analyzer)"
_TIMEOUT = httpx.Timeout(8.0, connect=4.0)
_GAME_ID = 432  # Minecraft
_CLASS_ID_MOD = 6  # the "Mods" category, to exclude resource packs/worlds/etc.
_SHA1_ALGO = 1  # CurseForge HashAlgo enum: 1 = Sha1, 2 = Md5

# CurseForge ModLoaderType enum, per our internal loader.
_LOADER_TYPES: dict[Loader, int] = {"forge": 1, "fabric": 4, "quilt": 5, "neoforge": 6}


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


def find_install(
    mod_id: str, loader: Loader, game_version: str, api_key: str
) -> dict[str, Any] | None:
    """The newest CurseForge file for a missing dependency ``mod_id`` (install fallback).

    Resolves the loader-declared id to a CurseForge project — the id is tried as an
    exact slug first, then a popularity-ranked search — filters the project's files
    to the pack's loader + Minecraft version, and returns the newest one as
    ``{url, filename, sha1, version_number, project_title}``. Returns ``None`` when
    there's no API key, the loader isn't supported, the id is a platform
    pseudo-dependency, nothing matches, or the only matching files have no
    ``downloadUrl`` (the author opted out of third-party API distribution).
    """
    if not api_key or loader not in _LOADER_TYPES or mod_id in modrinth.NOT_INSTALLABLE:
        return None
    project = _resolve_project(mod_id, loader, game_version, api_key)
    if project is None:
        return None
    project_id, title = project
    files = _project_files(project_id, loader, game_version, api_key)
    return _primary_file(files, title) if files else None


def verify_key(api_key: str) -> tuple[bool, str | None]:
    """Probe whether ``api_key`` authenticates against the CurseForge API.

    Returns ``(ok, detail)`` where ``detail`` is a human-readable reason when the
    probe failed — distinguishing a key CurseForge *rejected* (401/403) from an
    API we couldn't *reach* (offline), so the UI can say which. Hits the documented
    validation endpoint ``GET /v1/games`` directly rather than via :func:`_api_get`
    (which hides the status code behind ``None``); a 200 means the key works.
    """
    if not api_key:
        return False, "No key was entered."
    try:
        resp = httpx.get(
            f"{_BASE}/v1/games",
            timeout=_TIMEOUT,
            headers={"User-Agent": _UA, "Accept": "application/json", "x-api-key": api_key},
        )
    except httpx.HTTPError as exc:
        _log.warning("CurseForge key probe could not reach the API: %s", exc)
        return False, "Couldn't reach CurseForge — check your internet connection."
    if resp.status_code == 200:
        return True, None
    _log.warning("CurseForge key probe returned HTTP %s", resp.status_code)
    if resp.status_code in (401, 403):
        return False, (
            f"CurseForge rejected the key (HTTP {resp.status_code}). Copy the whole key "
            "from the developer console — it starts with '$2a$' and is one long line."
        )
    return False, f"CurseForge returned HTTP {resp.status_code}."


def _resolve_project(
    mod_id: str, loader: Loader, game_version: str, api_key: str
) -> tuple[int, str] | None:
    """The CurseForge (id, name) for ``mod_id``: exact slug, then a fuzzy search."""
    exact = _search(api_key, {"slug": mod_id})
    if exact is not None:
        return exact
    return _search(
        api_key,
        {
            "searchFilter": mod_id,
            "gameVersion": game_version,
            "modLoaderType": str(_LOADER_TYPES[loader]),
            "sortField": "2",  # popularity, so the best-known match ranks first
            "sortOrder": "desc",
            "pageSize": "5",
        },
    )


def probe_project(mod_id: str, loader: Loader, api_key: str) -> dict[str, Any] | None:
    """Resolve ``mod_id`` to its CurseForge project by exact slug, ignoring version.

    Mirrors :func:`modrinth.probe_project`: returns ``{title, url}`` when the project
    exists (so the caller can report "exists, but no build for <version>" with a
    direct link), or ``None``. Slug-exact only — no fuzzy match.
    """
    if not api_key or loader not in _LOADER_TYPES or mod_id in modrinth.NOT_INSTALLABLE:
        return None
    hit = _search_hit(api_key, {"slug": mod_id})
    if hit is None:
        return None
    title = hit.get("name")
    links = hit.get("links")
    url = links.get("websiteUrl") if isinstance(links, dict) else None
    if not (isinstance(url, str) and url):
        slug = hit.get("slug")
        url = (
            f"https://www.curseforge.com/minecraft/mc-mods/{slug}"
            if isinstance(slug, str)
            else None
        )
    title = title if isinstance(title, str) and title else mod_id
    return {"title": title, "url": url}


def _search(api_key: str, params: dict[str, str]) -> tuple[int, str] | None:
    """Top hit of ``GET /v1/mods/search`` for the given params: (project id, name)."""
    first = _search_hit(api_key, params)
    if first is None:
        return None
    project_id = first.get("id")
    if not isinstance(project_id, int):
        return None
    name = first.get("name")
    return project_id, name if isinstance(name, str) else str(project_id)


def _search_hit(api_key: str, params: dict[str, str]) -> dict[str, Any] | None:
    """The first ``GET /v1/mods/search`` hit object for the given params, or None."""
    query = {"gameId": str(_GAME_ID), "classId": str(_CLASS_ID_MOD), **params}
    data = _api_get("/v1/mods/search", query, api_key)
    hits = data.get("data") if isinstance(data, dict) else None
    if not isinstance(hits, list) or not hits or not isinstance(hits[0], dict):
        return None
    return hits[0]


def _project_files(
    project_id: int, loader: Loader, game_version: str, api_key: str
) -> list[dict[str, Any]] | None:
    """The project's files for the pack's loader + MC version."""
    params = {
        "gameVersion": game_version,
        "modLoaderType": str(_LOADER_TYPES[loader]),
        "pageSize": "20",
    }
    data = _api_get(f"/v1/mods/{project_id}/files", params, api_key)
    files = data.get("data") if isinstance(data, dict) else None
    if not isinstance(files, list):
        return None
    return [f for f in files if isinstance(f, dict)]


def _primary_file(files: list[dict[str, Any]], title: str) -> dict[str, Any] | None:
    """The newest downloadable file in ``files`` (skips third-party opt-outs)."""
    downloadable = [
        f for f in files if isinstance(f.get("downloadUrl"), str) and f.get("downloadUrl")
    ]
    if not downloadable:
        return None
    newest = max(downloadable, key=lambda f: f.get("fileDate") or "")
    filename = newest.get("fileName")
    if not isinstance(filename, str):
        return None
    return {
        "url": newest["downloadUrl"],
        "filename": filename,
        "sha1": _sha1_of(newest.get("hashes")),
        "version_number": newest.get("displayName"),
        "project_title": title,
    }


def _sha1_of(hashes: Any) -> str | None:
    """The sha1 value out of CurseForge's ``[{value, algo}]`` hash list, if present."""
    if not isinstance(hashes, list):
        return None
    for h in hashes:
        if isinstance(h, dict) and h.get("algo") == _SHA1_ALGO and isinstance(h.get("value"), str):
            return h["value"]
    return None


def _api_get(path: str, params: dict[str, str], api_key: str) -> Any | None:
    """GET seam for the CurseForge API (monkeypatched in tests); ``None`` on error."""
    try:
        resp = httpx.get(
            f"{_BASE}{path}",
            params=params,
            timeout=_TIMEOUT,
            headers={"User-Agent": _UA, "Accept": "application/json", "x-api-key": api_key},
        )
        resp.raise_for_status()
        return resp.json()
    except (httpx.HTTPError, ValueError):
        return None
