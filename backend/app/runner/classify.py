"""Classify a headless server boot (any loader) from its log output.

Pure functions over captured text (``latest.log`` + optional crash report), so
they are fully unit-testable without Docker. We reuse mclo.gs / Crash Assistant
style signatures rather than reinventing error classification (PROJECT.md §12).
The clean-start line and the mixin signatures are loader-agnostic (vanilla and
SpongePowered Mixin underpin all loaders); Forge/NeoForge add their own
dependency-resolution wording, handled by extra signatures below.

The orchestrator decides the terminal :data:`RunStatus` (ok / crash / timeout)
from how the container ended; this module extracts the *cause* of a failure and
detects whether the server reached a clean start.
"""

import re

from app.models import CrashCategory, RunCause

# Vanilla prints this once the server is fully up: registries frozen, datapacks
# and recipes loaded. Reaching it is our definition of a successful boot (§8).
_DONE_RE = re.compile(r"Done \([\d.]+s\)! For help", re.IGNORECASE)

# Ordered most-specific first; the first matching signature wins.
_SIGNATURES: list[tuple[CrashCategory, re.Pattern[str], str]] = [
    (
        "mixin_apply",
        re.compile(r"Mixin apply for mod ([\w.-]+) failed", re.IGNORECASE),
        "A mixin failed to apply — two mods likely patch the same target incompatibly.",
    ),
    (
        "mixin_apply",
        re.compile(r"(?:InvalidMixinException|MixinApplyError|MixinTransformerError)"),
        "A mixin failed to apply — two mods likely patch the same target incompatibly.",
    ),
    (
        "missing_dependency",
        re.compile(r"requires (?:any |version )?.*?of (?:mod )?'?([\w.-]+)'?,? which is missing"),
        "A required dependency is missing.",
    ),
    (
        # Forge/NeoForge (FML) phrasing: a per-mod line under the missing-deps banner.
        "missing_dependency",
        re.compile(r"Mod ID: '([\w.-]+)',\s*Requested by:", re.IGNORECASE),
        "A required dependency is missing or the wrong version (Forge/NeoForge).",
    ),
    (
        "missing_dependency",
        re.compile(r"Missing or unsupported mandatory dependencies", re.IGNORECASE),
        "Required dependencies are missing or the wrong version (Forge/NeoForge).",
    ),
    (
        "duplicate_mod",
        re.compile(r"(?:Found )?[Dd]uplicate mod(?:s)?[:\s]+'?([\w.-]+)'?"),
        "The same mod id is provided by more than one jar.",
    ),
    (
        "incompatible_mod",
        re.compile(r"is incompatible with (?:mod )?'?([\w.-]+)'?", re.IGNORECASE),
        "Two mods declare each other incompatible.",
    ),
    (
        "recipe_error",
        re.compile(
            r"(?:Error (?:parsing|loading)|Failed to (?:parse|load)).{0,40}recipe", re.IGNORECASE
        ),
        "A recipe failed to deserialize — likely a recipe collision or format mismatch.",
    ),
]

# Generic dependency-resolution banner Fabric prints before the detail lines.
_FABRIC_RESOLUTION_RE = re.compile(
    r"(?:Incompatible mods found!|Could not (?:execute|resolve) .*dependenc"
    r"|ModResolutionException)",
    re.IGNORECASE,
)
_EXCEPTION_RE = re.compile(
    r"^\s*(?:Caused by:\s*)?([\w.]+(?:Exception|Error)): (.+)$", re.MULTILINE
)


def reached_done(latest_log: str) -> bool:
    """True if the server reached a clean start (registries frozen, world loaded)."""
    return bool(_DONE_RE.search(latest_log or ""))


def tail(text: str, lines: int = 30) -> str:
    """Last ``lines`` non-empty-ish lines of ``text``, for compact UI display."""
    rows = (text or "").rstrip().splitlines()
    return "\n".join(rows[-lines:])


def extract_cause(log_text: str, crash_report: str | None = None) -> RunCause:
    """Best-effort cause of a failed boot from the combined log text."""
    combined = "\n".join(filter(None, (log_text, crash_report)))

    for category, pattern, summary in _SIGNATURES:
        match = pattern.search(combined)
        if match is None:
            continue
        mods = [match.group(1)] if match.groups() and match.group(1) else []
        return RunCause(
            category=category,
            summary=summary,
            mods=mods,
            excerpt=_excerpt_around(combined, match.start()),
        )

    if _FABRIC_RESOLUTION_RE.search(combined):
        return RunCause(
            category="missing_dependency",
            summary="Fabric could not resolve the mod set (missing or incompatible dependency).",
            excerpt=tail(combined, 20),
        )

    exception = _EXCEPTION_RE.search(combined)
    if exception is not None:
        return RunCause(
            category="startup_error",
            summary=f"{exception.group(1)}: {exception.group(2).strip()}",
            excerpt=_excerpt_around(combined, exception.start()),
        )

    return RunCause(
        category="unknown",
        summary="Server stopped before a clean start, with no recognized cause.",
        excerpt=tail(combined, 20),
    )


def _excerpt_around(text: str, index: int, before: int = 1, after: int = 4) -> str:
    """A few log lines around ``index`` to show the offending context."""
    rows = text.splitlines()
    # locate the line containing the char offset
    offset = 0
    hit = 0
    for i, row in enumerate(rows):
        offset += len(row) + 1
        if offset > index:
            hit = i
            break
    start = max(0, hit - before)
    end = min(len(rows), hit + after + 1)
    return "\n".join(rows[start:end])
