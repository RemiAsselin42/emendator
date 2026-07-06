"""Plan and apply the mixin fix ladder (Phase 2.5).

For every actionable ``mixin_overlap`` conflict the planner picks a loser and
the cheapest viable rung, most precise first:

1. **toggle** — the loser's own per-mixin kill switch covers the conflicting
   mixin classes (:mod:`app.resolve.mixin_toggles`);
2. **filter** — an installable filter mod blacklists them by class name
   (:mod:`app.resolve.mixin_filters`), installing the filter mod if absent;
3. **disable** — sideline the whole jar (the pre-existing floor).

``rollback`` and ``jar_patch`` stay manual alternatives: rolling back assumes
the previous release is conflict-free (a judgment call), and jar patching is
consent-gated.

Applying merges generated config files into any existing user file (prior
content is captured in the manifest, so revert restores rather than deletes),
sidelines jars via the ``.disabled`` rename, and records everything —
written files, disables, installed filter jars — in a v2 manifest that
:func:`revert_mixin_fixes` undoes.
"""

import json
from collections import defaultdict
from pathlib import Path

from app.analyzer.detectors import JarIndex, MixinToggleSystem, detect_mixin_overlaps
from app.analyzer.mods import build_jar_index
from app.enrich.install import disable_mod, install_mod
from app.models import (
    Conflict,
    GeneratedFile,
    Loader,
    MixinApplyResult,
    MixinFixAction,
    MixinFixPlan,
    MixinPlanResult,
    Mod,
)
from app.profile import VersionProfile
from app.resolve.apply import _base_dir
from app.resolve.mixin_filters import generate_filter_config, pick_filter_mod
from app.resolve.mixin_toggles import generate_mixin_toggles, togglable_classes
from app.runner.runner import detect_loader
from app.sources.instance import detect_instance, mods_jars

MIXIN_MANIFEST = ".emendator-mixins.json"


def plan_mixin_fixes(
    root: Path,
    profile: VersionProfile,
    losers: dict[str, str] | None = None,
) -> MixinPlanResult:
    """Build per-conflict fix plans for the instance at ``root``."""
    instance = detect_instance(root)
    jars = mods_jars(instance)
    indexes = _build_indexes(jars, profile)
    mods = [index.mod for index in indexes]
    loader: Loader = detect_loader(jars[0].parent) if jars else "fabric"
    conflicts = _mixin_conflicts(indexes)
    filter_mod = pick_filter_mod(loader, profile.profile)

    by_id = {index.mod.id: index for index in indexes}
    dependents = _count_dependents(mods)
    plans: list[MixinFixPlan] = []
    for conflict in conflicts:
        plans.append(_plan_one(conflict, by_id, dependents, loader, profile.profile, losers or {}))
    return MixinPlanResult(
        plans=plans, loader=loader, filter_mod=filter_mod.slug if filter_mod else None
    )


def _build_indexes(jars: list[Path], profile: VersionProfile) -> list[JarIndex]:
    indexes: list[JarIndex] = []
    for jar in jars:
        index, _error = build_jar_index(jar, profile)
        if index is not None:
            indexes.append(index)
    return indexes


def _mixin_conflicts(indexes: list[JarIndex]) -> list[Conflict]:
    """Actionable overlaps only: shared-method (warning) or provably hard (error)."""
    return [c for c in detect_mixin_overlaps(indexes) if c.severity in ("error", "warning")]


def _count_dependents(mods: list[Mod]) -> dict[str, int]:
    """How many other mods depend on each mod — the keep-the-library signal."""
    providers: dict[str, set[str]] = defaultdict(set)
    for mod in mods:
        for provided in (mod.id, *mod.provides):
            providers[provided].add(mod.id)
    counts: dict[str, int] = defaultdict(int)
    for mod in mods:
        hit: set[str] = set()
        for dep in mod.depends:
            hit |= providers.get(dep, set()) - {mod.id}
        for provider in hit:
            counts[provider] += 1
    return counts


def _loser_mixin_classes(conflict: Conflict, index: JarIndex, loser: str) -> set[str]:
    """The loser's mixin classes behind this conflict's shared methods."""
    target = str(conflict.detail.get("target") or "")
    classes: set[str] = set()
    for method in conflict.detail.get("sharedMethods") or []:
        patch = index.mixin_method_patches.get(f"{target}#{method}")
        if patch is not None:
            classes |= patch.mixin_classes
    return classes


def _feature_hints(classes: set[str], toggles: MixinToggleSystem | None) -> list[str]:
    """Readable names for what the mixins provide (semantic cost of the fix)."""
    hints: set[str] = set()
    for cls in classes:
        key = toggles.keys.get(cls) if toggles else None
        if key:
            hints.add(key.removeprefix("mixin.").replace(".", " "))
        else:
            package = cls.rsplit(".", 2)
            hints.add(" ".join(package[-2:-1]) or cls)
    return sorted(hints)


def _plan_one(
    conflict: Conflict,
    by_id: dict[str, JarIndex],
    dependents: dict[str, int],
    loader: Loader,
    version: str,
    losers: dict[str, str],
) -> MixinFixPlan:
    target = str(conflict.detail.get("target") or "")
    members = conflict.members
    filter_mod = pick_filter_mod(loader, version)

    # Loser candidates: explicit pick first, else fewest dependents (keep the
    # load-bearing library), preferring one whose fix has a precise rung.
    forced = losers.get(target)
    ordered = (
        [forced] if forced in members else sorted(members, key=lambda m: (dependents.get(m, 0), m))
    )

    best: MixinFixPlan | None = None
    for candidate in ordered:
        index = by_id.get(candidate)
        if index is None:
            continue
        classes = _loser_mixin_classes(conflict, index, candidate)
        hints = _feature_hints(classes, index.mixin_toggles)
        alternatives = _alternatives(index)

        if classes and index.mixin_toggles is not None:
            covered = togglable_classes(index.mixin_toggles, classes)
            if covered == classes:
                file = generate_mixin_toggles(index.mixin_toggles, classes)
                if file is not None:
                    return MixinFixPlan(
                        target=target,
                        members=members,
                        loser=candidate,
                        rung="toggle",
                        actions=[
                            MixinFixAction(
                                kind="toggle",
                                mod=candidate,
                                jar=index.mod.jar,
                                file=file,
                                mixin_classes=sorted(classes),
                                feature_hints=hints,
                            )
                        ],
                        alternatives=alternatives,
                    )
        if classes and filter_mod is not None and best is None:
            file = generate_filter_config(filter_mod, classes)
            if file is not None:
                actions = [
                    MixinFixAction(
                        kind="install_filter",
                        mod=candidate,
                        filter_slug=filter_mod.slug,
                        note=f"Requires the {filter_mod.name} mod (installed if absent).",
                    ),
                    MixinFixAction(
                        kind="filter_config",
                        mod=candidate,
                        jar=index.mod.jar,
                        file=file,
                        mixin_classes=sorted(classes),
                        feature_hints=hints,
                    ),
                ]
                best = MixinFixPlan(
                    target=target,
                    members=members,
                    loser=candidate,
                    rung="filter",
                    actions=actions,
                    alternatives=alternatives,
                )
        if best is None:
            best = MixinFixPlan(
                target=target,
                members=members,
                loser=candidate,
                rung="disable",
                actions=[
                    MixinFixAction(
                        kind="disable",
                        mod=candidate,
                        jar=index.mod.jar,
                        mixin_classes=sorted(classes),
                        feature_hints=hints,
                        note="No precise rung covers this mixin — sidelines the whole jar.",
                    )
                ],
                alternatives=alternatives,
                note="Consider rollback or a jar patch before disabling.",
            )
        if forced:
            break  # an explicit loser pick is not second-guessed

    return best or MixinFixPlan(
        target=target, members=members, loser=ordered[0] if ordered else "", rung="none"
    )


def _alternatives(index: JarIndex) -> list[str]:
    alternatives = ["jar_patch"]
    if index.mod.provider == "modrinth":
        alternatives.insert(0, "rollback")
    return alternatives


# --- apply / revert -----------------------------------------------------------


def _merge_properties(existing: str, ours: str) -> str:
    """Overlay our ``key=value`` lines on an existing properties file."""
    our_keys = {
        line.split("=", 1)[0].strip()
        for line in ours.splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }
    kept = [
        line
        for line in existing.splitlines()
        if not ("=" in line and line.split("=", 1)[0].strip() in our_keys)
    ]
    return "\n".join([*kept, ""]) + ours if kept else ours


def _merge_json(existing: str, ours: str) -> str:
    """Deep-merge our JSON config over an existing one (lists union, ours wins)."""
    try:
        base = json.loads(existing)
    except (json.JSONDecodeError, ValueError):
        return ours
    try:
        override = json.loads(ours)
    except (json.JSONDecodeError, ValueError):
        return ours
    if not isinstance(base, dict) or not isinstance(override, dict):
        return ours

    def merge(a: dict, b: dict) -> dict:
        out = dict(a)
        for key, value in b.items():
            if isinstance(value, dict) and isinstance(out.get(key), dict):
                out[key] = merge(out[key], value)
            elif isinstance(value, list) and isinstance(out.get(key), list):
                out[key] = out[key] + [v for v in value if v not in out[key]]
            else:
                out[key] = value
        return out

    return json.dumps(merge(base, override), indent=2) + "\n"


def _merged_content(path: Path, file: GeneratedFile) -> str:
    if not path.is_file():
        return file.content
    existing = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix == ".properties":
        return _merge_properties(existing, file.content)
    return _merge_json(existing, file.content)


def apply_mixin_fixes(
    root: Path,
    profile: VersionProfile,
    *,
    losers: dict[str, str] | None = None,
    targets: list[str] | None = None,
    allow_disable: bool = True,
) -> MixinApplyResult:
    """Execute the planned fixes and record a revert manifest."""
    instance = detect_instance(root)
    jars = mods_jars(instance)
    mods_dir = jars[0].parent if jars else root
    base = _base_dir(instance)
    result = plan_mixin_fixes(root, profile, losers)

    wanted = set(targets) if targets is not None else None
    selected = [p for p in result.plans if wanted is None or p.target in wanted]

    # Coalesce file artifacts across plans: one write per config path.
    files: dict[str, GeneratedFile] = {}
    disables: list[tuple[str, str]] = []  # (mod, jar)
    filter_slug: str | None = None
    for plan in selected:
        for action in plan.actions:
            if action.kind in ("toggle", "filter_config") and action.file is not None:
                merged = files.get(action.file.path)
                if merged is None:
                    files[action.file.path] = action.file
                else:
                    coalesced = (
                        _merge_properties(merged.content, action.file.content)
                        if action.file.path.endswith(".properties")
                        else _merge_json(merged.content, action.file.content)
                    )
                    files[action.file.path] = GeneratedFile(
                        path=action.file.path, content=coalesced
                    )
            elif action.kind == "install_filter":
                filter_slug = action.filter_slug
            elif action.kind == "disable" and allow_disable and action.jar:
                disables.append((action.mod, action.jar))

    written: list[dict] = []
    disabled: list[str] = []
    installed: list[str] = []
    try:
        for path_rel, file in sorted(files.items()):
            path = base / path_rel
            prior = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else None
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(_merged_content(path, file), encoding="utf-8")
            written.append({"path": str(path), "prior": prior})
    except OSError as exc:
        return MixinApplyResult(
            status="error",
            written=[w["path"] for w in written],
            message=f"Write failed: {exc}",
        )

    if filter_slug and files:
        outcome = install_mod(mods_dir, filter_slug, result.loader, profile.profile)
        freshly_added = (outcome.message or "") != "Already present."
        if outcome.status == "installed" and outcome.jar and freshly_added:
            installed.append(str(mods_dir / outcome.jar))

    for _mod, jar in disables:
        outcome = disable_mod(mods_dir, jar)
        if outcome.status == "disabled" and outcome.jar:
            disabled.append(jar)

    if not written and not disabled and not installed:
        return MixinApplyResult(status="nothing", message="No applicable mixin fixes.")

    manifest_path: Path | None = base / MIXIN_MANIFEST
    manifest = {
        "version": 2,
        "written": written,
        "disabled": disabled,
        "installed": installed,
        "modsDir": str(mods_dir),
    }
    try:
        assert manifest_path is not None
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    except OSError:
        manifest_path = None

    return MixinApplyResult(
        status="applied",
        written=[w["path"] for w in written],
        disabled=disabled,
        installed=installed,
        manifest=str(manifest_path) if manifest_path else None,
    )


def revert_mixin_fixes(manifest_path: Path) -> MixinApplyResult:
    """Undo a prior mixin apply: restore files, re-enable jars, drop installs."""
    if not manifest_path.is_file():
        return MixinApplyResult(status="error", message=f"Manifest not found: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return MixinApplyResult(status="error", message=f"Could not read manifest: {exc}")
    if not isinstance(manifest, dict):
        return MixinApplyResult(status="error", message="Malformed manifest.")

    restored: list[str] = []
    for entry in manifest.get("written") or []:
        if not isinstance(entry, dict):
            continue
        path = Path(str(entry.get("path")))
        prior = entry.get("prior")
        try:
            if prior is None:
                path.unlink(missing_ok=True)
            else:
                path.write_text(str(prior), encoding="utf-8")
            restored.append(str(path))
        except OSError:
            continue

    mods_dir = Path(str(manifest.get("modsDir") or manifest_path.parent))
    enabled: list[str] = []
    for jar in manifest.get("disabled") or []:
        disabled_file = mods_dir / f"{jar}.disabled"
        try:
            if disabled_file.is_file():
                disabled_file.replace(mods_dir / str(jar))
                enabled.append(str(jar))
        except OSError:
            continue

    removed: list[str] = []
    for installed in manifest.get("installed") or []:
        try:
            Path(str(installed)).unlink(missing_ok=True)
            removed.append(str(installed))
        except OSError:
            continue

    manifest_path.unlink(missing_ok=True)
    return MixinApplyResult(
        status="applied",
        written=restored,
        disabled=enabled,
        installed=removed,
        message="Reverted.",
    )
