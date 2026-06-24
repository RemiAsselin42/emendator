"""Automated bisection of a crashing mod set (PROJECT.md §10, Phase 3).

When the full set crashes, reduce it to the minimal subset that still reproduces
the *same* failure — typically the guilty pair (§8). The reducer is Zeller's
**ddmin** (pure, unit-tested with a synthetic oracle). The oracle boots a subset
via the Phase 2 runner and counts it as a reproduction only when the crash cause
matches the original, so removing an unrelated dependency (a *different* crash)
never derails the search. Dependency-provider jars are kept in **every** boot so
their absence can't cause a spurious missing-dependency crash.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.analyzer.mods import scan_mods_folder
from app.models import BisectResult, BisectStatus, RunCause, RunRequest
from app.profile import VersionProfile
from app.runner.runner import boot_jars, detect_loader, is_docker_available


@dataclass
class BisectProgress:
    """Live bisection status for the UI, emitted once per boot.

    ``step`` is the phase (``full`` initial boot, ``reduce`` ddmin trial, ``confirm``
    final minimal boot); ``boots`` is how many boots have started; ``testing`` is the
    jar count booting now; ``remaining`` is how many candidates are still in play.
    """

    step: str
    boots: int
    testing: int
    remaining: int


# Satisfied by the runtime/loader, never shipped as a candidate jar.
_ENV_PROVIDED = {
    "minecraft",
    "java",
    "fabricloader",
    "fabric-loader",
    "mixinextras",
    "quilt_loader",
    "forge",
    "neoforge",
    "fml",
    "javafml",
}


def _partition[T](items: list[T], n: int) -> list[list[T]]:
    """Split ``items`` into up to ``n`` near-equal contiguous chunks."""
    n = min(n, len(items))
    if n <= 0:
        return []
    base, extra = divmod(len(items), n)
    chunks: list[list[T]] = []
    start = 0
    for i in range(n):
        end = start + base + (1 if i < extra else 0)
        chunks.append(items[start:end])
        start = end
    return [chunk for chunk in chunks if chunk]


def ddmin[T](
    elements: list[T],
    reproduces: Callable[[list[T]], bool],
    on_candidate: Callable[[int], None] | None = None,
) -> list[T]:
    """Minimal failing subset of ``elements`` (precondition: the whole set fails).

    Delta debugging: try smaller chunks, then complements, increasing
    granularity until nothing can be removed while still reproducing.

    ``on_candidate(size)`` fires with the working-set size at start and after each
    reduction, so a caller can report how many candidates are still in play.
    """
    candidate = list(elements)
    if on_candidate is not None:
        on_candidate(len(candidate))
    granularity = 2
    while len(candidate) >= 2:
        chunks = _partition(candidate, granularity)
        reduced = False

        for chunk in chunks:
            if reproduces(chunk):
                candidate = chunk
                granularity = 2
                reduced = True
                break

        if not reduced:
            for chunk in chunks:
                complement = [x for x in candidate if x not in chunk]
                if complement and reproduces(complement):
                    candidate = complement
                    granularity = max(granularity - 1, 2)
                    reduced = True
                    break

        if reduced:
            if on_candidate is not None:
                on_candidate(len(candidate))
        else:
            if granularity >= len(candidate):
                break
            granularity = min(granularity * 2, len(candidate))

    return candidate


def _split_base_candidates(
    folder: Path, profile_name: str
) -> tuple[list[Path], list[Path], dict[str, str]]:
    """Partition the folder's jars into dependency-providers (base) and candidates."""
    scan = scan_mods_folder(folder, profile_name)
    depended: set[str] = set()
    for mod in scan.mods:
        depended.update(mod.depends.keys())
    depended -= _ENV_PROVIDED

    jar_to_id: dict[str, str] = {mod.jar: mod.id for mod in scan.mods}
    base_names = {mod.jar for mod in scan.mods if ({mod.id, *mod.provides} & depended)}

    jars_by_name = {path.name: path for path in folder.glob("*.jar")}
    base = [jars_by_name[name] for name in sorted(base_names) if name in jars_by_name]
    candidates = [path for name, path in sorted(jars_by_name.items()) if name not in base_names]
    return base, candidates, jar_to_id


def bisect_set(
    request: RunRequest,
    profile: VersionProfile,
    on_progress: Callable[[BisectProgress], None] | None = None,
) -> BisectResult:
    """Boot the full set; if it crashes, ddmin down to the guilty subset.

    ``on_progress`` (optional) is called once per boot with a :class:`BisectProgress`
    so the UI can show the search is alive and how far it has narrowed.
    """
    start = time.monotonic()
    folder = Path(request.path)
    if not folder.is_dir():
        return _result("error", profile, start, note=f"Not a directory: {request.path}")
    if not is_docker_available():
        return _result(
            "error", profile, start, note="Docker is not available — start Docker Desktop."
        )

    base, candidates, jar_to_id = _split_base_candidates(folder, profile.profile)
    loader = request.loader or detect_loader(folder)
    boots = 0
    remaining = len(candidates)

    def emit(step: str, testing: int) -> None:
        if on_progress is not None:
            on_progress(
                BisectProgress(step=step, boots=boots, testing=testing, remaining=remaining)
            )

    boots += 1
    emit("full", len(base) + len(candidates))
    full = boot_jars(
        base + candidates, profile, request.timeout_seconds, request.memory, loader=loader
    )
    if full.status == "error":
        return _result("error", profile, start, cause=full.cause, boots=boots)
    if full.status == "ok":
        return _result(
            "no_conflict", profile, start, boots=boots, note="The full set boots cleanly."
        )
    if full.status == "timeout":
        return _result(
            "inconclusive",
            profile,
            start,
            cause=full.cause,
            boots=boots,
            note="The full set timed out rather than crashing; cannot bisect reliably.",
        )

    original_category = full.cause.category if full.cause else "unknown"

    def reproduces(subset: list[Path]) -> bool:
        nonlocal boots
        boots += 1
        emit("reduce", len(base) + len(subset))
        verdict = boot_jars(
            base + subset, profile, request.timeout_seconds, request.memory, loader=loader
        )
        return (
            verdict.status == "crash"
            and verdict.cause is not None
            and verdict.cause.category == original_category
        )

    if not candidates:
        return _result(
            "inconclusive",
            profile,
            start,
            cause=full.cause,
            boots=boots,
            note="No reducible candidates — every jar is a dependency provider.",
        )

    def track(size: int) -> None:
        nonlocal remaining
        remaining = size

    minimal = ddmin(candidates, reproduces, on_candidate=track)
    members = sorted(jar_to_id.get(path.name, path.name) for path in minimal)
    boots += 1
    remaining = len(minimal)
    emit("confirm", len(base) + len(minimal))
    final = boot_jars(
        base + minimal, profile, request.timeout_seconds, request.memory, loader=loader
    )
    note = (
        None
        if len(minimal) <= 2
        else f"Reduced to {len(minimal)} mods (no smaller set reproduced)."
    )
    return _result(
        "isolated",
        profile,
        start,
        members=members,
        cause=final.cause or full.cause,
        boots=boots,
        note=note,
    )


def _result(
    status: BisectStatus,
    profile: VersionProfile,
    start: float,
    *,
    members: list[str] | None = None,
    cause: RunCause | None = None,
    boots: int = 0,
    note: str | None = None,
) -> BisectResult:
    return BisectResult(
        status=status,
        profile=profile.profile,
        members=members or [],
        cause=cause,
        boots=boots,
        duration_ms=int((time.monotonic() - start) * 1000),
        note=note,
    )
