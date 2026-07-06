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

from app.analyzer.mixin_targets import DEFAULT_PRIORITY, INSTRUCTION_EXCLUSIVE_KINDS
from app.models import Conflict, Mod
from app.profile import VersionProfile

# Dependency ids provided by the runtime/loader itself, never shipped as a mod
# jar (across loaders: Fabric, Quilt, Forge, NeoForge).
_ENV_PROVIDED = {
    "minecraft",
    "java",
    "fabricloader",
    "fabric-loader",
    "quilt_loader",
    "forge",
    "neoforge",
    "fml",
    "javafml",
}

# Conventional tag namespaces shared across loaders ("c" since 1.21 and on
# Fabric; "forge" on older Forge). Tag overlaps only matter in these.
_CONVENTIONAL_NAMESPACES = frozenset({"c", "forge"})


@dataclass
class MixinMethodPatch:
    """How one jar's mixins patch a single ``Class#method`` target."""

    # Injector kinds hitting the method ("inject", "redirect", "overwrite", ...).
    kinds: set[str] = field(default_factory=set)
    # ``@At`` target selectors used by instruction-exclusive kinds — lets the
    # detector tell "same call site" from "same method, different instruction".
    exclusive_at: set[str] = field(default_factory=set)
    # Effective priorities (@Mixin priority, else config priority, else 1000)
    # of the mixin classes patching this method.
    priorities: set[int] = field(default_factory=set)
    # True when a contributing config declares ``required`` (or a positive
    # ``injectors.defaultRequire``): a failed application then crashes the boot
    # instead of logging and limping on.
    required: bool = False
    # Dotted FQ names of the mixin classes doing the patching — the handle a
    # precise fix needs (toggle key lookup, filter-config generation).
    mixin_classes: set[str] = field(default_factory=set)

    def merge(self, other: "MixinMethodPatch") -> None:
        self.kinds |= other.kinds
        self.exclusive_at |= other.exclusive_at
        self.priorities |= other.priorities
        self.required = self.required or other.required
        self.mixin_classes |= other.mixin_classes


@dataclass
class MixinToggleSystem:
    """A mod's own per-mixin kill switch (CaffeineMC-style properties / Debugify).

    The officially tolerated no-code compat path: a config file the mod itself
    reads to skip applying individual mixins. ``keys`` maps each togglable
    mixin class (dotted FQ) to its option key — ``mixin.<subpackage>`` for the
    CaffeineMC family (per-package granularity), ``MC-<bug id>`` for Debugify.
    """

    kind: str  # "properties" | "debugify"
    file: str  # instance-relative config path, e.g. "config/lithium.properties"
    keys: dict[str, str] = field(default_factory=dict)


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
    # "<target class>#<method>" -> how this jar's mixins patch it.
    mixin_method_patches: dict[str, MixinMethodPatch] = field(default_factory=dict)
    # The mod's own per-mixin kill-switch config, when it ships one.
    mixin_toggles: MixinToggleSystem | None = None
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
    """≥2 mods feeding the same conventional (``c:``/``forge:``) item tag = content dup."""
    # Accept every conventional namespace, not just the profile's default, so a
    # mixed-loader pack (Fabric `c:` + older Forge `forge:`) isn't missed.
    namespaces = _CONVENTIONAL_NAMESPACES | {profile.tag_namespace}
    # tag id -> {mod id -> contributed item ids}
    by_tag: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for index in indexes:
        for path, tag_json in index.item_tags.items():
            tag_id = _tag_id_from_path(path, namespaces)
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


def _tag_id_from_path(path: str, namespaces: frozenset[str] | set[str]) -> str | None:
    """``data/c/tags/items/ingots/tin.json`` -> ``c:ingots/tin`` (conventional only)."""
    parts = path.split("/")
    # data / <namespace> / tags / items / <rel...>.json
    if len(parts) < 6 or parts[0] != "data" or parts[2] != "tags" or parts[3] != "items":
        return None
    namespace = parts[1]
    if namespace not in namespaces:
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
    """≥2 mods whose mixins target the same class, graded by how they patch it.

    Class-level overlap alone is coarse — many mods co-patch a vanilla class
    (e.g. MinecraftClient) harmlessly — so it stays ``info``. Mods patching the
    **same method** of that class raise it to ``warning`` with the shared
    methods listed. When the per-method patch info proves the combination
    cannot coexist — two ``@Overwrite`` at the same priority (Mixin hard-fails)
    or two instruction-exclusive injectors (``@Redirect``/``@ModifyConstant``)
    on the same call site — it escalates to ``error``, with the reasoning in
    ``detail.methodDetails``. The target stays class-level so the runtime
    mixin export (§7) can still confirm it. Names are intermediary
    (``net.minecraft.class_310``) in distributed jars but match across mods.
    """
    by_class: dict[str, set[str]] = defaultdict(set)
    by_class_method: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    # "Class#method" -> mod id -> merged patch info across that mod's jars.
    patches: dict[str, dict[str, MixinMethodPatch]] = defaultdict(dict)
    for index in indexes:
        for target in index.mixin_targets:
            by_class[target].add(index.mod.id)
        for pair in index.mixin_method_targets:
            target, _, method = pair.partition("#")
            by_class_method[target][method].add(index.mod.id)
        for key, patch in index.mixin_method_patches.items():
            slot = patches[key].setdefault(index.mod.id, MixinMethodPatch())
            slot.merge(patch)

    conflicts: list[Conflict] = []
    for target, mods in by_class.items():
        if len(mods) < 2:
            continue
        shared_methods = sorted(
            method for method, owners in by_class_method[target].items() if len(owners) > 1
        )
        severity = "warning" if shared_methods else "info"
        detail: dict[str, Any] = {"target": target}
        if shared_methods:
            detail["sharedMethods"] = shared_methods
            method_details, hard = _shared_method_details(target, shared_methods, patches)
            if method_details:
                detail["methodDetails"] = method_details
            if hard:
                severity = "error"
        conflicts.append(
            Conflict(
                type="mixin_overlap",
                severity=severity,
                members=sorted(mods),
                detail=detail,
            )
        )
    return conflicts


def _shared_method_details(
    target: str,
    shared_methods: list[str],
    patches: dict[str, dict[str, MixinMethodPatch]],
) -> tuple[dict[str, Any], bool]:
    """Per shared method: who patches it how, and whether that is a hard conflict.

    Hard = the combination cannot coexist at runtime: ≥2 mods ``@Overwrite``
    the method with a colliding (or default) priority — Mixin refuses to merge
    the second one — or ≥2 mods use an instruction-exclusive injector on the
    same call site (or one we could not attribute to a site). Distinct
    overwrite priorities mean the highest silently wins: real but survivable,
    so the conflict stays ``warning`` grade.
    """
    details: dict[str, Any] = {}
    hard = False
    for method in shared_methods:
        by_mod = patches.get(f"{target}#{method}", {})
        if len(by_mod) < 2:
            continue
        entry: dict[str, Any] = {
            "kinds": {mod: sorted(patch.kinds) for mod, patch in sorted(by_mod.items())}
        }
        mixin_classes = {
            mod: sorted(patch.mixin_classes)
            for mod, patch in sorted(by_mod.items())
            if patch.mixin_classes
        }
        if mixin_classes:
            # The concrete handle a precise fix targets (toggle/filter configs).
            entry["mixinClasses"] = mixin_classes
        # Fatal-vs-silent signal: a failed application only crashes the boot
        # for mods whose config is `required`; the others break silently.
        required_by = sorted(mod for mod, patch in by_mod.items() if patch.required)
        if required_by:
            entry["requiredBy"] = required_by

        overwriters = sorted(mod for mod, patch in by_mod.items() if "overwrite" in patch.kinds)
        if len(overwriters) >= 2:
            entry["overwrites"] = overwriters
            entry["priorities"] = {
                mod: sorted(by_mod[mod].priorities or {DEFAULT_PRIORITY}) for mod in overwriters
            }
            claimed: set[int] = set()
            for mod in overwriters:
                mod_priorities = by_mod[mod].priorities or {DEFAULT_PRIORITY}
                if claimed & mod_priorities:
                    hard = True
                claimed |= mod_priorities

        exclusive = sorted(
            mod for mod, patch in by_mod.items() if patch.kinds & INSTRUCTION_EXCLUSIVE_KINDS
        )
        if len(exclusive) >= 2:
            entry["exclusive"] = exclusive
            at_sets = [by_mod[mod].exclusive_at for mod in exclusive]
            known = [s for s in at_sets if s]
            unknown_site = len(known) < len(at_sets)
            same_site = any(a & b for i, a in enumerate(known) for b in known[i + 1 :])
            if unknown_site or same_site:
                hard = True

        details[method] = entry
    return details, hard
