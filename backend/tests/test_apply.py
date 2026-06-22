import json
import zipfile
from pathlib import Path

from app.profile import get_profile
from app.resolve.apply import apply_resolution, resolution_targets, revert_resolution

PROFILE = get_profile("1.21.1")
SEG = PROFILE.recipe_path.rstrip("/").split("/")[-1]


def _mod_jar(mods: Path, name: str, mod_id: str, result: str, tag_item: str) -> None:
    """A jar colliding on `farmersdelight:fried_rice` and feeding `c:crops/tomato`."""
    with zipfile.ZipFile(mods / name, "w") as zf:
        zf.writestr("fabric.mod.json", json.dumps({"id": mod_id, "version": "1.0"}))
        zf.writestr(f"data/farmersdelight/{SEG}/fried_rice.json", json.dumps({"result": result}))
        zf.writestr("data/c/tags/items/crops/tomato.json", json.dumps({"values": [tag_item]}))


def _plain_jar(mods: Path, name: str, mod_id: str) -> None:
    with zipfile.ZipFile(mods / name, "w") as zf:
        zf.writestr("fabric.mod.json", json.dumps({"id": mod_id, "version": "1.0"}))


def _instance(tmp_path: Path, *, au: bool = False, openloader: bool = False) -> Path:
    mods = tmp_path / "mods"
    mods.mkdir()
    _mod_jar(mods, "amod.jar", "amod", "A", "amod:tomato")
    _mod_jar(mods, "bmod.jar", "bmod", "B", "bmod:tomato")
    if au:
        _plain_jar(mods, "au.jar", "almostunified")
    if openloader:
        _plain_jar(mods, "ol.jar", "openloader")
    return tmp_path


def test_apply_per_world_fallback_then_revert(tmp_path: Path) -> None:
    root = _instance(tmp_path)
    result = apply_resolution(
        root, PROFILE, recipe_winners=None, tag_winners=None, target="per_world"
    )
    assert result.status == "applied"
    assert result.almost_unified is False
    # No existing worlds → fallback to a global datapacks/.
    dp = root / "datapacks" / "emendator-overrides"
    assert (dp / "pack.mcmeta").is_file()
    # Default recipe winner is the first mod alphabetically (amod → result "A").
    assert '"A"' in (dp / f"data/farmersdelight/{SEG}/fried_rice.json").read_text()
    # No AU → tags are handled by a re-tag datapack file.
    assert (dp / "data/c/tags/items/crops/tomato.json").is_file()

    assert result.manifest is not None
    revert = revert_resolution(Path(result.manifest))
    assert revert.status == "reverted"
    assert not dp.exists()  # the override subtree is pruned


def test_apply_with_au_writes_unify_not_retag(tmp_path: Path) -> None:
    root = _instance(tmp_path, au=True)
    result = apply_resolution(
        root, PROFILE, recipe_winners=None, tag_winners=None, target="per_world"
    )
    assert result.almost_unified is True
    assert (root / "config/almostunified/unify.json").is_file()
    # Tags go to unify.json, so the datapack carries no tag re-tag file.
    assert not (root / "datapacks/emendator-overrides/data/c").exists()


def test_apply_openloader_target(tmp_path: Path) -> None:
    root = _instance(tmp_path, openloader=True)
    result = apply_resolution(
        root, PROFILE, recipe_winners=None, tag_winners=None, target="openloader"
    )
    assert result.open_loader is True
    assert (root / "openloader/data/emendator-overrides/pack.mcmeta").is_file()


def test_resolution_targets_reports_presence(tmp_path: Path) -> None:
    targets = resolution_targets(_instance(tmp_path, au=True, openloader=True), PROFILE)
    assert targets.almost_unified is True
    assert targets.open_loader is True
