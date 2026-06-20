"""Static conflict detectors (PROJECT.md §7).

Each detector is a pure function over the already-built :class:`JarIndex` list
(no I/O — ``mods.py`` did the unzipping) plus the :class:`VersionProfile`, and
returns :class:`Conflict` objects for the unified conflict map (§9).

All detectors are heuristics that triage statically; load-time categories
(recipes, mixins) are *confirmed* by the runner in Phase 2. Detail payloads are
kept JSON-serializable (sets flattened to sorted lists).
"""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from app.models import Conflict, Mod
from app.profile import VersionProfile

# Dependency ids provided by the runtime itself, never shipped as a mod jar.
_ENV_PROVIDED = {"minecraft", "java", "fabricloader", "fabric-loader"}


@dataclass
class JarIndex:
    """Everything the detectors need from one jar, read once by ``mods.py``."""

    jar: str
    mod: Mod
    sha256: str
    recipes: dict[str, dict[str, Any]] = field(default_factory=dict)
    item_tags: dict[str, dict[str, Any]] = field(default_factory=dict)
    mixin_targets: set[str] = field(default_factory=set)
    # "<target class>#<method>" pairs from injector annotations (method-level).
    mixin_method_targets: set[str] = field(default_factory=set)
    # Mod ids (and their `provides`) shipped as nested jars inside this jar.
    bundled_ids: set[str] = field(default_factory=set)


def detect_conflicts(indexes: list[JarIndex], profile: VersionProfile) -> list[Conflict]:
    """Run every detector and concatenate, sorted error → warning → info."""
    conflicts = [
        *detect_duplicate_jars(indexes),
        *detect_missing_dependencies(indexes),
        *detect_tag_overlaps(indexes, profile),
        *detect_recipe_collisions(indexes, profile),
        *detect_mixin_overlaps(indexes),
    ]
    order = {"error": 0, "warning": 1, "info": 2}
    conflicts.sort(key=lambda c: (order[c.severity], c.type, c.members))
    return conflicts


def detect_duplicate_jars(indexes: list[JarIndex]) -> list[Conflict]:
    """Same mod id declared by more than one jar — the loader refuses to start."""
    by_id: dict[str, list[JarIndex]] = defaultdict(list)
    for index in indexes:
        by_id[index.mod.id].append(index)
    conflicts: list[Conflict] = []
    for mod_id, group in by_id.items():
        if len(group) > 1:
            conflicts.append(
                Conflict(
                    type="duplicate_jar",
                    severity="error",
                    members=[mod_id],
                    detail={"modId": mod_id, "jars": sorted(g.jar for g in group)},
                )
            )
    return conflicts


def detect_missing_dependencies(indexes: list[JarIndex]) -> list[Conflict]:
    """A hard ``depends`` whose id is neither present nor environment-provided."""
    present: set[str] = set(_ENV_PROVIDED)
    for index in indexes:
        present.add(index.mod.id)
        present.update(index.mod.provides)
        present.update(index.bundled_ids)  # ids shipped as nested jars

    conflicts: list[Conflict] = []
    for index in indexes:
        for dep_id in index.mod.depends:
            if dep_id not in present:
                conflicts.append(
                    Conflict(
                        type="dependency",
                        severity="error",
                        members=[index.mod.id],
                        detail={"mod": index.mod.id, "missing": dep_id},
                    )
                )
    return conflicts


def _tag_values(tag_json: dict[str, Any]) -> list[str]:
    """Item ids from a tag file's ``values`` (str or ``{"id": ...}`` entries)."""
    values = tag_json.get("values")
    if not isinstance(values, list):
        return []
    items: list[str] = []
    for entry in values:
        if isinstance(entry, str):
            items.append(entry)
        elif isinstance(entry, dict) and isinstance(entry.get("id"), str):
            items.append(entry["id"])
    return items


def detect_tag_overlaps(indexes: list[JarIndex], profile: VersionProfile) -> list[Conflict]:
    """≥2 mods feeding the same conventional (``c:``) item tag = content dup."""
    # tag id -> {mod id -> contributed item ids}
    by_tag: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for index in indexes:
        for path, tag_json in index.item_tags.items():
            tag_id = _tag_id_from_path(path, profile)
            if tag_id is None:
                continue
            by_tag[tag_id][index.mod.id].update(_tag_values(tag_json))

    conflicts: list[Conflict] = []
    for tag_id, by_mod in by_tag.items():
        if len(by_mod) < 2:
            continue
        items = sorted({item for items in by_mod.values() for item in items})
        conflicts.append(
            Conflict(
                type="tag_overlap",
                severity="info",
                members=sorted(by_mod),
                detail={
                    "tag": tag_id,
                    "items": items,
                    "byMod": {mod: sorted(v) for mod, v in by_mod.items()},
                },
            )
        )
    return conflicts


def _tag_id_from_path(path: str, profile: VersionProfile) -> str | None:
    """``data/c/tags/items/ingots/tin.json`` -> ``c:ingots/tin`` (conventional only)."""
    parts = path.split("/")
    # data / <namespace> / tags / items / <rel...>.json
    if len(parts) < 6 or parts[0] != "data" or parts[2] != "tags" or parts[3] != "items":
        return None
    namespace = parts[1]
    if namespace != profile.tag_namespace:
        return None
    rel = "/".join(parts[4:])
    if rel.endswith(".json"):
        rel = rel[: -len(".json")]
    return f"{namespace}:{rel}"


def detect_recipe_collisions(indexes: list[JarIndex], profile: VersionProfile) -> list[Conflict]:
    """Same recipe id written by ≥2 mods — one silently overrides the other."""
    by_recipe: dict[str, set[str]] = defaultdict(set)
    for index in indexes:
        for path in index.recipes:
            recipe_id = _recipe_id_from_path(path)
            if recipe_id is not None:
                by_recipe[recipe_id].add(index.mod.id)

    conflicts: list[Conflict] = []
    for recipe_id, mods in by_recipe.items():
        if len(mods) > 1:
            conflicts.append(
                Conflict(
                    type="recipe_collision",
                    severity="warning",
                    members=sorted(mods),
                    detail={"recipe": recipe_id},
                )
            )
    return conflicts


def _recipe_id_from_path(path: str) -> str | None:
    """``data/mymod/recipe/foo.json`` -> ``mymod:foo``."""
    parts = path.split("/")
    if len(parts) < 4 or parts[0] != "data":
        return None
    namespace = parts[1]
    rel = "/".join(parts[3:])  # skip data/<ns>/<recipe-segment>/
    if rel.endswith(".json"):
        rel = rel[: -len(".json")]
    return f"{namespace}:{rel}"


def detect_mixin_overlaps(indexes: list[JarIndex]) -> list[Conflict]:
    """≥2 mods whose mixins target the same class.

    Class-level overlap alone is coarse — many mods co-patch a vanilla class
    (e.g. MinecraftClient) harmlessly — so it stays ``info``. But when the mods
    also patch the **same method** of that class (from injector ``method``
    targets) the conflict is far more likely, so it is raised to ``warning`` and
    the shared methods are listed. The target stays class-level so the runtime
    mixin export (§7) can still confirm it. Names are intermediary
    (``net.minecraft.class_310``) in distributed jars but match across mods.
    """
    by_class: dict[str, set[str]] = defaultdict(set)
    by_class_method: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for index in indexes:
        for target in index.mixin_targets:
            by_class[target].add(index.mod.id)
        for pair in index.mixin_method_targets:
            target, _, method = pair.partition("#")
            by_class_method[target][method].add(index.mod.id)

    conflicts: list[Conflict] = []
    for target, mods in by_class.items():
        if len(mods) < 2:
            continue
        shared_methods = sorted(
            method for method, owners in by_class_method[target].items() if len(owners) > 1
        )
        detail: dict[str, Any] = {"target": target}
        if shared_methods:
            detail["sharedMethods"] = shared_methods
        conflicts.append(
            Conflict(
                type="mixin_overlap",
                severity="warning" if shared_methods else "info",
                members=sorted(mods),
                detail=detail,
            )
        )
    return conflicts
