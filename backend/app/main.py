from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.analyzer.mods import read_mods_metadata, scan_mods_folder
from app.config import settings
from app.models import (
    BisectResult,
    ExportRequest,
    ExportResult,
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


def _detect_in_folder(folder: Path) -> VersionDetection:
    """Run version detection from a folder's mod metadata (cheap first pass)."""
    mods, _errors = read_mods_metadata(folder)
    return detect_version([(mod.id, mod.depends.get("minecraft")) for mod in mods])


def _resolve_for(folder: Path, version: str | None) -> tuple[VersionProfile, VersionDetection]:
    """Pick the profile for a request: explicit ``version`` wins, else auto-detect.

    Raises HTTP 409 (carrying the :class:`VersionDetection`) when no version is
    given and the set is ambiguous — the front then asks the user to choose.
    """
    detection = _detect_in_folder(folder)
    chosen = version or detection.detected_version
    if chosen is None or (version is None and detection.status == "ambiguous"):
        raise HTTPException(status_code=409, detail=detection.model_dump(by_alias=True))
    return resolve_profile(chosen), detection


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
