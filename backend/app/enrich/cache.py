"""A tiny on-disk JSON cache with TTL for online-enrichment responses.

Keeps the network off the hot path on repeat scans and degrades to a no-op when
the cache dir can't be used. Keys are caller-supplied (e.g. a content hash); the
stored value is any JSON-serializable object. Best-effort throughout: any I/O
error simply behaves as a cache miss / skipped write.
"""

import json
import time
from pathlib import Path
from typing import Any

from app.config import settings

# 24h: project metadata / latest-version info changes slowly.
_TTL_SECONDS = 24 * 3600


def _cache_dir() -> Path:
    base = settings.cache_dir or (Path.home() / ".emendator" / "cache")
    return Path(base)


def _path_for(namespace: str, key: str) -> Path:
    # Keep keys filesystem-safe (hashes/ids are already safe, but be defensive).
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in key)[:120]
    return _cache_dir() / namespace / f"{safe}.json"


def get(namespace: str, key: str) -> Any | None:
    """Return the cached value for ``(namespace, key)`` if present and fresh."""
    path = _path_for(namespace, key)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict) or "ts" not in raw:
        return None
    if time.time() - raw["ts"] > _TTL_SECONDS:
        return None
    return raw.get("value")


def put(namespace: str, key: str, value: Any) -> None:
    """Store ``value`` under ``(namespace, key)``; silently skip on any error."""
    path = _path_for(namespace, key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"ts": time.time(), "value": value}), encoding="utf-8")
    except OSError:
        pass
