"""Modrinth enrichment: identify jars by hash and check for updates.

Two batched, auth-free calls cover the whole set:

- ``POST /v2/version_files`` maps each jar's **sha1** to the Modrinth version it
  is (project id + version number).
- ``POST /v2/version_files/update`` returns, per hash, the latest version for the
  pack's loader + Minecraft version — so we can flag ``update_available``.

Mutates the passed :class:`Mod` list in place. Entirely best-effort: the HTTP
seam (:func:`_api_post`) returns ``None`` on any error, leaving mods untouched.
"""

import hashlib
import json
from pathlib import Path
from typing import Any

import httpx

from app.enrich import cache
from app.models import Loader, Mod

_BASE = "https://api.modrinth.com"
_UA = "emendator/0.1 (modpack analyzer)"
_TIMEOUT = httpx.Timeout(8.0, connect=4.0)

# Modrinth loader names we query updates for, per our internal loader.
_LOADER_NAMES: dict[Loader, str] = {
    "fabric": "fabric",
    "quilt": "quilt",
    "forge": "forge",
    "neoforge": "neoforge",
}

# Loader/platform pseudo-dependencies that aren't installable mods — the server
# flags them as "missing" the same way, but there's nothing to fetch.
_NOT_INSTALLABLE = frozenset(
    {"minecraft", "java", "fabricloader", "fabric-loader", "quilt_loader", "forge", "neoforge"}
)

# Mod ids whose Modrinth slug differs from the id declared in loader metadata.
_INSTALL_ALIASES: dict[str, str] = {
    "fabric": "fabric-api",  # Fabric API's mod id is "fabric"; its slug is "fabric-api"
    "openloader": "open-loader",  # Open Loader's mod id is "openloader"; its slug is "open-loader"
}


def enrich(jars: list[Path], mods: list[Mod], game_version: str, loader: Loader) -> None:
    """Attach Modrinth project links + update status to ``mods`` (in place)."""
    by_jar_sha1 = {jar.name: _sha1(jar) for jar in jars}
    sha1s = sorted({h for h in by_jar_sha1.values() if h})
    if not sha1s:
        return

    found = _lookup(sha1s)
    if not found:
        return
    loaders = [_LOADER_NAMES[loader]] if loader in _LOADER_NAMES else []
    latest = _updates(sha1s, loaders, game_version) if loaders else {}

    for mod in mods:
        sha1 = by_jar_sha1.get(mod.jar)
        version = found.get(sha1) if sha1 else None
        if not isinstance(version, dict):
            continue
        project_id = version.get("project_id")
        if isinstance(project_id, str):
            mod.provider = "modrinth"
            mod.homepage = f"https://modrinth.com/project/{project_id}"
        current = version.get("version_number")
        newest = latest.get(sha1) if sha1 else None
        if isinstance(newest, dict):
            newest_number = newest.get("version_number")
            if isinstance(newest_number, str):
                mod.latest_version = newest_number
                if isinstance(current, str):
                    mod.update_available = newest_number != current


def find_update(jar_path: Path, loader: Loader, game_version: str) -> dict[str, Any] | None:
    """The latest Modrinth version's primary file for ``jar_path`` (for updating).

    Returns ``{url, filename, sha1, version_number, current_sha1}`` or ``None``
    when the loader isn't supported, the jar isn't on Modrinth, or the response
    is malformed. Not cached — an explicit update wants the freshest answer.
    """
    if loader not in _LOADER_NAMES:
        return None
    sha1 = _sha1(jar_path)
    if not sha1:
        return None
    payload = {
        "hashes": [sha1],
        "algorithm": "sha1",
        "loaders": [_LOADER_NAMES[loader]],
        "game_versions": [game_version],
    }
    data = _api_post("/v2/version_files/update", payload)
    version = data.get(sha1) if isinstance(data, dict) else None
    if not isinstance(version, dict):
        return None
    files = version.get("files")
    if not isinstance(files, list) or not files:
        return None
    primary = next((f for f in files if isinstance(f, dict) and f.get("primary")), None)
    if primary is None:
        primary = next((f for f in files if isinstance(f, dict)), None)
    if not isinstance(primary, dict):
        return None
    url, filename = primary.get("url"), primary.get("filename")
    if not isinstance(url, str) or not isinstance(filename, str):
        return None
    hashes = primary.get("hashes")
    return {
        "url": url,
        "filename": filename,
        "sha1": hashes.get("sha1") if isinstance(hashes, dict) else None,
        "version_number": version.get("version_number"),
        "current_sha1": sha1,
    }


def find_install(mod_id: str, loader: Loader, game_version: str) -> dict[str, Any] | None:
    """The latest Modrinth version's primary file for a missing dependency ``mod_id``.

    Resolves the loader-declared dependency id to a Modrinth project (the id is
    tried as a slug first, then a search falls back to a fuzzy match), filters its
    versions to the pack's loader + Minecraft version, and returns the newest one's
    primary file as ``{url, filename, sha1, version_number, project_title}``.
    Returns ``None`` when the loader isn't supported, the id is a platform
    pseudo-dependency (Minecraft/Java/the loader itself), or nothing matches.
    """
    if loader not in _LOADER_NAMES or mod_id in _NOT_INSTALLABLE:
        return None
    slug = _INSTALL_ALIASES.get(mod_id, mod_id)
    title = slug
    versions = _project_versions(slug, loader, game_version)
    if not versions:
        hit = _search_project(mod_id, loader, game_version)
        if hit is None:
            return None
        slug, title = hit
        versions = _project_versions(slug, loader, game_version)
    if not versions:
        return None
    return _primary_file(versions[0], title)


def _project_versions(
    slug_or_id: str, loader: Loader, game_version: str
) -> list[dict[str, Any]] | None:
    """The project's versions for the pack's loader + MC version, newest first."""
    params = {
        "loaders": json.dumps([_LOADER_NAMES[loader]]),
        "game_versions": json.dumps([game_version]),
    }
    data = _api_get(f"/v2/project/{slug_or_id}/version", params)
    if not isinstance(data, list):
        return None
    return [v for v in data if isinstance(v, dict)]


def _search_project(query: str, loader: Loader, game_version: str) -> tuple[str, str] | None:
    """Top Modrinth mod matching ``query`` for the loader + MC version: (slug, title)."""
    facets = [
        [f"categories:{_LOADER_NAMES[loader]}"],
        [f"versions:{game_version}"],
        ["project_type:mod"],
    ]
    data = _api_get("/v2/search", {"query": query, "limit": "5", "facets": json.dumps(facets)})
    hits = data.get("hits") if isinstance(data, dict) else None
    if not isinstance(hits, list) or not hits or not isinstance(hits[0], dict):
        return None
    first = hits[0]
    slug = first.get("slug") or first.get("project_id")
    if not isinstance(slug, str):
        return None
    title = first.get("title")
    return slug, title if isinstance(title, str) else slug


def _primary_file(version: dict[str, Any], title: str) -> dict[str, Any] | None:
    """The primary file of a Modrinth version object (or first file as fallback)."""
    files = version.get("files")
    if not isinstance(files, list) or not files:
        return None
    primary = next((f for f in files if isinstance(f, dict) and f.get("primary")), None)
    if primary is None:
        primary = next((f for f in files if isinstance(f, dict)), None)
    if not isinstance(primary, dict):
        return None
    url, filename = primary.get("url"), primary.get("filename")
    if not isinstance(url, str) or not isinstance(filename, str):
        return None
    hashes = primary.get("hashes")
    return {
        "url": url,
        "filename": filename,
        "sha1": hashes.get("sha1") if isinstance(hashes, dict) else None,
        "version_number": version.get("version_number"),
        "project_title": title,
    }


def _lookup(sha1s: list[str]) -> dict[str, Any]:
    """sha1 -> the Modrinth version object the jar is (cached per hash set)."""
    return _cached_post(
        "lookup", sha1s, "/v2/version_files", {"hashes": sha1s, "algorithm": "sha1"}
    )


def _updates(sha1s: list[str], loaders: list[str], game_version: str) -> dict[str, Any]:
    """sha1 -> the latest Modrinth version for the pack's loader + MC version."""
    payload = {
        "hashes": sha1s,
        "algorithm": "sha1",
        "loaders": loaders,
        "game_versions": [game_version],
    }
    kind = f"update:{game_version}:{','.join(loaders)}"
    return _cached_post(kind, sha1s, "/v2/version_files/update", payload)


def _cached_post(kind: str, sha1s: list[str], path: str, payload: dict[str, Any]) -> dict[str, Any]:
    key = hashlib.sha1((kind + "|" + "|".join(sha1s)).encode()).hexdigest()
    cached = cache.get("modrinth", key)
    if isinstance(cached, dict):
        return cached
    result = _api_post(path, payload)
    if isinstance(result, dict):
        cache.put("modrinth", key, result)
        return result
    return {}


def _api_post(path: str, payload: dict[str, Any]) -> Any | None:
    """The single HTTP seam (monkeypatched in tests); ``None`` on any failure."""
    try:
        resp = httpx.post(
            f"{_BASE}{path}", json=payload, timeout=_TIMEOUT, headers={"User-Agent": _UA}
        )
        resp.raise_for_status()
        return resp.json()
    except (httpx.HTTPError, ValueError):
        return None


def _api_get(path: str, params: dict[str, str] | None = None) -> Any | None:
    """GET seam for project/search lookups (monkeypatched in tests); ``None`` on error."""
    try:
        resp = httpx.get(
            f"{_BASE}{path}", params=params, timeout=_TIMEOUT, headers={"User-Agent": _UA}
        )
        resp.raise_for_status()
        return resp.json()
    except (httpx.HTTPError, ValueError):
        return None


def _sha1(jar: Path) -> str | None:
    try:
        return hashlib.sha1(jar.read_bytes()).hexdigest()
    except OSError:
        return None
