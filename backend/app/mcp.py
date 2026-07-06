"""MCP server: drive Emendator from any MCP client (Claude Code/Desktop, …).

A stdio server (``python -m app.mcp``, or ``emendator-backend mcp`` from the
frozen sidecar) wrapping the same internals the HTTP API serves — scan, boot,
bisect, run evidence, and the mixin fix ladder — so an agent can reason over a
broken pack and fix it precisely.

Guardrails:

- every mutating tool is **dry-run by default**: without ``apply=true`` it
  returns a preview plus a note to confirm with the user first;
- everything a mutation does is recorded in the same revert manifests the UI
  uses, and ``revert_mixin_fixes`` undoes them;
- errors come back as structured ``{"error": ...}`` values, never exceptions,
  so agent loops can branch on them.

Long-running tools (``run_test``, ``bisect``) block for the duration of a real
Docker boot (minutes); per-boot progress remains on the HTTP SSE twins.
"""

from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from app.analyzer.mods import read_jars_metadata, scan_jars
from app.enrich import install as install_ops
from app.models import RunRequest
from app.profile import detect_version, resolve_profile
from app.resolve import mixins as mixin_ops
from app.runner import artifacts
from app.runner.bisect import bisect_set
from app.runner.runner import detect_loader, run_set
from app.sources.instance import detect_instance, mods_jars

mcp = FastMCP(
    "emendator",
    instructions=(
        "Emendator analyzes Minecraft modpacks: static conflict detection "
        "(mixins graded by patch mechanics), headless Docker boots, crash "
        "bisection, and a precise mixin fix ladder. Mutating tools are "
        "dry-run unless apply=true — confirm with the user before applying."
    ),
)

_MUTATION_NOTE = "Dry-run: pass apply=true after confirming the action with the user."


def _profile_for(root: Path, version: str | None) -> tuple[Any, list[Path]] | dict[str, Any]:
    """Resolve the version profile for an instance, or an ``{"error": ...}``."""
    jars = mods_jars(detect_instance(root))
    mods, _errors = read_jars_metadata(jars)
    detection = detect_version(
        [(mod.id, mod.depends.get("minecraft")) for mod in mods], forced=version
    )
    if detection.detected_version is None or (version is None and detection.status == "ambiguous"):
        return {
            "error": "ambiguous_version",
            "detail": detection.model_dump(by_alias=True),
            "note": "Pass an explicit version from detail.candidates.",
        }
    return resolve_profile(detection.detected_version), jars


@mcp.tool()
def scan_instance(path: str, version: str | None = None) -> dict[str, Any]:
    """Scan a modpack instance (or bare mods folder): mods + graded conflict map.

    Mixin conflicts carry per-method reasoning in detail.methodDetails
    (kinds, overwrites, priorities, mixinClasses, requiredBy).
    """
    resolved = _profile_for(Path(path), version)
    if isinstance(resolved, dict):
        return resolved
    profile, jars = resolved
    return scan_jars(jars, profile, path).model_dump(by_alias=True)


@mcp.tool()
def run_test(path: str, version: str | None = None, timeout_seconds: int = 300) -> dict[str, Any]:
    """Boot the set in a headless Docker server and classify the outcome.

    Long-running (a real boot: minutes). The verdict carries the crash cause,
    full crash report, per-mixin application records and a persisted runId —
    fetch raw evidence with get_run_log / get_run_crash.
    """
    resolved = _profile_for(Path(path), version)
    if isinstance(resolved, dict):
        return resolved
    profile, jars = resolved
    mods_dir = jars[0].parent if jars else Path(path)
    request = RunRequest(path=str(mods_dir), timeout_seconds=timeout_seconds)
    return run_set(request, profile).model_dump(by_alias=True)


@mcp.tool()
def bisect(path: str, version: str | None = None, timeout_seconds: int = 300) -> dict[str, Any]:
    """Delta-debug a crashing set down to the minimal guilty subset.

    Very long-running: ~log2(N) real boots. Returns the guilty members and the
    confirmed cause.
    """
    resolved = _profile_for(Path(path), version)
    if isinstance(resolved, dict):
        return resolved
    profile, jars = resolved
    mods_dir = jars[0].parent if jars else Path(path)
    request = RunRequest(path=str(mods_dir), timeout_seconds=timeout_seconds)
    return bisect_set(request, profile).model_dump(by_alias=True)


@mcp.tool()
def list_runs() -> list[dict[str, Any]]:
    """Persisted boot runs (newest first) — the evidence store."""
    return [summary.model_dump(by_alias=True) for summary in artifacts.list_runs()]


@mcp.tool()
def get_run(run_id: str) -> dict[str, Any]:
    """The full persisted verdict of one run (cause, attribution, crash report)."""
    verdict = artifacts.read_run_verdict(run_id)
    return verdict.model_dump(by_alias=True) if verdict else {"error": f"no such run: {run_id}"}


@mcp.tool()
def get_run_log(run_id: str) -> str:
    """The run's unabridged latest.log."""
    return artifacts.read_run_text(run_id, "latest.log") or f"error: no log for run {run_id}"


@mcp.tool()
def get_run_crash(run_id: str) -> str:
    """The run's newest crash report (or an error string when none exists)."""
    return (
        artifacts.read_run_text(run_id, "crash-report.txt")
        or f"error: no crash report for run {run_id}"
    )


@mcp.tool()
def plan_mixin_fixes(
    path: str, version: str | None = None, losers: dict[str, str] | None = None
) -> dict[str, Any]:
    """Plan the mixin fix ladder: per conflict, the loser and the cheapest rung.

    Rungs, most precise first: the mod's own per-mixin toggle, a filter-mod
    config (Mixin Blacklist / Mixin Helper), else disabling the jar. Rollback
    and jar-patch are listed as manual alternatives. featureHints state what
    each fix trades away — surface them to the user.
    """
    resolved = _profile_for(Path(path), version)
    if isinstance(resolved, dict):
        return resolved
    profile, _jars = resolved
    return mixin_ops.plan_mixin_fixes(Path(path), profile, losers).model_dump(by_alias=True)


@mcp.tool()
def apply_mixin_fixes(
    path: str,
    version: str | None = None,
    losers: dict[str, str] | None = None,
    targets: list[str] | None = None,
    allow_disable: bool = True,
    apply: bool = False,
) -> dict[str, Any]:
    """Execute the planned mixin fixes, reversibly. DRY-RUN unless apply=true.

    Generated configs merge into existing user files, disables use the
    .disabled rename, and everything lands in a manifest revert_mixin_fixes
    can undo. The result's manifest path is the revert handle — keep it.
    """
    resolved = _profile_for(Path(path), version)
    if isinstance(resolved, dict):
        return resolved
    profile, _jars = resolved
    if not apply:
        preview = mixin_ops.plan_mixin_fixes(Path(path), profile, losers)
        return {"applied": False, "note": _MUTATION_NOTE, "plan": preview.model_dump(by_alias=True)}
    result = mixin_ops.apply_mixin_fixes(
        Path(path), profile, losers=losers, targets=targets, allow_disable=allow_disable
    )
    return result.model_dump(by_alias=True)


@mcp.tool()
def revert_mixin_fixes(manifest: str, apply: bool = False) -> dict[str, Any]:
    """Undo a prior mixin apply by its manifest. DRY-RUN unless apply=true."""
    if not apply:
        return {"applied": False, "note": _MUTATION_NOTE, "manifest": manifest}
    return mixin_ops.revert_mixin_fixes(Path(manifest)).model_dump(by_alias=True)


@mcp.tool()
def verify_mixin_fixes(
    path: str, version: str | None = None, baseline_run_id: str | None = None
) -> dict[str, Any]:
    """Re-boot and diff against the pre-fix baseline run (long-running).

    fixed=true means the baseline crash signature is gone; exportsRemoved are
    the classes the loader no longer transforms. Client-section mixins are
    never exercised by a server boot.
    """
    resolved = _profile_for(Path(path), version)
    if isinstance(resolved, dict):
        return resolved
    profile, _jars = resolved
    result = mixin_ops.verify_mixin_fixes(Path(path), profile, baseline_run_id)
    return result.model_dump(by_alias=True)


def _mods_dir_and_context(path: str, version: str | None) -> tuple[Path, Any, Any] | dict[str, Any]:
    resolved = _profile_for(Path(path), version)
    if isinstance(resolved, dict):
        return resolved
    profile, jars = resolved
    mods_dir = jars[0].parent if jars else Path(path)
    return mods_dir, profile, detect_loader(mods_dir)


@mcp.tool()
def disable_mod(path: str, jar: str, apply: bool = False) -> dict[str, Any]:
    """Sideline one jar (.disabled rename, reversible). DRY-RUN unless apply=true."""
    if not apply:
        return {"applied": False, "note": _MUTATION_NOTE, "jar": jar}
    context = _mods_dir_and_context(path, None)
    if isinstance(context, dict):
        return context
    mods_dir, _profile, _loader = context
    return install_ops.disable_mod(mods_dir, jar).model_dump(by_alias=True)


@mcp.tool()
def enable_mod(path: str, jar: str, apply: bool = False) -> dict[str, Any]:
    """Restore a sidelined jar. DRY-RUN unless apply=true."""
    if not apply:
        return {"applied": False, "note": _MUTATION_NOTE, "jar": jar}
    context = _mods_dir_and_context(path, None)
    if isinstance(context, dict):
        return context
    mods_dir, _profile, _loader = context
    return install_ops.enable_mod(mods_dir, jar).model_dump(by_alias=True)


@mcp.tool()
def update_mod(
    path: str, jar: str, version: str | None = None, apply: bool = False
) -> dict[str, Any]:
    """Swap a jar for its latest Modrinth build. DRY-RUN unless apply=true."""
    if not apply:
        return {"applied": False, "note": _MUTATION_NOTE, "jar": jar}
    context = _mods_dir_and_context(path, version)
    if isinstance(context, dict):
        return context
    mods_dir, profile, loader = context
    return install_ops.update_mod(mods_dir, jar, loader, profile.profile).model_dump(by_alias=True)


@mcp.tool()
def rollback_mod(
    path: str, jar: str, version: str | None = None, apply: bool = False
) -> dict[str, Any]:
    """Swap a jar for the Modrinth release just before it. DRY-RUN unless apply=true."""
    if not apply:
        return {"applied": False, "note": _MUTATION_NOTE, "jar": jar}
    context = _mods_dir_and_context(path, version)
    if isinstance(context, dict):
        return context
    mods_dir, profile, loader = context
    return install_ops.rollback_mod(mods_dir, jar, loader, profile.profile).model_dump(
        by_alias=True
    )


def main() -> None:
    mcp.run()  # stdio transport


if __name__ == "__main__":
    main()
