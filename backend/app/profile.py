"""Version profiles and version-block detection (PROJECT.md §6).

Version-dependent constants are **never hardcoded** in the analyzer; they live
here, grouped into *blocks* (ranges of Minecraft versions that share parsing
constants and a JDK). A :class:`VersionProfile` is *resolved* from a concrete
version: the exact version string (fed to the runner as itzg ``VERSION``) plus
the constants of the block that version falls in.

:func:`detect_version` turns the mods' ``depends.minecraft`` constraints into a
concrete target — the block where most mods cluster, then the newest in-block
floor — refusing to guess when the set spans incompatible blocks.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from app.models import CamelModel, VersionCandidate, VersionDetection
from app.version import Constraint, McVersion, parse_constraint


class VersionProfile(CamelModel):
    """Constants that decouple the tool's logic from a Minecraft version."""

    profile: str  # the exact resolved version (e.g. "1.21.5") — runner VERSION
    jdk: str
    item_format: Literal["components", "nbt"]
    datapack_folders: Literal["singular", "plural"]
    # Path templates; "{mod}" is the datapack namespace folder (a wildcard at
    # scan time). The recipe folder is singular in 1.21+, plural before.
    recipe_path: str
    tag_path: str
    tag_namespace: str
    datapack_format: int  # pack_format for generated datapacks
    runner_supported: bool = True

    def recipe_glob(self) -> str:
        """Glob (relative to a jar root) matching every recipe JSON."""
        return f"{self.recipe_path.replace('{mod}', '*')}/**/*.json"

    def tag_items_glob(self) -> str:
        """Glob (relative to a jar root) matching every item-tag JSON."""
        return f"{self.tag_path.replace('{mod}', '*')}/**/*.json"


@dataclass(frozen=True)
class Block:
    """A range of Minecraft versions sharing parsing constants and a JDK."""

    id: str
    low: McVersion
    high: McVersion  # inclusive upper bound of the block
    jdk: str
    item_format: Literal["components", "nbt"]
    datapack_folders: Literal["singular", "plural"]
    recipe_path: str
    tag_path: str
    tag_namespace: str
    datapack_format: int
    # Real releases inside the block, ascending; last = runner default / rep.
    known: tuple[McVersion, ...]
    runner_supported: bool = True

    def representative(self) -> McVersion:
        return self.known[-1]

    def contains(self, v: McVersion) -> bool:
        return self.low <= v <= self.high


def _v(text: str) -> McVersion:
    return McVersion.parse(text)


# The five blocks of PROJECT.md §6, ascending. tag_path stays plural everywhere
# (tags are always plural); only recipe_path flips singular/plural at 1.21.
_BLOCKS: tuple[Block, ...] = (
    Block(
        id="1.18–1.20.4",
        low=_v("1.18"),
        high=_v("1.20.4"),
        jdk="17",
        item_format="nbt",
        datapack_folders="plural",
        recipe_path="data/{mod}/recipes",
        tag_path="data/{mod}/tags/items",
        tag_namespace="c",
        datapack_format=26,
        known=(_v("1.18"), _v("1.18.2"), _v("1.19.2"), _v("1.19.4"), _v("1.20.1"), _v("1.20.4")),
    ),
    Block(
        id="1.20.5–1.20.6",
        low=_v("1.20.5"),
        high=_v("1.20.6"),
        jdk="21",
        item_format="components",
        datapack_folders="plural",
        recipe_path="data/{mod}/recipes",
        tag_path="data/{mod}/tags/items",
        tag_namespace="c",
        datapack_format=41,
        known=(_v("1.20.5"), _v("1.20.6")),
    ),
    Block(
        id="1.21–1.21.1",
        low=_v("1.21"),
        high=_v("1.21.1"),
        jdk="21",
        item_format="components",
        datapack_folders="singular",
        recipe_path="data/{mod}/recipe",
        tag_path="data/{mod}/tags/items",
        tag_namespace="c",
        datapack_format=48,
        known=(_v("1.21"), _v("1.21.1")),
    ),
    Block(
        id="1.21.2+",
        low=_v("1.21.2"),
        high=_v("1.21.999"),
        jdk="21",
        item_format="components",
        datapack_folders="singular",
        recipe_path="data/{mod}/recipe",
        tag_path="data/{mod}/tags/items",
        tag_namespace="c",
        datapack_format=57,
        known=(_v("1.21.2"), _v("1.21.4"), _v("1.21.5"), _v("1.21.6"), _v("1.21.8")),
    ),
    Block(
        id="26.1+",
        low=_v("26.1"),
        high=McVersion(9998, 0, 0),
        jdk="25",
        item_format="components",
        datapack_folders="singular",
        recipe_path="data/{mod}/recipe",
        tag_path="data/{mod}/tags/items",
        tag_namespace="c",
        datapack_format=88,
        known=(_v("26.1"),),
        # Bleeding edge: itzg java25 image / MC 26.x server may not exist yet, so
        # the runner is gated here until the artifacts are published (static is fine).
        runner_supported=False,
    ),
)


def block_of(version: McVersion) -> Block | None:
    """The block ``version`` falls in, or ``None`` if below the oldest block."""
    for block in _BLOCKS:
        if block.contains(version):
            return block
    return None


def resolve_profile(version: str) -> VersionProfile:
    """Build the :class:`VersionProfile` for a concrete version, via its block."""
    parsed = McVersion.parse(version)
    block = block_of(parsed)
    if block is None:
        raise KeyError(f"no version block for {version!r}")
    return VersionProfile(
        profile=str(parsed),
        jdk=block.jdk,
        item_format=block.item_format,
        datapack_folders=block.datapack_folders,
        recipe_path=block.recipe_path,
        tag_path=block.tag_path,
        tag_namespace=block.tag_namespace,
        datapack_format=block.datapack_format,
        runner_supported=block.runner_supported,
    )


def get_profile(name: str) -> VersionProfile:
    """Resolve a profile by exact version (kept for the runner/back-compat callers)."""
    return resolve_profile(name)


def available_profiles() -> list[VersionCandidate]:
    """The blocks offered in the manual-override picker (representative versions)."""
    return [
        VersionCandidate(version=str(b.representative()), block=b.id, mod_count=0) for b in _BLOCKS
    ]


def detect_version(
    constraints: Sequence[tuple[str, object]], forced: str | None = None
) -> VersionDetection:
    """Derive the target version from each mod's ``depends.minecraft``.

    The target is the version *block* where the most mods' floors cluster (a
    stray newer mod can't drag the set up), then the newest in-block floor as the
    exact version. Detection is ``confident`` only when ≥90% of the constraining
    mods can run that version; otherwise the set spans incompatible blocks and
    the caller must ask the user to pick.

    ``forced`` short-circuits the heuristic with the user's manual pick: the
    result then reflects *that* version's block (and which mods it leaves
    behind), so downstream gating (e.g. runtime support) matches what is used.
    """
    parsed = [(mod_id, parse_constraint(raw)) for mod_id, raw in constraints]
    constraining = [(mod_id, c) for mod_id, c in parsed if not c.is_any and c.ranges]

    if forced is not None:
        return _forced_detection(forced, constraining)

    # Fall back to every block when nothing constrains, so the picker has options.
    candidates = _block_candidates(constraining) or available_profiles()

    if not constraining:
        return VersionDetection(
            detected_version=None,
            block=None,
            jdk=None,
            status="ambiguous",
            confidence=0.0,
            candidates=candidates,
            outliers=[],
        )

    # The pack targets the version *block* where the most mods' floors cluster —
    # not the single highest floor. A stray newer mod (or an open-ended ">="
    # library that technically also runs on a much later version) must not drag a
    # whole 1.19.2 pack up to 1.21. Within the winning block, the exact version is
    # the newest floor the in-block mods need (so the runner boots that).
    floors = [(mod_id, c.floor()) for mod_id, c in constraining]
    votes = Counter(b.id for _, floor in floors if (b := block_of(floor)) is not None)
    if not votes:
        return VersionDetection(
            detected_version=None,
            block=None,
            jdk=None,
            status="ambiguous",
            confidence=0.0,
            candidates=candidates,
            outliers=[],
        )
    top = max(votes.values())
    block = next(b for b in reversed(_BLOCKS) if votes.get(b.id, 0) == top)  # newest on ties
    in_block = [floor for _, floor in floors if block.contains(floor)]
    detected = max(in_block) if in_block else block.low
    compatible = [mod_id for mod_id, c in constraining if c.contains(detected)]
    outliers = [mod_id for mod_id, c in constraining if not c.contains(detected)]
    confidence = len(compatible) / len(constraining)
    status: Literal["confident", "ambiguous"] = "confident" if confidence >= 0.9 else "ambiguous"
    return VersionDetection(
        detected_version=str(detected),
        block=block.id,
        jdk=block.jdk,
        status=status,
        confidence=round(confidence, 3),
        candidates=candidates,
        outliers=sorted(outliers),
        runner_supported=block.runner_supported,
    )


def _forced_detection(forced: str, constraining: list[tuple[str, Constraint]]) -> VersionDetection:
    """Detection reflecting an explicit user-picked version (its block, outliers)."""
    parsed = McVersion.parse(forced)
    block = block_of(parsed)
    if block is None:
        raise KeyError(f"no version block for {forced!r}")
    outliers = [mod_id for mod_id, c in constraining if not c.contains(parsed)]
    confidence = (len(constraining) - len(outliers)) / len(constraining) if constraining else 1.0
    return VersionDetection(
        detected_version=str(parsed),
        block=block.id,
        jdk=block.jdk,
        status="confident",
        confidence=round(confidence, 3),
        candidates=_block_candidates(constraining) or available_profiles(),
        outliers=sorted(outliers),
        runner_supported=block.runner_supported,
    )


def _block_candidates(constraining: list[tuple[str, Constraint]]) -> list[VersionCandidate]:
    """Per-block tally of constraining mods whose range overlaps that block (picker)."""
    out: list[VersionCandidate] = []
    for block in _BLOCKS:
        count = sum(1 for _, c in constraining if c.intersects(block.low, block.high))
        if count:
            out.append(
                VersionCandidate(
                    version=str(block.representative()), block=block.id, mod_count=count
                )
            )
    out.sort(key=lambda candidate: candidate.mod_count, reverse=True)
    return out
