"""The mixin fix ladder: planning, apply (merge + manifest) and revert."""

import json
import zipfile
from pathlib import Path

import pytest

from app.profile import get_profile
from app.resolve import mixins
from app.resolve.mixins import apply_mixin_fixes, plan_mixin_fixes, revert_mixin_fixes
from tests.bytecode import overwrite_class, strings_class

PROFILE = get_profile("1.21.1")
TARGET = "net.minecraft.class_1"


def _mixin_jar(
    folder: Path,
    mod_id: str,
    *,
    with_toggle: bool,
    entry: str = "alloc.FooMixin",
) -> Path:
    """A Fabric mod whose one mixin @Overwrite-s ``tick`` in the shared target."""
    package = f"com.{mod_id}.mixin"
    config: dict = {"package": package, "mixins": [entry]}
    if with_toggle:
        config["plugin"] = f"{package}.Plugin"
    path = folder / f"{mod_id}.jar"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(
            "fabric.mod.json",
            json.dumps({"id": mod_id, "version": "1.0", "depends": {"minecraft": "1.21.1"}}),
        )
        zf.writestr(f"{mod_id}.mixins.json", json.dumps(config))
        base = package.replace(".", "/")
        zf.writestr(f"{base}/{entry.replace('.', '/')}.class", overwrite_class(TARGET))
        if with_toggle:
            zf.writestr(f"{base}/Plugin.class", strings_class(f"./config/{mod_id}.properties"))
    return path


def test_plan_prefers_the_toggle_rung(tmp_path: Path) -> None:
    _mixin_jar(tmp_path, "a", with_toggle=True)
    _mixin_jar(tmp_path, "b", with_toggle=False)

    result = plan_mixin_fixes(tmp_path, PROFILE)

    assert result.loader == "fabric"
    assert result.filter_mod == "mixin-blacklist"
    (plan,) = result.plans
    assert plan.target == TARGET
    assert plan.loser == "a"  # equal dependents; "a" has the cheapest rung
    assert plan.rung == "toggle"
    (action,) = plan.actions
    assert action.kind == "toggle"
    assert action.file is not None
    assert action.file.path == "config/a.properties"
    assert "mixin.alloc=false" in action.file.content
    assert action.feature_hints == ["alloc"]
    assert "jar_patch" in plan.alternatives


def test_plan_falls_to_filter_for_forced_loser_without_toggle(tmp_path: Path) -> None:
    _mixin_jar(tmp_path, "a", with_toggle=True)
    _mixin_jar(tmp_path, "b", with_toggle=False)

    result = plan_mixin_fixes(tmp_path, PROFILE, losers={TARGET: "b"})

    (plan,) = result.plans
    assert plan.loser == "b"
    assert plan.rung == "filter"
    kinds = [a.kind for a in plan.actions]
    assert kinds == ["install_filter", "filter_config"]
    config_action = plan.actions[1]
    assert config_action.file is not None
    assert config_action.file.path == "config/mixinblacklist.json"
    blacklist = json.loads(config_action.file.content)
    assert blacklist["common"]["mixinClassNames"] == ["com.b.mixin.alloc.FooMixin"]


def test_plan_disable_fallback_without_filter_mod(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mixin_jar(tmp_path, "a", with_toggle=False)
    _mixin_jar(tmp_path, "b", with_toggle=False)
    monkeypatch.setattr(mixins, "pick_filter_mod", lambda loader, version: None)

    result = plan_mixin_fixes(tmp_path, PROFILE)

    (plan,) = result.plans
    assert plan.rung == "disable"
    assert plan.actions[0].jar == "a.jar"
    assert plan.note is not None  # points at rollback / jar patch first


def test_apply_merges_toggle_file_and_revert_restores(tmp_path: Path) -> None:
    _mixin_jar(tmp_path, "a", with_toggle=True)
    _mixin_jar(tmp_path, "b", with_toggle=False)
    # a pre-existing user toggle file must survive the apply (merge, not clobber)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    user_file = config_dir / "a.properties"
    user_file.write_text("mixin.other=false\n", encoding="utf-8")

    result = apply_mixin_fixes(tmp_path, PROFILE)

    assert result.status == "applied"
    assert result.manifest is not None
    content = user_file.read_text(encoding="utf-8")
    assert "mixin.other=false" in content  # user line kept
    assert "mixin.alloc=false" in content  # our override added

    reverted = revert_mixin_fixes(Path(result.manifest))
    assert reverted.status == "applied"
    assert user_file.read_text(encoding="utf-8") == "mixin.other=false\n"  # prior restored
    assert not Path(result.manifest).exists()


def test_apply_disable_fallback_and_revert_reenables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mixin_jar(tmp_path, "a", with_toggle=False)
    _mixin_jar(tmp_path, "b", with_toggle=False)
    monkeypatch.setattr(mixins, "pick_filter_mod", lambda loader, version: None)

    result = apply_mixin_fixes(tmp_path, PROFILE)

    assert result.status == "applied"
    assert result.disabled == ["a.jar"]
    assert (tmp_path / "a.jar.disabled").is_file()
    assert not (tmp_path / "a.jar").exists()

    assert result.manifest is not None
    reverted = revert_mixin_fixes(Path(result.manifest))
    assert reverted.disabled == ["a.jar"]
    assert (tmp_path / "a.jar").is_file()  # back in the boot set


def test_apply_respects_allow_disable_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mixin_jar(tmp_path, "a", with_toggle=False)
    _mixin_jar(tmp_path, "b", with_toggle=False)
    monkeypatch.setattr(mixins, "pick_filter_mod", lambda loader, version: None)

    result = apply_mixin_fixes(tmp_path, PROFILE, allow_disable=False)

    assert result.status == "nothing"
    assert (tmp_path / "a.jar").is_file()  # nothing sidelined
