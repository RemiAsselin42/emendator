"""Data contracts shared across the analyzer, the runner and the front.

The shapes here implement the **conflict map** (PROJECT.md §9) and the
**version profile** (§6). Phase 0 only populates the `mods` / `untestable`
slices; later phases add `conflicts` on top of the same models.

JSON is emitted in camelCase (matching §9: ``mcVersion``, ``detectedBy``) while
Python keeps snake_case attributes — the alias generator bridges the two.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

# environment as declared in fabric.mod.json; "*" means both sides.
Environment = Literal["server", "client", "*"]

# Conflict taxonomy (PROJECT.md §7, §9).
ConflictType = Literal[
    "tag_overlap",
    "recipe_collision",
    "mixin_overlap",
    "dependency",
    "duplicate_jar",
]
Severity = Literal["info", "warning", "error"]
DetectedBy = Literal["static", "runtime"]


class CamelModel(BaseModel):
    """Base model: snake_case in Python, camelCase on the wire."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class Mod(CamelModel):
    """One Fabric mod resolved from a jar's ``fabric.mod.json``."""

    id: str
    name: str | None = None
    version: str | None = None
    mc_version: str | None = None
    environment: Environment = "*"
    depends: dict[str, str | list[str]] = {}
    provides: list[str] = []
    jar: str


class UntestableMod(CamelModel):
    """A mod the server boot cannot exercise (e.g. ``environment:client``)."""

    id: str
    reason: str


class ScanError(CamelModel):
    """A jar that could not be parsed (not Fabric, corrupt, missing id…)."""

    jar: str
    reason: str


class Conflict(CamelModel):
    """One detected conflict (PROJECT.md §9).

    ``detail`` is type-specific (e.g. ``{"tag": "c:tin_ingots", "items": [...]}``)
    and ``resolution`` is filled by the generator in Phase 4.
    """

    type: ConflictType
    severity: Severity
    detected_by: DetectedBy = "static"
    members: list[str]
    detail: dict[str, Any] = {}
    resolution: dict[str, Any] | None = None


class ScanCounts(CamelModel):
    """Summary counts surfaced directly in the UI."""

    total: int
    mods: int
    testable: int
    untestable: int
    errors: int
    conflicts: int


# --- Version detection (PROJECT.md §6) -----------------------------------

# "confident" => the block is unambiguous and the front auto-scans; "ambiguous"
# => the constraints span incompatible blocks (or none constrain), so the user
# must pick a version before scanning.
DetectionStatus = Literal["confident", "ambiguous"]


class VersionCandidate(CamelModel):
    """One version block the mod set could plausibly target (for the picker)."""

    version: str  # representative exact version of the block (runner default)
    block: str  # block id, e.g. "1.21–1.21.1"
    mod_count: int  # constraining mods compatible with this block


class VersionDetection(CamelModel):
    """What automatic Minecraft-version detection concluded for a ``mods/`` set."""

    detected_version: str | None  # the version the whole set provably runs on
    block: str | None  # block id of ``detected_version``
    jdk: str | None  # JDK the runner needs for that block
    status: DetectionStatus
    confidence: float  # share of constraining mods compatible with the pick (0..1)
    candidates: list[VersionCandidate] = []
    outliers: list[str] = []  # mod ids incompatible with the chosen version
    runner_supported: bool = True  # False where runner artifacts aren't available yet


class ScanRequest(CamelModel):
    """Body of ``POST /mods/scan``: a ``mods/`` folder, plus an optional version.

    ``version`` overrides auto-detection (the user's manual pick); when absent the
    backend detects and refuses to guess on an ambiguous set (HTTP 409).
    """

    path: str
    version: str | None = None


class ScanResult(CamelModel):
    """Outcome of scanning a ``mods/`` folder (Phase 0 slice of the map)."""

    profile: str  # the exact version actually used for this scan
    mods_path: str
    mods: list[Mod]
    untestable: list[UntestableMod]
    conflicts: list[Conflict]
    errors: list[ScanError]
    counts: ScanCounts
    # Filled by the API layer (scan_mods_folder itself is profile-only).
    detection: VersionDetection | None = None


# --- Phase 2: headless runner (PROJECT.md §8) ----------------------------

# Terminal outcome of a boot attempt. "error" = harness/Docker failure, not a
# verdict on the mod set.
RunStatus = Literal["ok", "crash", "timeout", "error"]

# Runtime crash categories, parsed from the server log / crash report.
CrashCategory = Literal[
    "mixin_apply",
    "missing_dependency",
    "incompatible_mod",
    "duplicate_mod",
    "recipe_error",
    "startup_error",
    "unknown",
]


class RunCause(CamelModel):
    """Extracted explanation of why a boot failed."""

    category: CrashCategory
    summary: str
    mods: list[str] = []
    excerpt: str | None = None


class RunRequest(CamelModel):
    """Body of ``POST /runner/test``: the ``mods/`` folder to boot as a set."""

    path: str
    # Exact version to boot (itzg VERSION); when absent the backend auto-detects.
    version: str | None = None
    # Optional per-run overrides (defaults come from the version profile).
    timeout_seconds: int = 300
    memory: str = "3G"


class RunVerdict(CamelModel):
    """Result of booting a mod set in a headless Fabric server container."""

    status: RunStatus
    profile: str
    duration_ms: int
    cause: RunCause | None = None
    # Classes the loader actually transformed (mixin debug export) — the
    # ground truth that confirms or refutes static mixin_overlap candidates (§7).
    mixin_exports: list[str] = []
    log_tail: str | None = None


# Outcome of automated bisection (PROJECT.md §10, Phase 3).
BisectStatus = Literal["isolated", "no_conflict", "inconclusive", "error"]


class BisectResult(CamelModel):
    """The minimal guilty set isolated by delta-debugging a crashing boot."""

    status: BisectStatus
    profile: str
    members: list[str] = []
    cause: RunCause | None = None
    boots: int = 0
    duration_ms: int = 0
    note: str | None = None


# --- Phase 4: no-code resolution (PROJECT.md §10, §12) -------------------


class GeneratedFile(CamelModel):
    """A single artifact to preview or write (relative path + text content)."""

    path: str
    content: str


class ResolutionPlan(CamelModel):
    """The set of config/datapack files that resolve the resolvable conflicts."""

    profile: str
    files: list[GeneratedFile] = []
    summary: str
    # The mod priority order used for unification (first wins); editable.
    mod_priorities: list[str] = []


class ResolveRequest(CamelModel):
    """Body of ``POST /resolve/preview``: the scanned ``mods/`` folder."""

    path: str
    version: str | None = None
    mod_priorities: list[str] | None = None


class ExportRequest(CamelModel):
    """Body of ``POST /resolve/export``: where to write the generated files."""

    path: str
    out_dir: str
    version: str | None = None
    mod_priorities: list[str] | None = None


class ExportResult(CamelModel):
    """Absolute paths written by an export."""

    out_dir: str
    written: list[str] = []
