"""Online enrichment: CurseForge (offline manifest) + Modrinth (mocked HTTP)."""

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from app.enrich import cache, curseforge, modrinth
from app.models import Mod


def _jar(folder: Path, name: str) -> Path:
    path = folder / name
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("fabric.mod.json", json.dumps({"id": name.split(".")[0], "version": "1.0.0"}))
    return path


def test_curseforge_offline_enrichment(tmp_path: Path) -> None:
    (tmp_path / "minecraftinstance.json").write_text(
        json.dumps(
            {
                "installedAddons": [
                    {
                        "name": "Just Enough Items",
                        "webSiteURL": "https://www.curseforge.com/minecraft/mc-mods/jei",
                        "installedFile": {"fileNameOnDisk": "jei.jar"},
                    }
                ]
            }
        )
    )
    mods = [Mod(id="jei", jar="jei.jar")]
    curseforge.enrich_offline(tmp_path, mods)
    assert mods[0].provider == "curseforge"
    homepage = mods[0].homepage
    assert homepage is not None
    assert homepage.endswith("/jei")
    assert mods[0].name == "Just Enough Items"  # filled from manifest


def test_modrinth_enrichment_flags_update(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cache, "_cache_dir", lambda: tmp_path / "cache")
    jar = _jar(tmp_path, "sodium.jar")
    sha1 = hashlib.sha1(jar.read_bytes()).hexdigest()

    def fake_post(path: str, payload: dict) -> dict:
        if path.endswith("/version_files"):
            return {sha1: {"project_id": "AANobbMI", "version_number": "0.5.8"}}
        if path.endswith("/update"):
            return {sha1: {"version_number": "0.6.0"}}
        return {}

    monkeypatch.setattr(modrinth, "_api_post", fake_post)
    mods = [Mod(id="sodium", jar="sodium.jar", loader="fabric")]
    modrinth.enrich([jar], mods, "1.21.1", "fabric")

    assert mods[0].provider == "modrinth"
    homepage = mods[0].homepage
    assert homepage is not None
    assert "AANobbMI" in homepage
    assert mods[0].latest_version == "0.6.0"
    assert mods[0].update_available is True


def test_modrinth_no_update_when_current(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cache, "_cache_dir", lambda: tmp_path / "cache")
    jar = _jar(tmp_path, "mod.jar")
    sha1 = hashlib.sha1(jar.read_bytes()).hexdigest()
    monkeypatch.setattr(
        modrinth,
        "_api_post",
        lambda path, payload: (
            {sha1: {"project_id": "X", "version_number": "1.0.0"}}
            if path.endswith("/version_files")
            else {sha1: {"version_number": "1.0.0"}}
        ),
    )
    mods = [Mod(id="mod", jar="mod.jar", loader="fabric")]
    modrinth.enrich([jar], mods, "1.21.1", "fabric")
    assert mods[0].update_available is False


def test_modrinth_network_failure_is_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cache, "_cache_dir", lambda: tmp_path / "cache")
    jar = _jar(tmp_path, "x.jar")
    monkeypatch.setattr(modrinth, "_api_post", lambda path, payload: None)  # simulate offline
    mods = [Mod(id="x", jar="x.jar", loader="fabric")]
    modrinth.enrich([jar], mods, "1.21.1", "fabric")
    assert mods[0].provider is None  # untouched


def test_cache_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cache, "_cache_dir", lambda: tmp_path / "cache")
    assert cache.get("ns", "key") is None
    cache.put("ns", "key", {"hello": "world"})
    assert cache.get("ns", "key") == {"hello": "world"}
