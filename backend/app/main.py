from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.analyzer.mods import read_jars_metadata, read_mods_metadata, scan_jars, scan_mods_folder
from app.analyzer.packs import scan_datapacks, scan_resourcepacks, scan_shaderpacks
from app.analyzer.registry_index import build_registry_index
from app.config import settings
from app.enrich import enrich_mods
from app.models import (
    BisectResult,
    ExportRequest,
    ExportResult,
    Instance,
    InstanceReport,
    ResolutionPlan,
    ResolveRequest,
    RunRequest,
    RunVerdict,
    ScanRequest,
    ScanResult,
    VersionCandidate,
    VersionDetection,
)
from app.profile import (
    VersionProfile,
    available_profiles,
    detect_version,
    resolve_profile,
)
from app.resolve.generate import build_resolution_plan, export_plan
from app.runner.bisect import bisect_set
from app.runner.runner import run_set
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


@app.post("/resolve/preview", response_model=ResolutionPlan)
def resolve_preview(req: ResolveRequest) -> ResolutionPlan:
    """Generate the no-code resolution artifacts for a scanned folder (§10)."""
    folder = _require_dir(req.path)
    profile, _ = _resolve_for(folder, req.version)
    scan = scan_mods_folder(folder, profile.profile)
    return build_resolution_plan(profile, scan.conflicts, req.mod_priorities)


@app.post("/resolve/export", response_model=ExportResult)
def resolve_export(req: ExportRequest) -> ExportResult:
    """Write the generated resolution files under ``out_dir``."""
    folder = _require_dir(req.path)
    profile, _ = _resolve_for(folder, req.version)
    scan = scan_mods_folder(folder, profile.profile)
    plan = build_resolution_plan(profile, scan.conflicts, req.mod_priorities)
    out_dir = Path(req.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    return ExportResult(out_dir=str(out_dir), written=export_plan(plan, out_dir))
