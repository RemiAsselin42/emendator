"""Generate filter-mod configs — the fix ladder's second rung.

When the losing mixin has no mod-own toggle (:mod:`app.resolve.mixin_toggles`),
a dedicated filter mod can cancel it at load time. Schemas confirmed against
both mods' source (2026-07-06 spike):

- **Mixin Blacklist** (Fabric/Quilt, MixinSquared-based, wide 1.x window):
  ``config/mixinblacklist.json`` with ``client``/``common`` sections of
  ``mixinClassNames`` / ``targetClassNames``.
- **Mixin Helper** ((Neo)Forge + Fabric, MC 1.20.1 / 1.21.1 only):
  ``config/mixinhelper.json`` with ``blacklist.{mixins, mixinConfigs,
  targetClasses}`` and ``priorities.mixinConfigPriorities``. Its per-mixin
  ``priorities.mixinPriorities`` map is dead config upstream (declared, never
  read) — never generate it.

We blacklist by **mixin class name only**: the mod's own FQ dotted names are
never remapped, so they are correct on every loader with zero mapping work
(2.0 spike). Target-class blacklisting is coarser (kills every mixin of every
mod on that class) and stays out. Everything goes under ``common`` — a
client-section mixin simply never applies on a dedicated server, and Mixin
Blacklist checks its ``client`` list on the physical client anyway.

Pure functions, like :mod:`app.resolve.generate`. The filter mod itself must
be present for the config to act — callers install it via the existing
``/mods/install`` flow (both slugs resolve on Modrinth) and record the jar in
the apply manifest (Phase 2.5).
"""

import json
from dataclasses import dataclass

from app.models import GeneratedFile, Loader


@dataclass(frozen=True)
class FilterMod:
    """One installable mixin-filter mod and the window it supports."""

    slug: str  # Modrinth project slug (feeds /mods/install)
    name: str
    config_path: str
    loaders: frozenset[Loader]
    # Exact supported MC versions, or None = any 1.x (Mixin Blacklist's window
    # is 1.14–1.21.x; finer gating would need live Modrinth metadata).
    versions: frozenset[str] | None


MIXIN_BLACKLIST = FilterMod(
    slug="mixin-blacklist",
    name="Mixin Blacklist",
    config_path="config/mixinblacklist.json",
    loaders=frozenset({"fabric", "quilt"}),
    versions=None,
)

MIXIN_HELPER = FilterMod(
    slug="mixin-helper",
    name="Mixin Helper",
    config_path="config/mixinhelper.json",
    loaders=frozenset({"fabric", "forge", "neoforge"}),
    versions=frozenset({"1.20.1", "1.21.1"}),
)

# Preference order: the wider window first, so Fabric/Quilt land on Mixin
# Blacklist and (Neo)Forge falls through to Mixin Helper where supported.
_FILTER_MODS = (MIXIN_BLACKLIST, MIXIN_HELPER)


def pick_filter_mod(loader: Loader, version: str) -> FilterMod | None:
    """The filter mod covering this pack, or None (ladder falls through)."""
    for candidate in _FILTER_MODS:
        if loader not in candidate.loaders:
            continue
        if candidate.versions is None:
            if version.startswith("1."):
                return candidate
        elif version in candidate.versions:
            return candidate
    return None


def generate_filter_config(filter_mod: FilterMod, mixin_classes: set[str]) -> GeneratedFile | None:
    """The filter mod's config blacklisting exactly ``mixin_classes``."""
    if not mixin_classes:
        return None
    names = sorted(mixin_classes)
    if filter_mod is MIXIN_HELPER:
        config: dict = {
            "enabled": True,
            "blacklist": {"mixins": names, "mixinConfigs": [], "targetClasses": []},
        }
    else:
        config = {
            "client": {"mixinClassNames": [], "targetClassNames": []},
            "common": {"mixinClassNames": names, "targetClassNames": []},
        }
    return GeneratedFile(path=filter_mod.config_path, content=json.dumps(config, indent=2) + "\n")
