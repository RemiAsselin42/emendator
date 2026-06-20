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


class ScanRequest(CamelModel):
    """Body of ``POST /mods/scan``: absolute path to a ``mods/`` folder."""

    path: str


class ScanResult(CamelModel):
    """Outcome of scanning a ``mods/`` folder (Phase 0 slice of the map)."""

    profile: str
    mods_path: str
    mods: list[Mod]
    untestable: list[UntestableMod]
    conflicts: list[Conflict]
    errors: list[ScanError]
    counts: ScanCounts


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
