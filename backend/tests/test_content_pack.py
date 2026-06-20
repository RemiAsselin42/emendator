"""End-to-end check on a synthetic-but-real content pack.

The Fabulously Optimized pack is optimization-only (no content mods), so it
produces no tag_overlap / recipe_collision. This builds real jars that do, and
runs the full pipeline scan -> conflict map -> resolution plan -> export, so the
Phase 1 detectors and Phase 4 generators are covered on real data (offline).
"""

import json
import zipfile
from pathlib import Path

from app.analyzer.mods import scan_mods_folder
from app.profile import get_profile
from app.resolve.generate import UNIFY_PATH, build_resolution_plan, export_plan


def _jar(mods: Path, name: str, meta: dict, data: dict | None = None) -> None:
    with zipfile.ZipFile(mods / name, "w") as archive:
        archive.writestr("fabric.mod.json", json.dumps(meta))
        for path, content in (data or {}).items():
            archive.writestr(path, json.dumps(content))


def _build_content_pack(mods: Path) -> None:
    _jar(mods, "fabric-api.jar", {"id": "fabric-api", "version": "1"})
    # Two mods add tin to the same conventional tag -> tag_overlap.
    _jar(
        mods,
        "tinmod.jar",
        {"id": "tinmod", "version": "1", "depends": {"minecraft": "1.21.1", "fabric-api": "*"}},
        {"data/c/tags/items/ingots/tin.json": {"values": ["tinmod:tin_ingot"]}},
    )
    _jar(
        mods,
        "moretin.jar",
        {"id": "moretin", "version": "1", "depends": {"minecraft": "1.21.1"}},
        {"data/c/tags/items/ingots/tin.json": {"values": ["moretin:tin_ingot"]}},
    )
    # Two mods override the same vanilla recipe id -> recipe_collision.
    _jar(
        mods,
        "recipea.jar",
        {"id": "recipea", "version": "1", "depends": {"minecraft": "1.21.1"}},
        {"data/minecraft/recipe/torch.json": {"type": "minecraft:crafting_shaped"}},
    )
    _jar(
        mods,
        "recipeb.jar",
        {"id": "recipeb", "version": "1", "depends": {"minecraft": "1.21.1"}},
        {"data/minecraft/recipe/torch.json": {"type": "minecraft:crafting_shaped"}},
    )


def test_content_pack_detection_and_resolution(tmp_path: Path) -> None:
    mods = tmp_path / "mods"
    mods.mkdir()
    _build_content_pack(mods)

    scan = scan_mods_folder(mods, "1.21.1")
    types = {c.type for c in scan.conflicts}
    assert "tag_overlap" in types
    assert "recipe_collision" in types
    assert scan.counts.errors == 0

    plan = build_resolution_plan(get_profile("1.21.1"), scan.conflicts)
    paths = {file.path for file in plan.files}
    assert UNIFY_PATH in paths
    assert "emendator-overrides/pack.mcmeta" in paths

    out = tmp_path / "out"
    export_plan(plan, out)
    unify = json.loads((out / UNIFY_PATH).read_text())
    assert unify["tags"] == ["c:ingots/tin"]
    assert "minecraft" in unify["modPriorities"]
