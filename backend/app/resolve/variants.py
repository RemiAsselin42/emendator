"""Per-conflict recipe variants: each mod's own version of a contested recipe id.

The Resolution selection cards let the user pick which mod wins a recipe collision;
to choose meaningfully they need to see each variant. Tag variants already ride
along in the scan (the items each mod feeds the tag), so only recipe bodies are
read here — from each contributing jar, reusing the recipes the scan parses into
the :class:`JarIndex`. :func:`recipe_winner_bodies` then resolves the chosen (or
default) winner per id, so the generator can write real recipe JSON.
"""

import json
from collections import defaultdict
from pathlib import Path

from app.analyzer.detectors import _recipe_id_from_path
from app.analyzer.mods import build_jar_index
from app.models import RecipeVariant
from app.profile import VersionProfile


def _recipe_bodies(folder: Path, profile: VersionProfile) -> dict[str, dict[str, str]]:
    """``recipe id -> {mod id -> pretty JSON}`` for every recipe each jar defines."""
    by_id: dict[str, dict[str, str]] = defaultdict(dict)
    for jar in sorted(folder.glob("*.jar")):
        index, _error = build_jar_index(jar, profile)
        if index is None:
            continue
        for path, body in index.recipes.items():
            recipe_id = _recipe_id_from_path(path)
            if recipe_id is not None:
                by_id[recipe_id][index.mod.id] = json.dumps(body, indent=2) + "\n"
    return by_id


def collect_recipe_variants(
    folder: Path, profile: VersionProfile
) -> dict[str, list[RecipeVariant]]:
    """Colliding recipe ids (defined by ≥2 mods) → each mod's version, sorted by mod."""
    by_id = _recipe_bodies(folder, profile)
    return {
        recipe_id: [RecipeVariant(mod=mod, content=by_mod[mod]) for mod in sorted(by_mod)]
        for recipe_id, by_mod in by_id.items()
        if len(by_mod) > 1
    }


def recipe_winner_bodies(
    folder: Path, profile: VersionProfile, recipe_winners: dict[str, str] | None
) -> dict[str, str]:
    """For each colliding recipe id, the chosen (or default) winner's JSON body.

    The default winner is the first mod id alphabetically among the collision's
    members — the same rule the datapack generator's manifest implies — so a plan
    built with no explicit pick is deterministic and matches the cards' default.
    """
    winners = recipe_winners or {}
    bodies: dict[str, str] = {}
    for recipe_id, options in collect_recipe_variants(folder, profile).items():
        by_mod = {variant.mod: variant.content for variant in options}
        chosen = winners.get(recipe_id)
        if chosen not in by_mod:
            chosen = sorted(by_mod)[0]
        bodies[recipe_id] = by_mod[chosen]
    return bodies
