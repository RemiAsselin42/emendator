"""Generate no-code resolution artifacts from the conflict map (§10, §12).

- ``tag_overlap`` (content duplication) -> an **Almost Unified** ``unify.json``
  listing the affected ``c:`` tags and a mod-priority order (first mod wins).
  This is the DoD path: a duplication conflict resolved by a generated file.
- ``recipe_collision`` -> a recipe-override **datapack** scaffold (``pack.mcmeta``
  + a manifest of colliding recipe ids) the user drops the winning recipe into.

All functions are pure (conflicts -> file artifacts); writing to disk is
:func:`export_plan`.
"""

import json
from pathlib import Path
from typing import Any

from app.models import Conflict, GeneratedFile, ResolutionFamily, ResolutionPlan
from app.profile import VersionProfile

UNIFY_PATH = "config/almostunified/unify.json"
DATAPACK_ROOT = "emendator-overrides"


def _unify_default_priorities(tag_overlaps: list[Conflict]) -> list[str]:
    """Default winner order: vanilla first, then the involved mods, sorted."""
    mods = sorted({member for c in tag_overlaps for member in c.members})
    return ["minecraft", *mods]


def generate_unify_json(
    tag_overlaps: list[Conflict],
    mod_priorities: list[str],
    tag_winners: dict[str, str] | None = None,
) -> GeneratedFile | None:
    """Almost Unified config unifying the overlapping ``c:`` tags.

    ``tag_winners`` (tag id -> winning mod) records the per-tag canonical pick from
    the selection cards as a ``priorityOverrides`` map; tags left unset fall back to
    the global ``modPriorities`` order.
    """
    if not tag_overlaps:
        return None
    tags = sorted({str(c.detail["tag"]) for c in tag_overlaps if c.detail.get("tag")})
    config: dict[str, Any] = {"modPriorities": mod_priorities, "tags": tags}
    overrides = {tag: tag_winners[tag] for tag in tags if tag_winners and tag in tag_winners}
    if overrides:
        config["priorityOverrides"] = overrides
    return GeneratedFile(path=UNIFY_PATH, content=json.dumps(config, indent=2) + "\n")


def _recipe_segment(profile: VersionProfile) -> str:
    """Last path segment of the profile's recipe path (``recipe`` / ``recipes``)."""
    return profile.recipe_path.rstrip("/").split("/")[-1]


def pack_mcmeta(profile: VersionProfile) -> GeneratedFile:
    """The ``pack.mcmeta`` for the override datapack (version-appropriate format)."""
    mcmeta = {
        "pack": {
            "pack_format": profile.datapack_format,
            "description": f"Emendator overrides ({profile.profile})",
        }
    }
    return GeneratedFile(
        path=f"{DATAPACK_ROOT}/pack.mcmeta", content=json.dumps(mcmeta, indent=2) + "\n"
    )


def generate_recipe_datapack(
    recipe_collisions: list[Conflict],
    profile: VersionProfile,
    recipe_bodies: dict[str, str] | None = None,
) -> list[GeneratedFile]:
    """An override datapack for recipe collisions.

    Always emits ``pack.mcmeta`` + a README manifest. When ``recipe_bodies`` (recipe
    id -> winning JSON, from the chosen variant) is given, it also writes each
    winning recipe at its data path so the pack is functional, not a scaffold.
    """
    if not recipe_collisions:
        return []

    bodies = recipe_bodies or {}
    segment = _recipe_segment(profile)
    lines = [
        "# Recipe override datapack",
        "",
        "Each recipe id below is defined by more than one mod; this datapack loads",
        "last and wins. The winning recipe JSON is written at the listed path when a",
        "winner is chosen; otherwise drop the one you want in yourself.",
        "",
    ]
    files: list[GeneratedFile] = [pack_mcmeta(profile)]
    for conflict in sorted(recipe_collisions, key=lambda c: str(c.detail.get("recipe", ""))):
        recipe_id = str(conflict.detail.get("recipe", ""))
        namespace, _, rel = recipe_id.partition(":")
        rel_path = f"data/{namespace}/{segment}/{rel}.json"
        members = ", ".join(conflict.members)
        lines.append(f"- `{recipe_id}` (from {members}) -> {rel_path}")
        body = bodies.get(recipe_id)
        if body:
            files.append(GeneratedFile(path=f"{DATAPACK_ROOT}/{rel_path}", content=body))

    files.append(GeneratedFile(path=f"{DATAPACK_ROOT}/README.md", content="\n".join(lines) + "\n"))
    return files


def generate_tag_datapack(
    tag_overlaps: list[Conflict], tag_winners: dict[str, str] | None = None
) -> list[GeneratedFile]:
    """Re-tag datapack files: the dependency-free fallback to Almost Unified.

    Each conflicting conventional tag is rewritten to hold **only** the winning
    mod's items (``{"replace": true, "values": [...]}``), so recipes/automation
    that pull from the tag resolve to one canonical item. Tag paths are
    version-independent (tags are always plural: ``data/<ns>/tags/items/<rel>``).
    The winner defaults to the first mod alphabetically — the cards' default.
    """
    winners = tag_winners or {}
    files: list[GeneratedFile] = []
    for conflict in sorted(tag_overlaps, key=lambda c: str(c.detail.get("tag", ""))):
        tag_id = str(conflict.detail.get("tag", ""))
        by_mod = conflict.detail.get("byMod")
        if not tag_id or not isinstance(by_mod, dict) or not by_mod:
            continue
        winner = winners.get(tag_id)
        if winner not in by_mod:
            winner = sorted(by_mod)[0]
        raw = by_mod.get(winner, [])
        items = sorted(str(i) for i in raw) if isinstance(raw, list) else []
        namespace, _, rel = tag_id.partition(":")
        content = json.dumps({"replace": True, "values": items}, indent=2) + "\n"
        files.append(
            GeneratedFile(
                path=f"{DATAPACK_ROOT}/data/{namespace}/tags/items/{rel}.json", content=content
            )
        )
    return files


def assemble_override_datapack(
    profile: VersionProfile,
    recipe_collisions: list[Conflict],
    tag_overlaps: list[Conflict],
    *,
    recipe_bodies: dict[str, str] | None = None,
    tag_winners: dict[str, str] | None = None,
) -> list[GeneratedFile]:
    """One ``emendator-overrides/`` datapack: recipe winners + tag re-tags.

    Pass ``tag_overlaps=[]`` when Almost Unified handles tags via ``unify.json``.
    Returns ``[]`` when there is nothing to write; otherwise always carries a
    ``pack.mcmeta`` (recipe-only, tags-only, or both).
    """
    recipe_files = generate_recipe_datapack(recipe_collisions, profile, recipe_bodies)
    tag_files = generate_tag_datapack(tag_overlaps, tag_winners)
    if not recipe_files and not tag_files:
        return []
    # generate_recipe_datapack already prepends pack.mcmeta; a tags-only pack needs its own.
    head: list[GeneratedFile] = [] if recipe_files else [pack_mcmeta(profile)]
    return head + recipe_files + tag_files


def build_resolution_plan(
    profile: VersionProfile,
    conflicts: list[Conflict],
    mod_priorities: list[str] | None = None,
    families: list[ResolutionFamily] | None = None,
    *,
    recipe_bodies: dict[str, str] | None = None,
    tag_winners: dict[str, str] | None = None,
) -> ResolutionPlan:
    """Assemble the resolution artifacts for the requested families (default: all).

    ``recipe_bodies`` (winning recipe JSON per id) and ``tag_winners`` carry the
    per-conflict picks from the selection cards; without them the plan keeps its
    priority-order defaults.
    """
    want = set(families) if families is not None else {"tags", "recipes"}
    tag_overlaps = [c for c in conflicts if c.type == "tag_overlap"] if "tags" in want else []
    recipe_collisions = (
        [c for c in conflicts if c.type == "recipe_collision"] if "recipes" in want else []
    )
    priorities = mod_priorities or _unify_default_priorities(tag_overlaps)

    files: list[GeneratedFile] = []
    unify = generate_unify_json(tag_overlaps, priorities, tag_winners)
    if unify is not None:
        files.append(unify)
    files.extend(generate_recipe_datapack(recipe_collisions, profile, recipe_bodies))

    if files:
        summary = (
            f"{len(tag_overlaps)} tag overlap(s) -> unify.json; "
            f"{len(recipe_collisions)} recipe collision(s) -> override datapack."
        )
    else:
        summary = "No resolvable conflicts (tag_overlap / recipe_collision) found."

    return ResolutionPlan(
        profile=profile.profile,
        files=files,
        summary=summary,
        mod_priorities=priorities if tag_overlaps else [],
    )


def export_plan(plan: ResolutionPlan, out_dir: Path) -> list[str]:
    """Write the plan's files under ``out_dir``; return the absolute paths."""
    written: list[str] = []
    for file in plan.files:
        target = out_dir / file.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(file.content, encoding="utf-8")
        written.append(str(target))
    return written
