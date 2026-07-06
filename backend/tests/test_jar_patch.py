"""Jar mixin-config patching (last-resort fix) + the consent gate."""

import json
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.resolve.jar_patch import patch_jar_mixin_config, unpatch_jar

client = TestClient(app)

_CONFIG = {
    "package": "com.example.mixin",
    "required": True,
    "mixins": ["FooMixin", "BarMixin"],
    "client": ["render.GlassMixin"],
}


def _make_jar(folder: Path, name: str = "mod.jar") -> Path:
    path = folder / name
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("fabric.mod.json", json.dumps({"id": "mod", "version": "1.0"}))
        zf.writestr("mod.mixins.json", json.dumps(_CONFIG))
        zf.writestr("com/example/Other.class", b"\xca\xfe\xba\xbe")
    return path


def _read_config(path: Path) -> dict:
    with zipfile.ZipFile(path) as zf:
        return json.loads(zf.read("mod.mixins.json"))


def test_patch_removes_entries_and_keeps_backup(tmp_path: Path) -> None:
    jar = _make_jar(tmp_path)
    result = patch_jar_mixin_config(
        tmp_path, "mod.jar", remove_mixins={"mod.mixins.json": ["FooMixin"]}
    )
    assert result.status == "patched"
    assert result.backup == "mod.jar.bak"
    assert result.removed == {"mod.mixins.json": ["FooMixin"]}

    patched = _read_config(jar)
    assert patched["mixins"] == ["BarMixin"]  # FooMixin dropped
    assert patched["client"] == ["render.GlassMixin"]  # untouched section

    original = _read_config(tmp_path / "mod.jar.bak")
    assert original["mixins"] == ["FooMixin", "BarMixin"]  # backup is pristine

    # non-config entries survive the re-zip
    with zipfile.ZipFile(jar) as zf:
        assert zf.read("com/example/Other.class") == b"\xca\xfe\xba\xbe"


def test_patch_flips_required_and_priority(tmp_path: Path) -> None:
    jar = _make_jar(tmp_path)
    result = patch_jar_mixin_config(
        tmp_path,
        "mod.jar",
        set_required={"mod.mixins.json": False},
        set_priority={"mod.mixins.json": 900},
    )
    assert result.status == "patched"
    patched = _read_config(jar)
    assert patched["required"] is False
    assert patched["priority"] == 900


def test_patch_nothing_when_no_entry_matches(tmp_path: Path) -> None:
    _make_jar(tmp_path)
    result = patch_jar_mixin_config(
        tmp_path, "mod.jar", remove_mixins={"mod.mixins.json": ["NoSuchMixin"]}
    )
    assert result.status == "nothing"
    assert not (tmp_path / "mod.jar.bak").exists()  # untouched: no backup


def test_unpatch_restores_original(tmp_path: Path) -> None:
    jar = _make_jar(tmp_path)
    patch_jar_mixin_config(tmp_path, "mod.jar", remove_mixins={"mod.mixins.json": ["FooMixin"]})
    result = unpatch_jar(tmp_path, "mod.jar")
    assert result.status == "patched"
    assert _read_config(jar)["mixins"] == ["FooMixin", "BarMixin"]


def test_patch_endpoint_requires_confirm(tmp_path: Path) -> None:
    _make_jar(tmp_path)
    body = {
        "path": str(tmp_path),
        "jar": "mod.jar",
        "removeMixins": {"mod.mixins.json": ["FooMixin"]},
    }
    refused = client.post("/mods/patch", json=body)
    assert refused.status_code == 400  # consent gate

    accepted = client.post("/mods/patch", json={**body, "confirm": True})
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "patched"
