"""Apply a resolution into the live instance (reversibly), or revert it.

Writes the override datapack into the chosen target — each existing world's
``saves/<world>/datapacks/`` (no dependency) or Open Loader's ``openloader/data/``
(global, needs the mod) — plus ``unify.json`` under ``config/almostunified/`` when
Almost Unified is installed (it handles tags itself, so the datapack then carries
only recipe overrides). Every written path is recorded in a manifest so
:func:`revert_resolution` can undo it.
"""

import json
from pathlib import Path

from app.analyzer.mods import read_mods_metadata, scan_mods_folder
from app.models import (
    ApplyResult,
    ApplyTarget,
    Instance,
    ResolutionTargets,
    RevertResult,
)
from app.profile import VersionProfile
from app.resolve.generate import (
    UNIFY_PATH,
    _unify_default_priorities,
    assemble_override_datapack,
    generate_unify_json,
)
from app.resolve.variants import recipe_winner_bodies
from app.sources.instance import detect_instance

_MANIFEST = ".emendator-overrides.json"
_OPENLOADER_DATA = ("openloader", "data")
_FALLBACK_DATAPACKS = "datapacks"
_AU_ID = "almostunified"
_OPENLOADER_ID = "openloader"


def _mod_ids(mods_dir: Path) -> set[str]:
    """Every mod id (and its ``provides``) in the folder — for AU/Open Loader checks."""
    mods, _errors = read_mods_metadata(mods_dir)
    ids: set[str] = set()
    for mod in mods:
        ids.add(mod.id)
        ids.update(mod.provides)
    return ids


def _mods_dir(instance: Instance, root: Path) -> Path:
    return Path(instance.folders.mods) if instance.folders.mods else root


def _base_dir(instance: Instance) -> Path:
    """The pack base (where ``config/``, ``datapacks/`` and ``saves/`` live)."""
    folders = instance.folders
    for candidate in (folders.config, folders.resourcepacks, folders.shaderpacks):
        if candidate:
            return Path(candidate).parent
    if folders.mods and instance.source != "raw_mods":
        return Path(folders.mods).parent
    return Path(instance.root)


def resolution_targets(root: Path, profile: VersionProfile) -> ResolutionTargets:
    """What the pack supports: AU present, Open Loader present, existing datapack dirs."""
    instance = detect_instance(root)
    ids = _mod_ids(_mods_dir(instance, root))
    return ResolutionTargets(
        almost_unified=_AU_ID in ids,
        open_loader=_OPENLOADER_ID in ids,
        worlds=instance.folders.datapacks,
    )


def _datapack_dirs(instance: Instance, base: Path, target: ApplyTarget) -> list[Path]:
    """Directories the override datapack is copied into for the chosen target."""
    if target == "openloader":
        return [base.joinpath(*_OPENLOADER_DATA)]
    existing = [Path(d) for d in instance.folders.datapacks]
    return existing or [base / _FALLBACK_DATAPACKS]


def _write(path: Path, content: str, written: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    written.append(str(path))


def apply_resolution(
    root: Path,
    profile: VersionProfile,
    *,
    recipe_winners: dict[str, str] | None,
    tag_winners: dict[str, str] | None,
    target: ApplyTarget,
) -> ApplyResult:
    """Write the resolution into ``root``'s instance and record a revert manifest."""
    instance = detect_instance(root)
    mods_dir = _mods_dir(instance, root)
    base = _base_dir(instance)

    scan = scan_mods_folder(mods_dir, profile.profile)
    recipe_collisions = [c for c in scan.conflicts if c.type == "recipe_collision"]
    tag_overlaps = [c for c in scan.conflicts if c.type == "tag_overlap"]

    ids = _mod_ids(mods_dir)
    au = _AU_ID in ids
    open_loader = _OPENLOADER_ID in ids
    bodies = recipe_winner_bodies(mods_dir, profile, recipe_winners)
    # AU present: it unifies tags via unify.json, so the datapack carries recipes only.
    datapack = assemble_override_datapack(
        profile,
        recipe_collisions,
        [] if au else tag_overlaps,
        recipe_bodies=bodies,
        tag_winners=tag_winners,
    )

    written: list[str] = []
    targets: list[str] = []
    try:
        if datapack:
            for dp_dir in _datapack_dirs(instance, base, target):
                for file in datapack:
                    _write(dp_dir / file.path, file.content, written)
                targets.append(str(dp_dir))
        if au and tag_overlaps:
            unify = generate_unify_json(
                tag_overlaps, _unify_default_priorities(tag_overlaps), tag_winners
            )
            if unify is not None:
                _write(base / unify.path, unify.content, written)
                targets.append(str((base / UNIFY_PATH).parent))
    except OSError as exc:
        return ApplyResult(status="error", written=written, message=f"Write failed: {exc}")

    if not written:
        return ApplyResult(
            status="nothing",
            almost_unified=au,
            open_loader=open_loader,
            message="No resolvable conflicts to apply.",
        )

    manifest: Path | None = base / _MANIFEST
    try:
        assert manifest is not None
        manifest.write_text(json.dumps(written, indent=2), encoding="utf-8")
    except OSError:
        manifest = None  # best-effort; the front still holds the written list

    return ApplyResult(
        status="applied",
        written=written,
        targets=targets,
        manifest=str(manifest) if manifest else None,
        almost_unified=au,
        open_loader=open_loader,
    )


def _prune_empty(directory: Path) -> None:
    """Remove now-empty dirs left by a revert, but only within the override subtree."""
    while "emendator-overrides" in directory.parts:
        try:
            if directory.is_dir() and not any(directory.iterdir()):
                directory.rmdir()
                directory = directory.parent
            else:
                return
        except OSError:
            return


def revert_resolution(manifest: Path) -> RevertResult:
    """Delete every file a prior apply wrote (per its manifest), then the manifest."""
    if not manifest.is_file():
        return RevertResult(status="not_found", message=f"Manifest not found: {manifest}")
    try:
        paths = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return RevertResult(status="error", message=f"Could not read manifest: {exc}")
    if not isinstance(paths, list):
        return RevertResult(status="error", message="Malformed manifest.")

    removed: list[str] = []
    for entry in paths:
        path = Path(str(entry))
        try:
            if path.is_file():
                path.unlink()
                removed.append(str(path))
                _prune_empty(path.parent)
        except OSError:
            continue
    manifest.unlink(missing_ok=True)
    return RevertResult(status="reverted", removed=removed)
