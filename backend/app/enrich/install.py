"""Mutate a mods folder: update a jar, add a missing dependency, or sideline one.

:func:`update_mod` resolves the latest Modrinth version for an existing jar and
atomically swaps it in (removing the previous file). :func:`install_mod` resolves
a dependency the runner flagged as *missing* — by its loader-declared mod id —
and adds it to the folder. Both verify the sha1 and write to a temp ``.part``
first, so network/IO failures leave the mods folder untouched.

:func:`disable_mod` / :func:`enable_mod` toggle a jar's ``.disabled`` suffix in
place (``foo.jar`` <-> ``foo.jar.disabled``) — the no-download, fully reversible
way to resolve an incompatible mixin pair when no compatible update exists (never a
delete, and no second copy). :func:`install_mod` notices a dependency that is only
disabled and re-enables it instead of downloading.
"""

import hashlib
import os
import tempfile
import zipfile
from pathlib import Path

import httpx

from app.config import settings
from app.enrich import curseforge, modrinth
from app.models import DisableResult, InstallResult, Loader, ProviderLink, UpdateResult

_PROVIDER_LABEL = {"modrinth": "Modrinth", "curseforge": "CurseForge"}

_UA = "emendator/0.1 (modpack analyzer)"
_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
_MAX_BYTES = 300 * 1024 * 1024  # guard against a runaway download
# A disabled jar keeps its place and gains a ``.disabled`` suffix (``foo.jar`` ->
# ``foo.jar.disabled``). The scanner/runner glob ``*.jar`` non-recursively, so the
# renamed file drops out of scans and boots while staying one rename away from
# restoration — and is never duplicated into a sidecar folder.
_DISABLED_SUFFIX = ".disabled"


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
    """Add the missing dependency ``mod_id`` to ``mods_dir`` from Modrinth (else CurseForge).

    Resolves the latest matching version for the pack's loader + MC version,
    verifies its sha1 and writes it in. Modrinth is tried first; when it has no
    match and a CurseForge API key is configured, CurseForge is tried as a
    fallback. Returns ``not_found`` when neither provider matches (or the id is a
    platform pseudo-dependency), and is a no-op on the folder for any failure.
    """
    # A dependency that's only disabled (renamed ``.jar.disabled``) is restored by
    # dropping the suffix — no download, the exact jar/version the pack already had.
    disabled = _find_disabled_jar(mods_dir, mod_id)
    if disabled is not None:
        active = disabled.with_suffix("")  # strip ".disabled" -> "<name>.jar"
        try:
            disabled.replace(active)
        except OSError as exc:
            return InstallResult(
                status="error", mod_id=mod_id, message=f"Could not re-enable: {exc}"
            )
        return InstallResult(
            status="installed",
            mod_id=mod_id,
            jar=active.name,
            message="Re-enabled a disabled mod (no download).",
        )

    from_curseforge = False
    info = modrinth.find_install(mod_id, loader, game_version)
    if info is None and settings.curseforge_api_key:
        info = curseforge.find_install(mod_id, loader, game_version, settings.curseforge_api_key)
        from_curseforge = info is not None
    if info is None:
        return _resolve_not_found(mod_id, loader, game_version)

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
        status="installed",
        mod_id=mod_id,
        jar=filename,
        version=info.get("version_number"),
        message="Installed from CurseForge." if from_curseforge else None,
    )


def _resolve_not_found(mod_id: str, loader: Loader, game_version: str) -> InstallResult:
    """A precise not_found: probe each provider (ignoring the version filter).

    Distinguishes "the project exists but has no build for the pack's loader + MC
    version" — carrying a direct link to it — from "found nowhere", where the front
    falls back to a manual search. Only runs on the failure path, so the extra
    lookups are cheap.
    """
    links: list[ProviderLink] = []
    hit = modrinth.probe_project(mod_id, loader)
    if hit is not None:
        links.append(ProviderLink(provider="modrinth", title=hit["title"], url=hit.get("url")))
    key = settings.curseforge_api_key
    if key:
        hit = curseforge.probe_project(mod_id, loader, key)
        if hit is not None:
            links.append(
                ProviderLink(provider="curseforge", title=hit["title"], url=hit.get("url"))
            )

    if links:
        where = " and ".join(_PROVIDER_LABEL[link.provider] for link in links)
        message = f"{links[0].title} is on {where}, but has no build for {loader} {game_version}."
        return InstallResult(status="not_found", mod_id=mod_id, message=message, links=links)

    searched = "Modrinth or CurseForge" if key else "Modrinth"
    return InstallResult(
        status="not_found",
        mod_id=mod_id,
        message=f"Not found on {searched} — check the spelling, or that it's still published.",
    )


def disable_mod(mods_dir: Path, jar: str) -> DisableResult:
    """Disable ``jar`` in place by appending ``.disabled`` (reversible; no download)."""
    src = mods_dir / jar
    if not src.is_file():
        return DisableResult(status="not_found", jar=jar, message=f"Jar not found: {jar}")
    try:
        src.replace(mods_dir / (jar + _DISABLED_SUFFIX))
    except OSError as exc:
        return DisableResult(status="error", jar=jar, message=f"Could not disable: {exc}")
    return DisableResult(status="disabled", jar=jar)


def enable_mod(mods_dir: Path, jar: str) -> DisableResult:
    """Re-enable ``jar`` by stripping its ``.disabled`` suffix, back into the set."""
    src = mods_dir / (jar + _DISABLED_SUFFIX)
    if not src.is_file():
        return DisableResult(status="not_found", jar=jar, message=f"Disabled jar not found: {jar}")
    try:
        src.replace(mods_dir / jar)
    except OSError as exc:
        return DisableResult(status="error", jar=jar, message=f"Could not enable: {exc}")
    return DisableResult(status="enabled", jar=jar)


def _find_disabled_jar(mods_dir: Path, mod_id: str) -> Path | None:
    """A ``*.jar.disabled`` file whose declared mod id (or ``provides``) is ``mod_id``.

    Lets :func:`install_mod` re-enable a merely-disabled dependency instead of
    re-downloading it. The metadata parser is imported lazily to keep the enrich
    layer free of an analyzer import at module load.
    """
    from app.analyzer.metadata import parse_mod_metadata

    for path in sorted(mods_dir.glob(f"*.jar{_DISABLED_SUFFIX}")):
        try:
            with zipfile.ZipFile(path) as zf:
                mod, _ = parse_mod_metadata(zf, zf.namelist(), path.name)
        except (zipfile.BadZipFile, OSError):
            continue
        if mod is not None and (mod.id == mod_id or mod_id in mod.provides):
            return path
    return None


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
