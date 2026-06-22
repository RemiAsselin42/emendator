from collections.abc import Sequence
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.analyzer.mods import read_jars_metadata, read_mods_metadata, scan_jars, scan_mods_folder
from app.analyzer.packs import scan_datapacks, scan_resourcepacks, scan_shaderpacks
from app.analyzer.registry_index import build_registry_index
from app.config import settings
from app.enrich import enrich_mods
from app.enrich.install import disable_mod, enable_mod, install_mod, update_mod
from app.models import (
    ApplyRequest,
    ApplyResult,
    BisectResult,
    DisableRequest,
    DisableResult,
    ExportRequest,
    ExportResult,
    InstallRequest,
    InstallResult,
    Instance,
    InstanceReport,
    ResolutionPlan,
    ResolutionTargets,
    ResolutionVariants,
    ResolveRequest,
    RevertRequest,
    RevertResult,
    RunRequest,
    RunVerdict,
    ScanRequest,
    ScanResult,
    UpdateRequest,
    UpdateResult,
    VariantsRequest,
    VersionCandidate,
    VersionDetection,
)
from app.profile import (
    VersionProfile,
    available_profiles,
    detect_version,
    resolve_profile,
)
from app.resolve.apply import apply_resolution, resolution_targets, revert_resolution
from app.resolve.generate import build_resolution_plan, export_plan
from app.resolve.variants import collect_recipe_variants, recipe_winner_bodies
from app.runner.bisect import bisect_set
from app.runner.runner import detect_loader, run_set
from app.sources.discovery import discover_instances
from app.sources.instance import detect_instance, mods_jars

app = FastAPI(title="Emendator backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _require_dir(path: str) -> Path:
    """Resolve a request path to an existing directory or raise HTTP 400."""
    folder = Path(path)
    if not folder.exists():
        raise HTTPException(status_code=400, detail=f"Path does not exist: {path}")
    if not folder.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a directory: {path}")
    return folder


def _detect_in_jars(jars: list[Path], forced: str | None = None) -> VersionDetection:
    """Run version detection from an explicit jar list's metadata (cheap pass)."""
    mods, _errors = read_jars_metadata(jars)
    constraints = [(mod.id, mod.depends.get("minecraft")) for mod in mods]
    return detect_version(constraints, forced=forced)


def _detect_in_folder(folder: Path, forced: str | None = None) -> VersionDetection:
    """Run version detection from a folder's mod metadata (cheap first pass)."""
    mods, _errors = read_mods_metadata(folder)
    constraints = [(mod.id, mod.depends.get("minecraft")) for mod in mods]
    return detect_version(constraints, forced=forced)


def _resolve_for_jars(
    jars: list[Path], version: str | None
) -> tuple[VersionProfile, VersionDetection]:
    """Pick the profile for a jar list: explicit ``version`` wins, else auto-detect.

    Raises HTTP 409 (carrying the :class:`VersionDetection`) when no version is
    given and the set is ambiguous — the front then asks the user to choose. The
    returned detection reflects the version actually used (the override, if any).
    """
    detection = _detect_in_jars(jars, forced=version)
    if detection.detected_version is None or (version is None and detection.status == "ambiguous"):
        raise HTTPException(status_code=409, detail=detection.model_dump(by_alias=True))
    return resolve_profile(detection.detected_version), detection


def _resolve_for(folder: Path, version: str | None) -> tuple[VersionProfile, VersionDetection]:
    """:func:`_resolve_for_jars` over every top-level ``.jar`` in ``folder``."""
    return _resolve_for_jars(sorted(folder.glob("*.jar")), version)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe consumed by the front to confirm the sidecar is up."""
    return {"status": "ok", "profile": settings.default_version}


@app.get("/profiles", response_model=list[VersionCandidate])
def profiles() -> list[VersionCandidate]:
    """Version blocks offered in the manual-override picker (PROJECT.md §6)."""
    return available_profiles()


@app.post("/mods/detect", response_model=VersionDetection)
def mods_detect(req: ScanRequest) -> VersionDetection:
    """Detect the Minecraft version of a ``mods/`` folder without a full scan."""
    return _detect_in_folder(_require_dir(req.path))


@app.post("/mods/scan", response_model=ScanResult)
def scan_mods(req: ScanRequest) -> ScanResult:
    """Ingest a local ``mods/`` folder into the conflict map (Phase 0 slice).

    With no ``version`` the backend auto-detects and refuses to guess on an
    ambiguous set (HTTP 409 + the detection payload, so the front can prompt).
    """
    folder = _require_dir(req.path)
    profile, detection = _resolve_for(folder, req.version)
    result = scan_mods_folder(folder, profile.profile)
    result.detection = detection
    return result


@app.get("/instances/discover", response_model=list[Instance])
def instances_discover() -> list[Instance]:
    """List modpack instances installed by known launchers (for quick-select).

    Scans CurseForge / Modrinth / Prism / MultiMC / vanilla locations and returns
    the ones with mods; best-effort, so it's empty rather than failing when none
    are found.
    """
    return discover_instances()


@app.post("/instance/detect", response_model=Instance)
def instance_detect(req: ScanRequest) -> Instance:
    """Classify a dropped path (launcher instance or bare ``mods/`` folder).

    Recognises CurseForge / Modrinth / Prism / MultiMC instances and locates
    their content folders, so the front can summarise the pack (name, loader,
    version, counts) before a full scan.
    """
    return detect_instance(_require_dir(req.path))


@app.post("/instance/scan", response_model=InstanceReport)
def instance_scan(req: ScanRequest) -> InstanceReport:
    """Full instance analysis: the mod conflict map plus content-pack sections.

    The path may be a launcher instance root (CurseForge/Modrinth/Prism…) or a
    bare ``mods/`` folder; mods and content folders are located automatically.
    Ambiguous Minecraft versions still 409 (the front prompts for a pick).
    """
    root = _require_dir(req.path)
    instance = detect_instance(root)
    jars = mods_jars(instance)
    profile, detection = _resolve_for_jars(jars, req.version)
    mods = scan_jars(jars, profile, instance.folders.mods or str(root))
    mods.detection = detection
    # Best-effort online enrichment (provider links + update status); offline-first.
    enrich_mods(instance, jars, mods.mods, profile.profile)

    folders = instance.folders
    resourcepacks, rp_conflicts = scan_resourcepacks(
        Path(folders.resourcepacks) if folders.resourcepacks else None
    )
    datapacks, dp_conflicts = scan_datapacks(folders.datapacks)
    shaderpacks = scan_shaderpacks(Path(folders.shaderpacks) if folders.shaderpacks else None)
    return InstanceReport(
        instance=instance,
        mods=mods,
        resourcepacks=resourcepacks,
        datapacks=datapacks,
        shaderpacks=shaderpacks,
        resourcepack_conflicts=rp_conflicts,
        datapack_conflicts=dp_conflicts,
        items=build_registry_index(jars),
    )


@app.post("/mods/update", response_model=UpdateResult)
def mods_update(req: UpdateRequest) -> UpdateResult:
    """Update one jar in a mods folder to its latest Modrinth version, in place.

    Explicit user action: downloads, verifies the checksum, swaps the jar and
    removes the old one. The mods folder is left untouched on any failure.
    """
    mods_dir = _require_dir(req.path)
    loader = req.loader or detect_loader(mods_dir)
    game_version = req.version or _resolve_for(mods_dir, None)[0].profile
    return update_mod(mods_dir, req.jar, loader, game_version)


@app.post("/mods/install", response_model=InstallResult)
def mods_install(req: InstallRequest) -> InstallResult:
    """Install a dependency the runner flagged as missing, from Modrinth, in place.

    Explicit user action from the runtime verdict: resolves the missing mod id to
    a Modrinth project, downloads the version matching the pack's loader + MC
    version, verifies the checksum and adds the jar. No-op on any failure.
    """
    mods_dir = _require_dir(req.path)
    loader = req.loader or detect_loader(mods_dir)
    game_version = req.version or _resolve_for(mods_dir, None)[0].profile
    return install_mod(mods_dir, req.mod_id, loader, game_version)


@app.post("/mods/disable", response_model=DisableResult)
def mods_disable(req: DisableRequest) -> DisableResult:
    """Disable a mod's jar in place by appending ``.disabled`` (reversible).

    Explicit user action from the mixin resolver: when two mods incompatibly
    patch the same target and no compatible update exists, disable one rather
    than delete it. The jar is renamed ``<jar>.disabled`` — excluded from scans
    and boots (which glob ``*.jar``) — and ``/mods/enable`` strips the suffix.
    """
    return disable_mod(_require_dir(req.path), req.jar)


@app.post("/mods/enable", response_model=DisableResult)
def mods_enable(req: DisableRequest) -> DisableResult:
    """Re-enable a disabled mod by stripping its ``.disabled`` suffix."""
    return enable_mod(_require_dir(req.path), req.jar)


@app.post("/runner/test", response_model=RunVerdict)
def runner_test(req: RunRequest) -> RunVerdict:
    """Boot a mod set in a headless Fabric server and return a verdict (§8).

    Long-running: a real boot takes minutes. A missing Docker daemon yields a
    verdict with ``status: error`` rather than an HTTP error.
    """
    folder = _require_dir(req.path)
    profile, _ = _resolve_for(folder, req.version)
    return run_set(req, profile)


@app.post("/runner/bisect", response_model=BisectResult)
def runner_bisect(req: RunRequest) -> BisectResult:
    """Bisect a crashing set down to the guilty subset (§10, Phase 3).

    Long-running: each step is a real boot (~log2(N) of them). Returns the
    minimal reproducing set, or ``no_conflict`` if the full set boots cleanly.
    """
    folder = _require_dir(req.path)
    profile, _ = _resolve_for(folder, req.version)
    return bisect_set(req, profile)


@app.post("/resolve/variants", response_model=ResolutionVariants)
def resolve_variants(req: VariantsRequest) -> ResolutionVariants:
    """Per-conflict recipe variants for the selection cards (each mod's version).

    Reads the colliding recipes' JSON from every contributing jar so the front can
    show what each mod would write; tag variants already ride along in the scan.
    """
    folder = _require_dir(req.path)
    profile, _ = _resolve_for(folder, req.version)
    return ResolutionVariants(recipes=collect_recipe_variants(folder, profile))


def _winner_bodies(
    folder: Path,
    profile: VersionProfile,
    families: Sequence[str] | None,
    recipe_winners: dict[str, str] | None,
) -> dict[str, str]:
    """Winning recipe JSON per id when the recipes family is in scope, else empty."""
    if families is not None and "recipes" not in families:
        return {}
    return recipe_winner_bodies(folder, profile, recipe_winners)


@app.post("/resolve/preview", response_model=ResolutionPlan)
def resolve_preview(req: ResolveRequest) -> ResolutionPlan:
    """Generate the no-code resolution artifacts for a scanned folder (§10).

    Honours the per-conflict winner picks: the chosen recipe JSON is read from its
    jar and the per-tag winner is written into ``unify.json``.
    """
    folder = _require_dir(req.path)
    profile, _ = _resolve_for(folder, req.version)
    scan = scan_mods_folder(folder, profile.profile)
    bodies = _winner_bodies(folder, profile, req.families, req.recipe_winners)
    return build_resolution_plan(
        profile,
        scan.conflicts,
        req.mod_priorities,
        req.families,
        recipe_bodies=bodies,
        tag_winners=req.tag_winners,
    )


@app.post("/resolve/export", response_model=ExportResult)
def resolve_export(req: ExportRequest) -> ExportResult:
    """Write the generated resolution files under ``out_dir`` (winner-aware)."""
    folder = _require_dir(req.path)
    profile, _ = _resolve_for(folder, req.version)
    scan = scan_mods_folder(folder, profile.profile)
    bodies = _winner_bodies(folder, profile, req.families, req.recipe_winners)
    plan = build_resolution_plan(
        profile,
        scan.conflicts,
        req.mod_priorities,
        req.families,
        recipe_bodies=bodies,
        tag_winners=req.tag_winners,
    )
    out_dir = Path(req.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    return ExportResult(out_dir=str(out_dir), written=export_plan(plan, out_dir))


def _resolve_for_instance(root: Path, version: str | None) -> VersionProfile:
    """Resolve the version profile from an instance root (its mods live in mods/)."""
    instance = detect_instance(root)
    mods_dir = Path(instance.folders.mods) if instance.folders.mods else root
    return _resolve_for(mods_dir, version)[0]


@app.post("/resolve/targets", response_model=ResolutionTargets)
def resolve_targets(req: VariantsRequest) -> ResolutionTargets:
    """What the pack supports for applying a resolution (AU / Open Loader / worlds)."""
    root = _require_dir(req.path)
    return resolution_targets(root, _resolve_for_instance(root, req.version))


@app.post("/resolve/apply", response_model=ApplyResult)
def resolve_apply(req: ApplyRequest) -> ApplyResult:
    """Write the resolution into the instance (reversibly) and return its manifest.

    ``path`` is the instance root: the override datapack lands per-world or under
    Open Loader (``target``), and ``unify.json`` under ``config/`` when Almost
    Unified is installed. Honours the per-conflict winner picks.
    """
    root = _require_dir(req.path)
    profile = _resolve_for_instance(root, req.version)
    return apply_resolution(
        root,
        profile,
        recipe_winners=req.recipe_winners,
        tag_winners=req.tag_winners,
        target=req.target,
    )


@app.post("/resolve/revert", response_model=RevertResult)
def resolve_revert(req: RevertRequest) -> RevertResult:
    """Undo a prior apply by its manifest path (deletes the files it wrote)."""
    return revert_resolution(Path(req.manifest))
