"""Boot a mod set in a headless server container (any loader) and return a verdict.

Uses the proven ``itzg/minecraft-server`` image, the JDK tag from the version
profile, the loader as the image ``TYPE`` (Fabric/Quilt/Forge/NeoForge), and the
mixin debug flags from §7 so the loader exports the classes it actually
transforms (ground truth for mixin conflicts — SpongePowered Mixin underpins all
four loaders). The set is copied into a throwaway ``/data`` volume; we watch the
live ``latest.log`` until the server reaches a clean start ("Done") or the
container exits / times out, then classify the outcome.

No bisection here (Phase 3) — this boots the whole set as given. Docker calls go
through the CLI to avoid an SDK dependency; the daemon being down yields a clean
``error`` verdict rather than an exception.
"""

import contextlib
import shutil
import subprocess
import tempfile
import time
from collections import Counter
from pathlib import Path
from uuid import uuid4

from app.analyzer.mods import read_jars_metadata
from app.models import Loader, RunCause, RunRequest, RunStatus, RunVerdict
from app.profile import VersionProfile
from app.runner.classify import extract_cause, reached_done, tail

_IMAGE = "itzg/minecraft-server"
_MIXIN_FLAGS = "-Dmixin.debug.export=true -Dmixin.debug.verbose=true -Dmixin.checks=true"

# Our loader -> the itzg image TYPE that boots it. "unknown" falls back to Fabric.
_LOADER_TYPE: dict[Loader, str] = {
    "fabric": "FABRIC",
    "quilt": "QUILT",
    "forge": "FORGE",
    "neoforge": "NEOFORGE",
    "unknown": "FABRIC",
}


def detect_loader(folder: Path) -> Loader:
    """The dominant loader across a folder's jars (defaults to ``fabric``)."""
    mods, _errors = read_jars_metadata(sorted(folder.glob("*.jar")))
    counts: Counter[Loader] = Counter(mod.loader for mod in mods if mod.loader != "unknown")
    if not counts:
        return "fabric"
    loader, _n = counts.most_common(1)[0]
    return loader


_POLL_SECONDS = 3.0
# `docker run -d` is detached, so it normally returns in well under a second.
# The slow case is the daemon waking its WSL2 backend from idle: `docker info`
# (the is_docker_available probe) answers from the API instantly, but the first
# real container start has to spin the VM back up, which can take well over 30s.
# Give it generous headroom; a true hang past this still degrades to a clean
# `error` verdict (see boot_jars) rather than a 500.
_DOCKER_CALL_TIMEOUT = 120
# Running mods = arbitrary code (§8). Drop every Linux capability and re-add only
# what the itzg entrypoint needs to fix permissions and drop to its unprivileged
# user. Combined with no-new-privileges, --pids-limit and --memory, this confines
# the boot well short of host access. Full network isolation (--network none)
# additionally needs a pre-baked offline image (see docker/Dockerfile.offline).
_KEEP_CAPS = ("CHOWN", "DAC_OVERRIDE", "FOWNER", "SETGID", "SETUID", "KILL")


def is_docker_available() -> bool:
    """True if the Docker daemon answers (Docker Desktop running)."""
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def build_run_args(
    container: str,
    workdir: Path,
    memory: str,
    profile: VersionProfile,
    network: str = "bridge",
    loader: Loader = "fabric",
) -> list[str]:
    """Assemble the ``docker run`` argv (pure, so it is unit-tested directly).

    ``network`` defaults to ``bridge`` because the itzg image downloads the
    server + loader on first boot; pass ``none`` only with the offline image.
    ``loader`` selects the image ``TYPE`` (itzg auto-resolves the loader build
    for the target version).
    """
    cap_args: list[str] = []
    for capability in _KEEP_CAPS:
        cap_args += ["--cap-add", capability]
    return [
        "docker",
        "run",
        "-d",
        "--name",
        container,
        "--memory",
        memory,
        "--pids-limit",
        "512",
        "--cap-drop",
        "ALL",
        *cap_args,
        "--security-opt",
        "no-new-privileges",
        "--network",
        network,
        "-e",
        "EULA=TRUE",
        "-e",
        f"TYPE={_LOADER_TYPE.get(loader, 'FABRIC')}",
        "-e",
        f"VERSION={profile.profile}",
        "-e",
        f"MEMORY={memory}",
        "-e",
        f"JVM_OPTS={_MIXIN_FLAGS}",
        "-v",
        f"{workdir.as_posix()}:/data",
        f"{_IMAGE}:java{profile.jdk}",
    ]


def boot_jars(
    jar_paths: list[Path],
    profile: VersionProfile,
    timeout_seconds: int = 300,
    memory: str = "3G",
    network: str = "bridge",
    loader: Loader = "fabric",
) -> RunVerdict:
    """Boot exactly ``jar_paths`` in a throwaway container and classify the log.

    This is the unit of work the bisector drives over subsets; ``run_set`` is a
    thin wrapper that boots a whole folder.
    """
    start = time.monotonic()
    if not is_docker_available():
        return _error(profile, start, "Docker is not available.")

    workdir = Path(tempfile.mkdtemp(prefix="emendator-run-"))
    container = f"emendator-{uuid4().hex[:8]}"
    try:
        mods_dir = workdir / "mods"
        mods_dir.mkdir()
        for jar in jar_paths:
            shutil.copy2(jar, mods_dir / jar.name)

        try:
            launched = subprocess.run(
                build_run_args(container, workdir, memory, profile, network, loader),
                capture_output=True,
                text=True,
                timeout=_DOCKER_CALL_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return _error(
                profile,
                start,
                f"docker run did not return within {_DOCKER_CALL_TIMEOUT}s "
                "(Docker Desktop may be waking from idle — retry in a moment).",
            )
        if launched.returncode != 0:
            return _error(profile, start, "docker run failed", excerpt=launched.stderr.strip())

        outcome, _exit_code = _wait_for_boot(container, workdir, timeout_seconds)
        log_text = _read_log(workdir)
        crash = _read_crash_report(workdir)
        status, cause = _decide(outcome, log_text, crash)
        return RunVerdict(
            status=status,
            profile=profile.profile,
            duration_ms=_elapsed_ms(start),
            cause=cause,
            mixin_exports=_read_mixin_exports(workdir),
            log_tail=tail(log_text, 40),
        )
    finally:
        # Best-effort: a timed-out `docker run` can leave the container half-created
        # on the daemon. Force-remove it, but bound the call so cleanup can never
        # hang the request itself (the daemon may still be busy from the timeout).
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run(["docker", "rm", "-f", container], capture_output=True, timeout=30)
        shutil.rmtree(workdir, ignore_errors=True)


def run_set(request: RunRequest, profile: VersionProfile) -> RunVerdict:
    """Boot ``request.path`` as a whole set and return the classified verdict."""
    folder = Path(request.path)
    if not folder.is_dir():
        return _error(profile, time.monotonic(), f"Not a directory: {request.path}")
    loader = request.loader or detect_loader(folder)
    return boot_jars(
        sorted(folder.glob("*.jar")),
        profile,
        request.timeout_seconds,
        request.memory,
        loader=loader,
    )


def _wait_for_boot(container: str, workdir: Path, timeout: int) -> tuple[str, int]:
    """Poll the live log until clean start / container exit / timeout."""
    log_path = workdir / "logs" / "latest.log"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if log_path.exists() and reached_done(log_path.read_text(errors="replace")):
            return "ok", 0
        if not _container_running(container):
            return "exited", _container_exit_code(container)
        time.sleep(_POLL_SECONDS)
    return "timeout", -1


def _decide(outcome: str, log_text: str, crash: str | None) -> tuple[RunStatus, RunCause | None]:
    if outcome == "ok":
        return "ok", None
    cause = extract_cause(log_text, crash)
    if outcome == "timeout":
        return "timeout", cause
    return "crash", cause


def _container_running(container: str) -> bool:
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", container],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() == "true"


def _container_exit_code(container: str) -> int:
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.ExitCode}}", container],
        capture_output=True,
        text=True,
    )
    try:
        return int(result.stdout.strip())
    except ValueError:
        return -1


def _read_log(workdir: Path) -> str:
    log_path = workdir / "logs" / "latest.log"
    return log_path.read_text(errors="replace") if log_path.exists() else ""


def _read_crash_report(workdir: Path) -> str | None:
    crash_dir = workdir / "crash-reports"
    if not crash_dir.is_dir():
        return None
    reports = sorted(crash_dir.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    return reports[0].read_text(errors="replace") if reports else None


def _read_mixin_exports(workdir: Path) -> list[str]:
    """Dotted class names the loader actually transformed (mixin debug export)."""
    export_dir = workdir / ".mixin.out" / "class"
    if not export_dir.is_dir():
        return []
    classes = [
        path.relative_to(export_dir).with_suffix("").as_posix().replace("/", ".")
        for path in export_dir.rglob("*.class")
    ]
    return sorted(classes)


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


def _error(
    profile: VersionProfile, start: float, summary: str, excerpt: str | None = None
) -> RunVerdict:
    return RunVerdict(
        status="error",
        profile=profile.profile,
        duration_ms=_elapsed_ms(start),
        cause=RunCause(category="startup_error", summary=summary, excerpt=excerpt),
    )
