from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.analyzer.mods import scan_mods_folder
from app.config import settings
from app.models import ScanRequest, ScanResult

app = FastAPI(title="Emendator backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe consumed by the front to confirm the sidecar is up."""
    return {"status": "ok", "profile": settings.profile}


@app.post("/mods/scan", response_model=ScanResult)
def scan_mods(req: ScanRequest) -> ScanResult:
    """Ingest a local ``mods/`` folder into the conflict map (Phase 0 slice)."""
    folder = Path(req.path)
    if not folder.exists():
        raise HTTPException(status_code=400, detail=f"Path does not exist: {req.path}")
    if not folder.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a directory: {req.path}")
    return scan_mods_folder(folder, settings.profile)
