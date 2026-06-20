from pathlib import Path

from app.models import RunRequest
from app.profile import get_profile
from app.runner import runner
from app.runner.runner import build_run_args, run_set

PROFILE = get_profile("1.21.1")


def test_build_run_args_uses_profile_and_mixin_flags(tmp_path: Path) -> None:
    args = build_run_args("emendator-test", tmp_path, "4G", PROFILE)

    assert args[:3] == ["docker", "run", "-d"]
    assert f"{runner._IMAGE}:java21" == args[-1]  # JDK from profile
    joined = " ".join(args)
    assert "TYPE=FABRIC" in joined
    assert "VERSION=1.21.1" in joined
    assert "MEMORY=4G" in joined
    assert "mixin.debug.export=true" in joined
    assert f"{tmp_path.as_posix()}:/data" in joined


def test_build_run_args_hardening(tmp_path: Path) -> None:
    joined = " ".join(build_run_args("c", tmp_path, "2G", PROFILE))
    assert "--cap-drop ALL" in joined
    assert "--cap-add CHOWN" in joined
    assert "--security-opt no-new-privileges" in joined
    assert "--pids-limit 512" in joined
    assert "--network bridge" in joined  # default


def test_build_run_args_network_override(tmp_path: Path) -> None:
    joined = " ".join(build_run_args("c", tmp_path, "2G", PROFILE, network="none"))
    assert "--network none" in joined


def test_run_set_rejects_non_directory(tmp_path: Path) -> None:
    missing = tmp_path / "nope"
    verdict = run_set(RunRequest(path=str(missing)), PROFILE)
    assert verdict.status == "error"
    assert verdict.cause is not None
    assert "directory" in verdict.cause.summary.lower()


def test_run_set_reports_when_docker_unavailable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(runner, "is_docker_available", lambda: False)
    verdict = run_set(RunRequest(path=str(tmp_path)), PROFILE)
    assert verdict.status == "error"
    assert verdict.cause is not None
    assert "docker" in verdict.cause.summary.lower()
    assert verdict.profile == "1.21.1"


def test_decide_maps_outcomes() -> None:
    assert runner._decide("ok", "", None) == ("ok", None)
    crash_status, crash_cause = runner._decide(
        "exited", "Mixin apply for mod sodium failed x from mod sodium", None
    )
    assert crash_status == "crash"
    assert crash_cause is not None and crash_cause.category == "mixin_apply"
    timeout_status, _ = runner._decide("timeout", "still loading...", None)
    assert timeout_status == "timeout"


def test_read_mixin_exports_lists_transformed_classes(tmp_path: Path) -> None:
    export = tmp_path / ".mixin.out" / "class" / "net" / "minecraft" / "server"
    export.mkdir(parents=True)
    (export / "MinecraftServer.class").write_bytes(b"\xca\xfe\xba\xbe")
    assert runner._read_mixin_exports(tmp_path) == ["net.minecraft.server.MinecraftServer"]
