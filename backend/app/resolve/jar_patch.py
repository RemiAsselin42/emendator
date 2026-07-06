"""Patch a jar's mixin config in place — the fix ladder's last resort.

Loaders perform no signature/integrity checks on mod jars (2026-07-06 spike),
so removing a mixin entry from a ``*.mixins.json``, flipping its ``required``
flag, or adjusting the config ``priority`` and re-zipping is technically clean
and perfectly precise. It is still the *last* rung because it edits a file the
user doesn't own: licensing forbids redistributing the modified jar, pack
manifests referencing the original file by hash stop matching, and upstream
support is void. Callers must gate it behind explicit consent and surface
those caveats.

The original jar is preserved as ``<jar>.bak`` next to the patched one —
revert = swap back (the apply manifest records it, Phase 2.5).
"""

import json
import shutil
import zipfile
from pathlib import Path

from app.models import JarPatchResult

_MIXIN_SECTIONS = ("mixins", "client", "server")


def patch_jar_mixin_config(
    mods_dir: Path,
    jar: str,
    *,
    remove_mixins: dict[str, list[str]] | None = None,
    set_required: dict[str, bool] | None = None,
    set_priority: dict[str, int] | None = None,
) -> JarPatchResult:
    """Rewrite ``jar`` with the requested mixin-config edits, keeping a ``.bak``.

    ``remove_mixins`` maps a config entry name (e.g. ``sodium.mixins.json``) to
    the mixin class entries (as listed in the config, package-relative) to
    drop; ``set_required`` / ``set_priority`` override those config fields.
    Unknown configs/entries are ignored; if nothing effectively changes, the
    jar is left untouched (``status="nothing"``).
    """
    source = mods_dir / jar
    if not source.is_file():
        return JarPatchResult(status="error", jar=jar, message=f"Jar not found: {jar}")

    edits = _ConfigEdits(remove_mixins or {}, set_required or {}, set_priority or {})
    tmp = source.with_suffix(source.suffix + ".patch-tmp")
    removed: dict[str, list[str]] = {}
    try:
        with zipfile.ZipFile(source) as src, zipfile.ZipFile(tmp, "w") as dst:
            for info in src.infolist():
                data = src.read(info.filename)
                if edits.applies_to(info.filename):
                    patched, dropped = edits.apply(info.filename, data)
                    if patched is not None:
                        data = patched
                        if dropped:
                            removed[info.filename] = dropped
                dst.writestr(info, data)
    except (OSError, zipfile.BadZipFile) as exc:
        tmp.unlink(missing_ok=True)
        return JarPatchResult(status="error", jar=jar, message=f"Could not patch: {exc}")

    if not edits.changed:
        tmp.unlink(missing_ok=True)
        return JarPatchResult(status="nothing", jar=jar, message="No matching entries to edit.")

    backup = source.with_suffix(source.suffix + ".bak")
    try:
        shutil.copy2(source, backup)
        tmp.replace(source)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        return JarPatchResult(status="error", jar=jar, message=f"Could not swap in patch: {exc}")

    return JarPatchResult(
        status="patched",
        jar=jar,
        backup=backup.name,
        removed=removed,
        message="Original kept as .bak — pack-manifest hashes for this file no longer match.",
    )


class _ConfigEdits:
    """The requested edits, applied config-by-config while re-zipping."""

    def __init__(
        self,
        remove_mixins: dict[str, list[str]],
        set_required: dict[str, bool],
        set_priority: dict[str, int],
    ) -> None:
        self.remove_mixins = remove_mixins
        self.set_required = set_required
        self.set_priority = set_priority
        self.changed = False

    def applies_to(self, name: str) -> bool:
        return name in self.remove_mixins or name in self.set_required or name in self.set_priority

    def apply(self, name: str, data: bytes) -> tuple[bytes | None, list[str]]:
        """The patched config bytes (None = leave as-is) + entries dropped."""
        try:
            config = json.loads(data, strict=False)
        except (json.JSONDecodeError, ValueError):
            return None, []
        if not isinstance(config, dict):
            return None, []

        touched = False
        dropped: list[str] = []
        to_remove = set(self.remove_mixins.get(name, ()))
        if to_remove:
            for section in _MIXIN_SECTIONS:
                entries = config.get(section)
                if not isinstance(entries, list):
                    continue
                kept = [e for e in entries if e not in to_remove]
                if len(kept) != len(entries):
                    dropped.extend(e for e in entries if e in to_remove)
                    config[section] = kept
                    touched = True
        if name in self.set_required and config.get("required") is not self.set_required[name]:
            config["required"] = self.set_required[name]
            touched = True
        if name in self.set_priority and config.get("priority") != self.set_priority[name]:
            config["priority"] = self.set_priority[name]
            touched = True

        if not touched:
            return None, []
        self.changed = True
        return json.dumps(config, indent=2).encode("utf-8"), dropped


def unpatch_jar(mods_dir: Path, jar: str) -> JarPatchResult:
    """Restore a patched jar from its ``.bak`` (the revert path)."""
    source = mods_dir / jar
    backup = source.with_suffix(source.suffix + ".bak")
    if not backup.is_file():
        return JarPatchResult(status="error", jar=jar, message="No .bak backup to restore.")
    try:
        backup.replace(source)
    except OSError as exc:
        return JarPatchResult(status="error", jar=jar, message=f"Could not restore: {exc}")
    return JarPatchResult(status="patched", jar=jar, message="Restored the original jar.")
