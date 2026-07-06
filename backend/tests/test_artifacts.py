"""Run-evidence persistence + the /runner/runs API."""

import time
from pathlib import Path

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from app.config import settings
from app.main import app
from app.models import RunCause, RunVerdict
from app.runner.artifacts import list_runs, persist_run, read_run_text, read_run_verdict

client = TestClient(app)


def _verdict(status: str = "crash") -> RunVerdict:
    return RunVerdict(
        status=status,  # type: ignore[arg-type]
        profile="1.21.1",
        duration_ms=1234,
        cause=RunCause(category="mixin_apply", summary="boom") if status != "ok" else None,
        crash_report="---- Minecraft Crash Report ----" if status != "ok" else None,
    )


_counter = 0


def _workdir(tmp_path: Path, with_crash: bool = True, with_export: bool = True) -> Path:
    global _counter
    _counter += 1
    workdir = tmp_path / f"work{_counter}"
    (workdir / "logs").mkdir(parents=True)
    (workdir / "logs" / "latest.log").write_text("line1\nline2\n")
    if with_crash:
        (workdir / "crash-reports").mkdir()
        (workdir / "crash-reports" / "crash-2026-07-06.txt").write_text("crash body")
    if with_export:
        export = workdir / ".mixin.out" / "class" / "net" / "minecraft"
        export.mkdir(parents=True)
        (export / "class_761.class").write_bytes(b"\xca\xfe\xba\xbe")
    return workdir


def test_persist_run_copies_evidence_and_sets_run_id(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "runs_dir", str(tmp_path / "runs"))
    verdict = _verdict()
    run_id = persist_run(_workdir(tmp_path), verdict)

    assert run_id is not None
    assert verdict.run_id == run_id
    run_dir = tmp_path / "runs" / run_id
    assert (run_dir / "latest.log").read_text() == "line1\nline2\n"
    assert (run_dir / "crash-report.txt").read_text() == "crash body"
    assert (run_dir / "mixin-out" / "net" / "minecraft" / "class_761.class").exists()

    reloaded = read_run_verdict(run_id)
    assert reloaded is not None
    assert reloaded.status == "crash"
    assert reloaded.crash_report == "---- Minecraft Crash Report ----"
    assert read_run_text(run_id, "latest.log") == "line1\nline2\n"


def test_persist_run_skips_export_for_clean_boot(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "runs_dir", str(tmp_path / "runs"))
    run_id = persist_run(_workdir(tmp_path, with_crash=False), _verdict("ok"))
    assert run_id is not None
    run_dir = tmp_path / "runs" / run_id
    assert not (run_dir / "mixin-out").exists()  # heavyweight artifact: failed boots only
    assert not (run_dir / "crash-report.txt").exists()
    assert (run_dir / "latest.log").exists()


def test_retention_prunes_oldest(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "runs_dir", str(tmp_path / "runs"))
    monkeypatch.setattr(settings, "runs_retention", 2)
    ids: list[str] = []
    for _ in range(3):
        run_id = persist_run(_workdir(tmp_path), _verdict())
        assert run_id is not None
        ids.append(run_id)
        time.sleep(0.02)  # distinct mtimes on coarse filesystems
    kept = {d.name for d in (tmp_path / "runs").iterdir()}
    assert kept == set(ids[-2:])  # oldest pruned


def test_list_runs_newest_first(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "runs_dir", str(tmp_path / "runs"))
    first = persist_run(_workdir(tmp_path), _verdict())
    time.sleep(0.02)
    second = persist_run(_workdir(tmp_path), _verdict("ok"))
    runs = list_runs()
    assert [r.run_id for r in runs] == [second, first]
    assert runs[0].status == "ok"
    assert runs[1].category == "mixin_apply"


def test_runs_endpoints(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "runs_dir", str(tmp_path / "runs"))
    run_id = persist_run(_workdir(tmp_path), _verdict())
    assert run_id is not None

    listed = client.get("/runner/runs")
    assert listed.status_code == 200
    assert listed.json()[0]["runId"] == run_id

    verdict = client.get(f"/runner/runs/{run_id}")
    assert verdict.status_code == 200
    body = verdict.json()
    assert body["crashReport"] == "---- Minecraft Crash Report ----"
    assert body["runId"] == run_id

    assert client.get(f"/runner/runs/{run_id}/log").text == "line1\nline2\n"
    assert client.get(f"/runner/runs/{run_id}/crash").text == "crash body"


def test_runs_endpoints_reject_unknown_and_traversal(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "runs_dir", str(tmp_path / "runs"))
    assert client.get("/runner/runs/aaaabbbbcccc").status_code == 404
    # ids are strictly 12 hex chars: traversal shapes never reach the filesystem
    assert client.get("/runner/runs/..%2f..%2fsecrets").status_code == 404
    assert read_run_text("../escape", "latest.log") is None
