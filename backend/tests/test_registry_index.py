"""Item/block registry index built from jar lang + item-model assets."""

import json
import zipfile
from pathlib import Path

from app.analyzer.registry_index import build_registry_index


def _jar(folder: Path, name: str, entries: dict[str, str]) -> Path:
    path = folder / name
    with zipfile.ZipFile(path, "w") as zf:
        for inner, content in entries.items():
            zf.writestr(inner, content)
    return path


def test_lang_keys_become_items_and_blocks(tmp_path: Path) -> None:
    _jar(
        tmp_path,
        "create.jar",
        {
            "assets/create/lang/en_us.json": json.dumps(
                {
                    "item.create.brass_ingot": "Brass Ingot",
                    "block.create.andesite_casing": "Andesite Casing",
                    "item.create.brass_ingot.tooltip": "shiny",  # extra segment → ignored
                    "itemGroup.create": "Create",  # not item./block. → ignored
                }
            )
        },
    )
    index = build_registry_index([tmp_path / "create.jar"])
    by_id = {e.id: e for e in index.items}
    assert by_id["create:brass_ingot"].display_name == "Brass Ingot"
    assert by_id["create:brass_ingot"].kind == "item"
    assert by_id["create:brass_ingot"].mod == "create"
    assert by_id["create:andesite_casing"].kind == "block"
    assert index.total == 2
    assert index.item_count == 1
    assert index.block_count == 1


def test_item_model_fills_gap_without_lang(tmp_path: Path) -> None:
    _jar(
        tmp_path,
        "tool.jar",
        {"assets/tool/models/item/wrench.json": json.dumps({"parent": "item/handheld"})},
    )
    index = build_registry_index([tmp_path / "tool.jar"])
    entry = index.items[0]
    assert entry.id == "tool:wrench"
    assert entry.display_name is None
    assert entry.kind == "item"


def test_lang_wins_over_model(tmp_path: Path) -> None:
    _jar(
        tmp_path,
        "m.jar",
        {
            "assets/m/lang/en_us.json": json.dumps({"item.m.gear": "Gear"}),
            "assets/m/models/item/gear.json": json.dumps({}),
        },
    )
    index = build_registry_index([tmp_path / "m.jar"])
    assert index.total == 1
    assert index.items[0].display_name == "Gear"


def test_block_models_are_not_counted(tmp_path: Path) -> None:
    # Block models (state variants) would over-count; only item models fill gaps.
    _jar(
        tmp_path,
        "b.jar",
        {"assets/b/models/block/stairs_inner.json": json.dumps({})},
    )
    index = build_registry_index([tmp_path / "b.jar"])
    assert index.total == 0


def test_dedup_across_jars(tmp_path: Path) -> None:
    _jar(tmp_path, "a.jar", {"assets/shared/lang/en_us.json": json.dumps({"item.shared.x": "X"})})
    _jar(tmp_path, "b.jar", {"assets/shared/models/item/x.json": json.dumps({})})
    index = build_registry_index(sorted(tmp_path.glob("*.jar")))
    assert index.total == 1
    assert index.items[0].display_name == "X"  # lang entry kept
