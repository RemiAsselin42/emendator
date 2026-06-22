import json
from pathlib import Path

from app.models import Conflict
from app.profile import get_profile
from app.resolve.generate import (
    UNIFY_PATH,
    build_resolution_plan,
    export_plan,
    generate_recipe_datapack,
    generate_unify_json,
)

PROFILE = get_profile("1.21.1")


def _tag_overlap(tag: str, members: list[str]) -> Conflict:
    return Conflict(type="tag_overlap", severity="info", members=members, detail={"tag": tag})


def _recipe_collision(recipe: str, members: list[str]) -> Conflict:
    return Conflict(
        type="recipe_collision", severity="warning", members=members, detail={"recipe": recipe}
    )


def test_generate_unify_json_collects_tags_and_priorities() -> None:
    conflicts = [
        _tag_overlap("c:ingots/tin", ["moda", "modb"]),
        _tag_overlap("c:gems/ruby", ["modb", "modc"]),
    ]
    file = generate_unify_json(conflicts, ["minecraft", "moda", "modb", "modc"])
    assert file is not None
    assert file.path == UNIFY_PATH
    config = json.loads(file.content)
    assert config["tags"] == ["c:gems/ruby", "c:ingots/tin"]
    assert config["modPriorities"] == ["minecraft", "moda", "modb", "modc"]


def test_generate_unify_json_none_without_overlaps() -> None:
    assert generate_unify_json([], ["minecraft"]) is None


def test_recipe_datapack_has_mcmeta_and_manifest() -> None:
    files = generate_recipe_datapack([_recipe_collision("minecraft:torch", ["a", "b"])], PROFILE)
    by_path = {f.path: f.content for f in files}
    mcmeta = json.loads(by_path["emendator-overrides/pack.mcmeta"])
    assert mcmeta["pack"]["pack_format"] == 48  # from the profile
    assert "minecraft:torch" in by_path["emendator-overrides/README.md"]
    assert "data/minecraft/recipe/torch.json" in by_path["emendator-overrides/README.md"]


def test_build_plan_default_priorities_and_summary() -> None:
    conflicts = [
        _tag_overlap("c:ingots/tin", ["zmod", "amod"]),
        _recipe_collision("minecraft:torch", ["a", "b"]),
    ]
    plan = build_resolution_plan(PROFILE, conflicts)
    assert plan.mod_priorities == ["minecraft", "amod", "zmod"]  # vanilla first, then sorted
    paths = {f.path for f in plan.files}
    assert UNIFY_PATH in paths
    assert "emendator-overrides/pack.mcmeta" in paths
    assert "tag overlap" in plan.summary


def test_build_plan_families_tags_only_skips_recipes() -> None:
    conflicts = [
        _tag_overlap("c:ingots/tin", ["a", "b"]),
        _recipe_collision("minecraft:torch", ["a", "b"]),
    ]
    plan = build_resolution_plan(PROFILE, conflicts, families=["tags"])
    paths = {f.path for f in plan.files}
    assert UNIFY_PATH in paths
    assert not any(p.startswith("emendator-overrides/") for p in paths)


def test_build_plan_families_recipes_only_skips_tags() -> None:
    conflicts = [
        _tag_overlap("c:ingots/tin", ["a", "b"]),
        _recipe_collision("minecraft:torch", ["a", "b"]),
    ]
    plan = build_resolution_plan(PROFILE, conflicts, families=["recipes"])
    paths = {f.path for f in plan.files}
    assert UNIFY_PATH not in paths
    assert "emendator-overrides/pack.mcmeta" in paths


def test_build_plan_empty_when_no_resolvable_conflicts() -> None:
    plan = build_resolution_plan(
        PROFILE, [Conflict(type="mixin_overlap", severity="info", members=["a", "b"])]
    )
    assert plan.files == []
    assert "No resolvable conflicts" in plan.summary


def test_export_plan_writes_files(tmp_path: Path) -> None:
    plan = build_resolution_plan(PROFILE, [_tag_overlap("c:ingots/tin", ["a", "b"])])
    written = export_plan(plan, tmp_path)
    assert written
    unify = tmp_path / UNIFY_PATH
    assert unify.is_file()
    assert json.loads(unify.read_text())["tags"] == ["c:ingots/tin"]
