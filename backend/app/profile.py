"""Version profiles (PROJECT.md §6).

Version-dependent constants are **never hardcoded** in the analyzer; they live
here and are consumed by both the static analyzer (Phase 1) and the runner
(Phase 2). Adding a new Minecraft block = adding a profile, not rewriting logic.
"""

from typing import Literal

from app.models import CamelModel


class VersionProfile(CamelModel):
    """Constants that decouple the tool's logic from a Minecraft version."""

    profile: str
    jdk: str
    item_format: Literal["components", "nbt"]
    datapack_folders: Literal["singular", "plural"]
    # Path templates; "{mod}" is the datapack namespace folder (a wildcard at
    # scan time). The recipe folder is singular in 1.21+, plural before.
    recipe_path: str
    tag_path: str
    tag_namespace: str
    fabric_api: str
    datapack_format: int  # pack_format for generated datapacks (1.21–1.21.1 = 48)

    def recipe_glob(self) -> str:
        """Glob (relative to a jar root) matching every recipe JSON."""
        return f"{self.recipe_path.replace('{mod}', '*')}/**/*.json"

    def tag_items_glob(self) -> str:
        """Glob (relative to a jar root) matching every item-tag JSON."""
        return f"{self.tag_path.replace('{mod}', '*')}/**/*.json"


# MVP target. See the block table in PROJECT.md §6.
_PROFILES: dict[str, VersionProfile] = {
    "1.21.1": VersionProfile(
        profile="1.21.1",
        jdk="21",
        item_format="components",
        datapack_folders="singular",
        recipe_path="data/{mod}/recipe",
        tag_path="data/{mod}/tags/items",
        tag_namespace="c",
        fabric_api="0.116.11+1.21.1",
        datapack_format=48,
    ),
}


def get_profile(name: str) -> VersionProfile:
    """Resolve a profile by name, or raise ``KeyError`` if unknown."""
    return _PROFILES[name]


def available_profiles() -> list[str]:
    """Names of the profiles bundled with this build."""
    return sorted(_PROFILES)
