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

from app.models import Conflict, GeneratedFile, ResolutionFamily, ResolutionPlan
from app.profile import VersionProfile

UNIFY_PATH = "config/almostunified/unify.json"
DATAPACK_ROOT = "emendator-overrides"


def _unify_default_priorities(tag_overlaps: list[Conflict]) -> list[str]:
    """Default winner order: vanilla first, then the involved mods, sorted."""
    mods = sorted({member for c in tag_overlaps for member in c.members})
    return ["minecraft", *mods]


def generate_unify_json(
    tag_overlaps: list[Conflict], mod_priorities: list[str]
) -> GeneratedFile | None:
    """Almost Unified config unifying the overlapping ``c:`` tags."""
    if not tag_overlaps:
        return None
    tags = sorted({str(c.detail["tag"]) for c in tag_overlaps if c.detail.get("tag")})
    config = {"modPriorities": mod_priorities, "tags": tags}
    return GeneratedFile(path=UNIFY_PATH, content=json.dumps(config, indent=2) + "\n")


def _recipe_segment(profile: VersionProfile) -> str:
    """Last path segment of the profile's recipe path (``recipe`` / ``recipes``)."""
    return profile.recipe_path.rstrip("/").split("/")[-1]


def generate_recipe_datapack(
    recipe_collisions: list[Conflict], profile: VersionProfile
) -> list[GeneratedFile]:
    """A datapack scaffold (``pack.mcmeta`` + manifest) for recipe collisions."""
    if not recipe_collisions:
        return []

    mcmeta = {
        "pack": {
            "pack_format": profile.datapack_format,
            "description": f"Emendator recipe overrides ({profile.profile})",
        }
    }
    segment = _recipe_segment(profile)
    lines = [
        "# Recipe override datapack",
        "",
        "Each recipe id below is defined by more than one mod; the datapack with",
        "the highest priority wins. Drop the winning recipe JSON at the listed",
        "path to override the others.",
        "",
    ]
    for conflict in sorted(recipe_collisions, key=lambda c: str(c.detail.get("recipe", ""))):
        recipe_id = str(conflict.detail.get("recipe", ""))
        namespace, _, rel = recipe_id.partition(":")
        members = ", ".join(conflict.members)
        lines.append(f"- `{recipe_id}` (from {members}) -> data/{namespace}/{segment}/{rel}.json")

    return [
        GeneratedFile(
            path=f"{DATAPACK_ROOT}/pack.mcmeta",
            content=json.dumps(mcmeta, indent=2) + "\n",
        ),
        GeneratedFile(path=f"{DATAPACK_ROOT}/README.md", content="\n".join(lines) + "\n"),
    ]


def build_resolution_plan(
    profile: VersionProfile,
    conflicts: list[Conflict],
    mod_priorities: list[str] | None = None,
    families: list[ResolutionFamily] | None = None,
) -> ResolutionPlan:
    """Assemble the resolution artifacts for the requested families (default: all)."""
    want = set(families) if families is not None else {"tags", "recipes"}
    tag_overlaps = [c for c in conflicts if c.type == "tag_overlap"] if "tags" in want else []
    recipe_collisions = (
        [c for c in conflicts if c.type == "recipe_collision"] if "recipes" in want else []
    )
    priorities = mod_priorities or _unify_default_priorities(tag_overlaps)

    files: list[GeneratedFile] = []
    unify = generate_unify_json(tag_overlaps, priorities)
    if unify is not None:
        files.append(unify)
    files.extend(generate_recipe_datapack(recipe_collisions, profile))

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
