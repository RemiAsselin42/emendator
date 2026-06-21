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


def _sha1(jar: Path) -> str | None:
    try:
        return hashlib.sha1(jar.read_bytes()).hexdigest()
    except OSError:
        return None
