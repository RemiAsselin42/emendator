"""Download and install mods: update one in place, or add a missing dependency.

:func:`update_mod` resolves the latest Modrinth version for an existing jar and
atomically swaps it in (removing the previous file). :func:`install_mod` resolves
a dependency the runner flagged as *missing* — by its loader-declared mod id —
and adds it to the folder. Both verify the sha1 and write to a temp ``.part``
first, so network/IO failures leave the mods folder untouched.
"""

import hashlib
import os
import tempfile
from pathlib import Path

import httpx

from app.enrich import modrinth
from app.models import InstallResult, Loader, UpdateResult

_UA = "emendator/0.1 (modpack analyzer)"
_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
_MAX_BYTES = 300 * 1024 * 1024  # guard against a runaway download


def update_mod(mods_dir: Path, jar: str, loader: Loader, game_version: str) -> UpdateResult:
    """Update ``jar`` in ``mods_dir`` to the latest Modrinth version, in place."""
    old = mods_dir / jar
    if not old.is_file():
        return UpdateResult(status="error", old_jar=jar, message=f"Jar not found: {jar}")

    info = modrinth.find_update(old, loader, game_version)
    if info is None:
        return UpdateResult(
            status="not_found", old_jar=jar, message="No Modrinth match for this jar."
        )
    if info.get("sha1") and info["sha1"] == info.get("current_sha1"):
        return UpdateResult(
            status="no_update", old_jar=jar, new_jar=jar, message="Already the latest version."
        )

    tmp = _download(info["url"], mods_dir)
    if tmp is None:
        return UpdateResult(status="error", old_jar=jar, message="Download failed.")

    expected = info.get("sha1")
    if expected and _sha1_file(tmp) != expected:
        tmp.unlink(missing_ok=True)
        return UpdateResult(status="error", old_jar=jar, message="Checksum mismatch — aborted.")

    new_name = info["filename"]
    try:
        tmp.replace(mods_dir / new_name)
        if new_name != jar:
            old.unlink(missing_ok=True)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        return UpdateResult(status="error", old_jar=jar, message=f"Could not install: {exc}")

    return UpdateResult(
        status="updated", old_jar=jar, new_jar=new_name, version=info.get("version_number")
    )


def install_mod(mods_dir: Path, mod_id: str, loader: Loader, game_version: str) -> InstallResult:
    """Add the missing dependency ``mod_id`` to ``mods_dir`` from Modrinth.

    Resolves the latest matching version for the pack's loader + MC version,
    verifies its sha1 and writes it in. Returns ``not_found`` when nothing on
    Modrinth matches (or the id is a platform pseudo-dependency), and is a no-op
    on the folder for any failure.
    """
    info = modrinth.find_install(mod_id, loader, game_version)
    if info is None:
        return InstallResult(
            status="not_found", mod_id=mod_id, message="No Modrinth match for this dependency."
        )

    filename = info["filename"]
    dest = mods_dir / filename
    if dest.exists():
        return InstallResult(
            status="installed",
            mod_id=mod_id,
            jar=filename,
            version=info.get("version_number"),
            message="Already present.",
        )

    tmp = _download(info["url"], mods_dir)
    if tmp is None:
        return InstallResult(status="error", mod_id=mod_id, message="Download failed.")

    expected = info.get("sha1")
    if expected and _sha1_file(tmp) != expected:
        tmp.unlink(missing_ok=True)
        return InstallResult(status="error", mod_id=mod_id, message="Checksum mismatch — aborted.")

    try:
        tmp.replace(dest)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        return InstallResult(status="error", mod_id=mod_id, message=f"Could not install: {exc}")

    return InstallResult(
        status="installed", mod_id=mod_id, jar=filename, version=info.get("version_number")
    )


def _download(url: str, dest_dir: Path) -> Path | None:
    """Stream ``url`` to a temp ``.part`` file in ``dest_dir`` (atomic-rename ready)."""
    fd, tmp_name = tempfile.mkstemp(dir=dest_dir, suffix=".part")
    tmp = Path(tmp_name)
    try:
        with httpx.stream(
            "GET", url, timeout=_TIMEOUT, follow_redirects=True, headers={"User-Agent": _UA}
        ) as resp:
            resp.raise_for_status()
            total = 0
            with os.fdopen(fd, "wb") as out:
                for chunk in resp.iter_bytes():
                    total += len(chunk)
                    if total > _MAX_BYTES:
                        raise ValueError("download exceeds size limit")
                    out.write(chunk)
        return tmp
    except (httpx.HTTPError, OSError, ValueError):
        tmp.unlink(missing_ok=True)
        return None


def _sha1_file(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()
