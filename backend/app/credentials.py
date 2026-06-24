"""Persisted runtime credentials — currently just the CurseForge API key.

The key can arrive two ways, **env wins**: ``EMENDATOR_CURSEFORGE_API_KEY`` (env or
.env), or a small JSON file under the emendator data dir written from the UI.
:func:`load_into_settings` folds the file into the live :data:`settings` at startup;
:func:`set_curseforge_key` rewrites the file *and* updates settings in place, so an
install picks up a freshly entered key without a restart.

Stored in plaintext under the user's home (a local desktop tool, like most CLIs).
Best-effort I/O: a missing/unreadable file just means "no stored key".
"""

import json
from pathlib import Path
from typing import Any

from app.config import settings

_CURSEFORGE_KEY = "curseforgeApiKey"


def _store_path() -> Path:
    return Path.home() / ".emendator" / "credentials.json"


def load_into_settings() -> None:
    """Fold a stored CurseForge key into live settings, unless env already set one."""
    if settings.curseforge_api_key:
        return
    stored = _read().get(_CURSEFORGE_KEY)
    if isinstance(stored, str) and stored:
        settings.curseforge_api_key = stored


def set_curseforge_key(key: str | None) -> None:
    """Persist (or, when blank, clear) the CurseForge key and update live settings."""
    cleaned = key.strip() if isinstance(key, str) else ""
    settings.curseforge_api_key = cleaned or None
    data = _read()
    if cleaned:
        data[_CURSEFORGE_KEY] = cleaned
    else:
        data.pop(_CURSEFORGE_KEY, None)
    _write(data)


def _read() -> dict[str, Any]:
    try:
        raw = json.loads(_store_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _write(data: dict[str, Any]) -> None:
    path = _store_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass
