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

# Mod loader a jar targets, from the metadata file it ships (fabric.mod.json,
# quilt.mod.json, META-INF/(neoforge.)mods.toml). "unknown" = unrecognized jar.
Loader = Literal["fabric", "quilt", "forge", "neoforge", "unknown"]

# Conflict taxonomy (PROJECT.md §7, §9). The first five are mod conflicts; the
# last two are content-pack overrides (resource packs / datapacks).
ConflictType = Literal[
    "tag_overlap",
    "recipe_collision",
    "mixin_overlap",
    "dependency",
    "duplicate_jar",
    "asset_override",
    "datapack_override",
]
Severity = Literal["info", "warning", "error"]
DetectedBy = Literal["static", "runtime"]


class CamelModel(BaseModel):
    """Base model: snake_case in Python, camelCase on the wire."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class Mod(CamelModel):
    """One mod resolved from a jar's loader metadata (Fabric/Quilt/Forge/NeoForge)."""

    id: str
    name: str | None = None
    version: str | None = None
    mc_version: str | None = None
    environment: Environment = "*"
    loader: Loader = "unknown"
    depends: dict[str, str | list[str]] = {}
    provides: list[str] = []
    jar: str
    # Online enrichment (best-effort; null when not looked up / not found).
    provider: Literal["modrinth", "curseforge"] | None = None
    homepage: str | None = None
    latest_version: str | None = None
    update_available: bool | None = None


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
    # Which loader to boot (itzg TYPE); when absent it's detected from the jars.
    loader: Loader | None = None
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


# Which conflict families the no-code generator covers. The front drives them
# per resolution sub-tab (Tags / Recipes); omitting the list means "all".
ResolutionFamily = Literal["tags", "recipes"]


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
    # Restrict generation to these families (None = all). Lets the Tags and
    # Recipes sub-tabs each preview only their own artifact.
    families: list[ResolutionFamily] | None = None
    # Per-conflict winner picks from the selection cards (subject id -> mod id):
    # which mod's recipe wins a collision, which mod's item wins a tag. Absent
    # subjects fall back to the default (priority order).
    recipe_winners: dict[str, str] | None = None
    tag_winners: dict[str, str] | None = None


class ExportRequest(CamelModel):
    """Body of ``POST /resolve/export``: where to write the generated files."""

    path: str
    out_dir: str
    version: str | None = None
    mod_priorities: list[str] | None = None
    families: list[ResolutionFamily] | None = None
    recipe_winners: dict[str, str] | None = None
    tag_winners: dict[str, str] | None = None


class RecipeVariant(CamelModel):
    """One mod's own version of a contested recipe id (for the selection card)."""

    mod: str
    content: str  # the recipe JSON, pretty-printed, as the user would drop it in


class VariantsRequest(CamelModel):
    """Body of ``POST /resolve/variants``: the scanned ``mods/`` folder."""

    path: str
    version: str | None = None


class ResolutionVariants(CamelModel):
    """Per-conflict variants the user chooses between in the Resolution cards.

    ``recipes`` maps a colliding recipe id to each mod's version of it; tag
    variants already ride along in the scan's ``tag_overlap`` detail, so they are
    not duplicated here.
    """

    recipes: dict[str, list[RecipeVariant]] = {}


# --- Apply the resolution into the live instance (reversibly) ----------------

# Where the override datapack lands. "per_world" copies it into each existing
# world's datapacks/ (no dependency); "openloader" writes it under openloader/data/
# for global loading (needs the Open Loader mod).
ApplyTarget = Literal["per_world", "openloader"]


class ResolutionTargets(CamelModel):
    """What a pack can do with a resolution — drives the Apply UI before writing."""

    almost_unified: bool  # AU present -> tags via unify.json instead of a re-tag datapack
    open_loader: bool  # Open Loader present -> the global datapack target is available
    worlds: list[str] = []  # existing datapack dirs (global + per-world) found in the pack


class ApplyRequest(CamelModel):
    """Body of ``POST /resolve/apply``: write the resolution into the instance."""

    path: str  # the instance root (not the mods folder) — content folders are resolved from it
    version: str | None = None
    recipe_winners: dict[str, str] | None = None
    tag_winners: dict[str, str] | None = None
    target: ApplyTarget = "per_world"


# applied = files written; nothing = no resolvable conflicts; error = write failed.
ApplyStatus = Literal["applied", "nothing", "error"]


class ApplyResult(CamelModel):
    """Outcome of applying a resolution, with the manifest needed to revert it."""

    status: ApplyStatus
    written: list[str] = []  # absolute paths written
    targets: list[str] = []  # the datapack dirs / config dir written into
    manifest: str | None = None  # manifest file path (feed it back to /resolve/revert)
    almost_unified: bool = False  # whether tags went to unify.json (AU) vs the datapack
    open_loader: bool = False
    message: str | None = None


class RevertRequest(CamelModel):
    """Body of ``POST /resolve/revert``: undo a prior apply by its manifest."""

    manifest: str


class RevertResult(CamelModel):
    """Outcome of reverting an apply (the written files removed)."""

    status: Literal["reverted", "not_found", "error"]
    removed: list[str] = []
    message: str | None = None


class ExportResult(CamelModel):
    """Absolute paths written by an export."""

    out_dir: str
    written: list[str] = []


# --- In-place mod update (download the latest version) --------------------

# updated = jar replaced; no_update = already latest; not_found = no provider
# match; error = something went wrong (no change made).
UpdateStatus = Literal["updated", "no_update", "not_found", "error"]


class UpdateRequest(CamelModel):
    """Body of ``POST /mods/update``: update one jar in a mods folder."""

    path: str  # the mods folder containing the jar
    jar: str  # current jar filename
    version: str | None = None  # exact MC version to match (else detected)
    loader: Loader | None = None  # loader to match (else detected)


class UpdateResult(CamelModel):
    """Outcome of an in-place mod update."""

    status: UpdateStatus
    old_jar: str | None = None
    new_jar: str | None = None
    version: str | None = None  # the version number installed
    message: str | None = None


# --- Install a missing dependency (the runner flags it; we fetch it) ---------

# installed = jar fetched and added; not_found = no provider match (or a platform
# pseudo-dependency); error = something went wrong (no change made).
InstallStatus = Literal["installed", "not_found", "error"]


class InstallRequest(CamelModel):
    """Body of ``POST /mods/install``: install a missing dependency by its mod id."""

    path: str  # the mods folder to install into
    mod_id: str  # the dependency id the runner reported missing
    version: str | None = None  # exact MC version to match (else detected)
    loader: Loader | None = None  # loader to match (else detected)


class ProviderLink(CamelModel):
    """A direct link to a dependency's project page on a provider (for not_found)."""

    provider: Literal["modrinth", "curseforge"]
    title: str
    url: str | None = None


class InstallResult(CamelModel):
    """Outcome of installing a missing dependency into a mods folder."""

    status: InstallStatus
    mod_id: str
    jar: str | None = None  # the filename that was written
    version: str | None = None  # the version number installed
    message: str | None = None
    # On not_found: direct project links for the providers where the dependency
    # exists but has no build for the pack's loader + MC version. Empty when it
    # was found nowhere — the front then offers a manual search instead.
    links: list[ProviderLink] = []


# --- CurseForge connection (UI-entered API key for the install fallback) -----


class CurseForgeKeyRequest(CamelModel):
    """Body of ``POST /config/curseforge``: the user-entered API key (blank clears)."""

    api_key: str


class CurseForgeStatus(CamelModel):
    """Whether a CurseForge key is configured (and, right after a set, if it verified).

    ``valid`` is ``None`` when not probed (the GET status) or when there's no key;
    otherwise it reflects whether the key authenticated against the CurseForge API.
    ``detail`` carries the human-readable reason when a probe failed (rejected key
    vs. unreachable API), so the front can show exactly what went wrong.
    """

    configured: bool
    valid: bool | None = None
    detail: str | None = None


# --- Disable / enable a mod (reversible sideline, never a delete) ------------

# disabled = jar suffixed `.disabled` in place; enabled = the suffix stripped;
# not_found = jar absent; error = the rename failed (no change made).
DisableStatus = Literal["disabled", "enabled", "not_found", "error"]


class DisableRequest(CamelModel):
    """Body of ``POST /mods/disable`` and ``/mods/enable``: one jar in a folder.

    ``disable`` renames ``mods/<jar>`` to ``mods/<jar>.disabled`` in place; ``enable``
    strips the suffix. Reversible by design — when two mods incompatibly patch the
    same mixin target and no compatible update exists, Emendator sidelines the loser
    rather than deleting it, so the choice can always be undone.
    """

    path: str  # the mods folder
    jar: str  # the active jar filename (the `.disabled` suffix is added/removed internally)


class DisableResult(CamelModel):
    """Outcome of disabling/enabling a mod (the reversible jar move)."""

    status: DisableStatus
    jar: str | None = None
    message: str | None = None


# --- Instances (launcher-native ingestion) -------------------------------

# Where the dropped folder comes from. "raw_mods" = a bare mods/ folder (the
# historical input); the others are launcher instances we recognise by their
# manifest and whose content sub-folders we locate automatically.
InstanceSource = Literal["curseforge", "modrinth", "prism", "multimc", "vanilla", "raw_mods"]


class InstanceFolders(CamelModel):
    """Resolved absolute paths of the content sub-folders found in an instance.

    Each is ``None`` when the instance has no such folder; ``datapacks`` holds
    every datapack directory found (a global ``datapacks/`` plus each world's
    ``saves/<world>/datapacks``).
    """

    mods: str | None = None
    resourcepacks: str | None = None
    config: str | None = None
    datapacks: list[str] = []


class Instance(CamelModel):
    """A launcher instance (or bare mods folder) resolved from a dropped path.

    Carries the launcher-declared metadata (name, loader, MC version) when a
    manifest is present, plus the located content folders and quick counts so the
    front can summarise the pack before a full scan.
    """

    root: str
    source: InstanceSource
    name: str | None = None
    loader: Loader = "unknown"
    mc_version: str | None = None
    folders: InstanceFolders = InstanceFolders()
    mod_count: int = 0
    resourcepack_count: int = 0
    datapack_count: int = 0


# --- Content packs beyond mods (resource packs / datapacks) ---------------


class ResourcePack(CamelModel):
    """A resource pack (texture pack): a ``.zip`` or folder with ``pack.mcmeta``."""

    name: str
    pack_format: int | None = None
    description: str | None = None
    asset_count: int = 0
    source: Literal["zip", "dir"] = "dir"


class Datapack(CamelModel):
    """A datapack found in a global ``datapacks/`` or a world's ``datapacks/``."""

    name: str
    location: str  # the containing world (or instance) name, for display
    pack_format: int | None = None
    description: str | None = None
    data_count: int = 0
    source: Literal["zip", "dir"] = "dir"


# --- Registry index (items/blocks the pack adds) -------------------------


class ItemEntry(CamelModel):
    """One registered item or block, from a jar's lang/model assets."""

    id: str  # "namespace:name"
    display_name: str | None = None  # from lang en_us.json when available
    kind: Literal["item", "block"] = "item"
    mod: str  # owning namespace (≈ the mod id)


class RegistryIndex(CamelModel):
    """The aggregate of items/blocks every mod in the set registers.

    Approximate by design: built from ``lang``/``models`` assets, so items
    registered purely in code without a lang key or item model are not captured
    (documented in the UI). Good enough to browse what a pack adds.
    """

    items: list[ItemEntry] = []
    total: int = 0
    item_count: int = 0
    block_count: int = 0


class InstanceReport(CamelModel):
    """Full analysis of an instance: the mod conflict map plus everything else.

    ``mods`` is the same :class:`ScanResult` ``/mods/scan`` returns; the other
    sections cover the content folders located by instance detection.
    """

    instance: Instance
    mods: ScanResult
    resourcepacks: list[ResourcePack] = []
    datapacks: list[Datapack] = []
    resourcepack_conflicts: list[Conflict] = []
    datapack_conflicts: list[Conflict] = []
    items: RegistryIndex = RegistryIndex()
