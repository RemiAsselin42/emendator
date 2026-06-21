"""Content-pack inventory + override detection (resource packs / datapacks)."""

import json
import zipfile
from pathlib import Path

from app.analyzer.packs import scan_datapacks, scan_resourcepacks, scan_shaderpacks


def _mcmeta(fmt: int, desc: str) -> str:
    return json.dumps({"pack": {"pack_format": fmt, "description": desc}})


def _dir_pack(root: Path, name: str, fmt: int, files: dict[str, str]) -> None:
    pack = root / name
    pack.mkdir(parents=True)
    (pack / "pack.mcmeta").write_text(_mcmeta(fmt, f"{name} desc"))
    for rel, content in files.items():
        target = pack / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)


def _zip_pack(root: Path, name: str, fmt: int, files: dict[str, str]) -> None:
    with zipfile.ZipFile(root / name, "w") as zf:
        zf.writestr("pack.mcmeta", _mcmeta(fmt, f"{name} desc"))
        for rel, content in files.items():
            zf.writestr(rel, content)


def test_resourcepack_inventory_and_meta(tmp_path: Path) -> None:
    _dir_pack(tmp_path, "PackA", 48, {"assets/minecraft/textures/block/stone.png": "x"})
    _zip_pack(tmp_path, "PackB.zip", 34, {"assets/minecraft/textures/item/apple.png": "y"})
    packs, conflicts = scan_resourcepacks(tmp_path)

    by_name = {p.name: p for p in packs}
    assert by_name["PackA"].pack_format == 48
    assert by_name["PackA"].source == "dir"
    assert by_name["PackA"].asset_count == 1
    assert by_name["PackB.zip"].source == "zip"
    assert conflicts == []  # no shared assets


def test_resourcepack_override_detected(tmp_path: Path) -> None:
    shared = "assets/minecraft/textures/block/stone.png"
    _dir_pack(tmp_path, "PackA", 48, {shared: "a"})
    _zip_pack(tmp_path, "PackB.zip", 48, {shared: "b"})
    _packs, conflicts = scan_resourcepacks(tmp_path)

    assert len(conflicts) == 1
    c = conflicts[0]
    assert c.type == "asset_override"
    assert c.severity == "info"
    assert c.members == ["PackA", "PackB.zip"]
    assert shared in c.detail["paths"]
    assert c.detail["count"] == 1


def test_datapack_override_across_world(tmp_path: Path) -> None:
    dp_dir = tmp_path / "saves" / "world" / "datapacks"
    dp_dir.mkdir(parents=True)
    recipe = "data/minecraft/recipe/torch.json"
    _dir_pack(dp_dir, "DpA", 48, {recipe: "{}"})
    _zip_pack(dp_dir, "DpB.zip", 48, {recipe: "{}"})
    packs, conflicts = scan_datapacks([str(dp_dir)])

    assert {p.name for p in packs} == {"DpA", "DpB.zip"}
    assert all(p.location == "world" for p in packs)
    assert len(conflicts) == 1
    assert conflicts[0].type == "datapack_override"
    assert conflicts[0].members == ["world/DpA", "world/DpB.zip"]


def test_shaderpacks_inventoried(tmp_path: Path) -> None:
    (tmp_path / "ComplementaryShaders").mkdir()
    (tmp_path / "BSL.zip").write_bytes(b"PK\x03\x04stub")
    shaders = scan_shaderpacks(tmp_path)
    assert {s.name for s in shaders} == {"ComplementaryShaders", "BSL.zip"}


def test_missing_folder_is_empty() -> None:
    assert scan_resourcepacks(None) == ([], [])
    assert scan_datapacks([]) == ([], [])
    assert scan_shaderpacks(None) == []
