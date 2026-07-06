"""Persist and serve boot-run evidence.

The runner's workdir is a throwaway tempdir; before it is removed, the pieces
an agent (human or LLM) needs to reason about a failure are copied out here:

    <runs>/<run_id>/verdict.json      — the full RunVerdict (incl. attribution)
    <runs>/<run_id>/latest.log        — the server log, unabridged
    <runs>/<run_id>/crash-report.txt  — newest crash report, when one exists
    <runs>/<run_id>/mixin-out/        — post-transform bytecode export
                                        (failed boots only — it is large)

Everything is best-effort: persistence failing never fails the boot itself.
Retention keeps the newest ``settings.runs_retention`` runs.
"""

import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.config import settings
from app.models import RunSummary, RunVerdict

_RUN_ID_RE = re.compile(r"^[0-9a-f]{12}$")


def runs_root() -> Path:
    base = settings.runs_dir or (Path.home() / ".emendator" / "runs")
    return Path(base)


def persist_run(workdir: Path, verdict: RunVerdict) -> str | None:
    """Copy the run's evidence out of ``workdir``; returns the run id (or None).

    Mutates ``verdict.run_id`` so the persisted ``verdict.json`` and the API
    response both carry the handle.
    """
    try:
        run_id = uuid4().hex[:12]
        run_dir = runs_root() / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        log = workdir / "logs" / "latest.log"
        if log.is_file():
            shutil.copy2(log, run_dir / "latest.log")

        crash_dir = workdir / "crash-reports"
        if crash_dir.is_dir():
            reports = sorted(crash_dir.glob("*.txt"), key=lambda p: p.stat().st_mtime)
            if reports:
                shutil.copy2(reports[-1], run_dir / "crash-report.txt")

        # The bytecode export is the heavyweight artifact — keep it only where
        # it earns its bytes: boots an agent will actually investigate.
        export = workdir / ".mixin.out" / "class"
        if verdict.status in ("crash", "timeout") and export.is_dir():
            shutil.copytree(export, run_dir / "mixin-out", dirs_exist_ok=True)

        verdict.run_id = run_id
        (run_dir / "verdict.json").write_text(
            verdict.model_dump_json(by_alias=True), encoding="utf-8"
        )
        _prune(runs_root())
        return run_id
    except OSError:
        verdict.run_id = None
        return None


def list_runs() -> list[RunSummary]:
    """Persisted runs, newest first."""
    root = runs_root()
    if not root.is_dir():
        return []
    summaries: list[tuple[float, RunSummary]] = []
    for run_dir in root.iterdir():
        verdict = _read_verdict(run_dir)
        if verdict is None or verdict.run_id is None:
            continue
        mtime = run_dir.stat().st_mtime
        summaries.append(
            (
                mtime,
                RunSummary(
                    run_id=verdict.run_id,
                    status=verdict.status,
                    profile=verdict.profile,
                    duration_ms=verdict.duration_ms,
                    created_at=datetime.fromtimestamp(mtime, tz=UTC).isoformat(),
                    category=verdict.cause.category if verdict.cause else None,
                ),
            )
        )
    return [summary for _, summary in sorted(summaries, key=lambda s: s[0], reverse=True)]


def read_run_verdict(run_id: str) -> RunVerdict | None:
    run_dir = _run_dir(run_id)
    return _read_verdict(run_dir) if run_dir else None


def read_run_text(run_id: str, name: str) -> str | None:
    """A run's ``latest.log`` / ``crash-report.txt`` content, when present."""
    run_dir = _run_dir(run_id)
    if run_dir is None:
        return None
    path = run_dir / name
    try:
        return path.read_text(errors="replace") if path.is_file() else None
    except OSError:
        return None


def _run_dir(run_id: str) -> Path | None:
    """The run's directory — ids are validated so a path can't traverse out."""
    if not _RUN_ID_RE.fullmatch(run_id):
        return None
    run_dir = runs_root() / run_id
    return run_dir if run_dir.is_dir() else None


def _read_verdict(run_dir: Path) -> RunVerdict | None:
    path = run_dir / "verdict.json"
    try:
        return RunVerdict.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _prune(root: Path) -> None:
    """Drop the oldest runs beyond the retention window."""
    try:
        run_dirs = sorted(
            (d for d in root.iterdir() if d.is_dir()),
            key=lambda d: d.stat().st_mtime,
            reverse=True,
        )
        for stale in run_dirs[max(settings.runs_retention, 1) :]:
            shutil.rmtree(stale, ignore_errors=True)
    except OSError:
        pass
