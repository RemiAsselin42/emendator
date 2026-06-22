import json
import zipfile
from pathlib import Path

import pytest

from app.models import Conflict
from app.profile import get_profile
from app.resolve.generate import (
    UNIFY_PATH,
    build_resolution_plan,
    export_plan,
    generate_recipe_datapack,
    generate_unify_json,
)
from app.resolve.variants import collect_recipe_variants, recipe_winner_bodies

PROFILE = get_profile("1.21.1")
RECIPE_SEGMENT = PROFILE.recipe_path.rstrip("/").split("/")[-1]


def _recipe_jar(folder: Path, name: str, mod_id: str, body: dict) -> None:
    """A minimal jar declaring ``mod_id`` and shipping one ``farmersdelight`` recipe."""
    with zipfile.ZipFile(folder / name, "w") as zf:
        zf.writestr("fabric.mod.json", json.dumps({"id": mod_id, "version": "1.0"}))
        zf.writestr(f"data/farmersdelight/{RECIPE_SEGMENT}/fried_rice.json", json.dumps(body))


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


@pytest.mark.parametrize(
    ("families", "want_unify", "want_datapack"),
    [(["tags"], True, False), (["recipes"], False, True)],
)
def test_build_plan_families_filter(
    families: list[str], want_unify: bool, want_datapack: bool
) -> None:
    conflicts = [
        _tag_overlap("c:ingots/tin", ["a", "b"]),
        _recipe_collision("minecraft:torch", ["a", "b"]),
    ]
    plan = build_resolution_plan(PROFILE, conflicts, families=families)  # type: ignore[arg-type]
    paths = {f.path for f in plan.files}
    assert (UNIFY_PATH in paths) is want_unify
    assert any(p.startswith("emendator-overrides/") for p in paths) is want_datapack


def test_build_plan_empty_when_no_resolvable_conflicts() -> None:
    plan = build_resolution_plan(
        PROFILE, [Conflict(type="mixin_overlap", severity="info", members=["a", "b"])]
    )
    assert plan.files == []
    assert "No resolvable conflicts" in plan.summary


def test_unify_json_encodes_tag_winners() -> None:
    file = generate_unify_json(
        [_tag_overlap("c:crops/tomato", ["croptopia", "farmersdelight"])],
        ["minecraft", "croptopia", "farmersdelight"],
        {"c:crops/tomato": "croptopia"},
    )
    assert file is not None
    config = json.loads(file.content)
    assert config["priorityOverrides"] == {"c:crops/tomato": "croptopia"}


def test_recipe_datapack_writes_winning_body() -> None:
    body = '{"type": "minecraft:crafting_shapeless"}\n'
    files = generate_recipe_datapack(
        [_recipe_collision("farmersdelight:cooking/fried_rice", ["a", "b"])],
        PROFILE,
        {"farmersdelight:cooking/fried_rice": body},
    )
    by_path = {f.path: f.content for f in files}
    written = f"emendator-overrides/data/farmersdelight/{RECIPE_SEGMENT}/cooking/fried_rice.json"
    assert by_path[written] == body


def test_collect_variants_and_resolve_winner(tmp_path: Path) -> None:
    _recipe_jar(tmp_path, "amod.jar", "amod", {"result": "A"})
    _recipe_jar(tmp_path, "bmod.jar", "bmod", {"result": "B"})

    variants = collect_recipe_variants(tmp_path, PROFILE)
    assert {v.mod for v in variants["farmersdelight:fried_rice"]} == {"amod", "bmod"}

    # No pick → default winner is the first mod id alphabetically (amod).
    default = recipe_winner_bodies(tmp_path, PROFILE, None)
    assert '"result": "A"' in default["farmersdelight:fried_rice"]

    # Explicit pick wins.
    chosen = recipe_winner_bodies(tmp_path, PROFILE, {"farmersdelight:fried_rice": "bmod"})
    assert '"result": "B"' in chosen["farmersdelight:fried_rice"]


def test_export_plan_writes_files(tmp_path: Path) -> None:
    plan = build_resolution_plan(PROFILE, [_tag_overlap("c:ingots/tin", ["a", "b"])])
    written = export_plan(plan, tmp_path)
    assert written
    unify = tmp_path / UNIFY_PATH
    assert unify.is_file()
    assert json.loads(unify.read_text())["tags"] == ["c:ingots/tin"]
