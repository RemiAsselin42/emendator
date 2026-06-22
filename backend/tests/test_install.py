"""In-place mod update: download newest Modrinth version, verify, swap."""

import hashlib
import os
import tempfile
from pathlib import Path

import pytest

from app.enrich import install, modrinth


def _fake_download(content: bytes):
    def _dl(url: str, dest_dir: Path) -> Path:
        fd, name = tempfile.mkstemp(dir=dest_dir, suffix=".part")
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        return Path(name)

    return _dl


def _old_jar(mods: Path, name: str = "sodium-0.5.8.jar") -> Path:
    mods.mkdir(parents=True, exist_ok=True)
    jar = mods / name
    jar.write_bytes(b"OLD")
    return jar


def test_update_replaces_jar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _old_jar(tmp_path)
    content = b"NEWJAR-CONTENT"
    sha1 = hashlib.sha1(content).hexdigest()
    monkeypatch.setattr(
        modrinth,
        "find_update",
        lambda old, loader, gv: {
            "url": "https://cdn/sodium-0.6.0.jar",
            "filename": "sodium-0.6.0.jar",
            "sha1": sha1,
            "version_number": "0.6.0",
            "current_sha1": "old",
        },
    )
    monkeypatch.setattr(install, "_download", _fake_download(content))

    result = install.update_mod(tmp_path, "sodium-0.5.8.jar", "fabric", "1.21.1")

    assert result.status == "updated"
    assert result.new_jar == "sodium-0.6.0.jar"
    assert result.version == "0.6.0"
    assert (tmp_path / "sodium-0.6.0.jar").read_bytes() == content
    assert not (tmp_path / "sodium-0.5.8.jar").exists()  # old removed


def test_update_no_update_when_same_hash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _old_jar(tmp_path)
    monkeypatch.setattr(
        modrinth,
        "find_update",
        lambda old, loader, gv: {
            "url": "x",
            "filename": "sodium-0.5.8.jar",
            "sha1": "abc",
            "current_sha1": "abc",
        },
    )
    result = install.update_mod(tmp_path, "sodium-0.5.8.jar", "fabric", "1.21.1")
    assert result.status == "no_update"
    assert (tmp_path / "sodium-0.5.8.jar").read_bytes() == b"OLD"  # untouched


def test_update_not_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _old_jar(tmp_path)
    monkeypatch.setattr(modrinth, "find_update", lambda old, loader, gv: None)
    result = install.update_mod(tmp_path, "sodium-0.5.8.jar", "fabric", "1.21.1")
    assert result.status == "not_found"


def test_update_checksum_mismatch_aborts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _old_jar(tmp_path)
    monkeypatch.setattr(
        modrinth,
        "find_update",
        lambda old, loader, gv: {
            "url": "x",
            "filename": "sodium-0.6.0.jar",
            "sha1": "expected-but-wrong",
            "current_sha1": "old",
        },
    )
    monkeypatch.setattr(install, "_download", _fake_download(b"corrupt"))
    result = install.update_mod(tmp_path, "sodium-0.5.8.jar", "fabric", "1.21.1")
    assert result.status == "error"
    assert not (tmp_path / "sodium-0.6.0.jar").exists()  # nothing installed
    assert (tmp_path / "sodium-0.5.8.jar").exists()  # old kept


def test_update_missing_jar(tmp_path: Path) -> None:
    tmp_path.mkdir(exist_ok=True)
    result = install.update_mod(tmp_path, "nope.jar", "fabric", "1.21.1")
    assert result.status == "error"


# --- install_mod: add a dependency the runner flagged as missing --------------


def test_install_adds_missing_dependency(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tmp_path.mkdir(exist_ok=True)
    content = b"FABRIC-API-JAR"
    sha1 = hashlib.sha1(content).hexdigest()
    monkeypatch.setattr(
        modrinth,
        "find_install",
        lambda mod_id, loader, gv: {
            "url": "https://cdn/fabric-api-0.100.jar",
            "filename": "fabric-api-0.100.jar",
            "sha1": sha1,
            "version_number": "0.100.0",
            "project_title": "Fabric API",
        },
    )
    monkeypatch.setattr(install, "_download", _fake_download(content))

    result = install.install_mod(tmp_path, "fabric", "fabric", "1.21.1")

    assert result.status == "installed"
    assert result.jar == "fabric-api-0.100.jar"
    assert result.version == "0.100.0"
    assert (tmp_path / "fabric-api-0.100.jar").read_bytes() == content


def test_install_not_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tmp_path.mkdir(exist_ok=True)
    monkeypatch.setattr(modrinth, "find_install", lambda mod_id, loader, gv: None)
    result = install.install_mod(tmp_path, "minecraft", "fabric", "1.21.1")
    assert result.status == "not_found"
    assert result.mod_id == "minecraft"


def test_install_already_present_is_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "cloth-config.jar").write_bytes(b"EXISTING")
    monkeypatch.setattr(
        modrinth,
        "find_install",
        lambda mod_id, loader, gv: {
            "url": "x",
            "filename": "cloth-config.jar",
            "sha1": "whatever",
            "version_number": "1.0.0",
            "project_title": "Cloth Config",
        },
    )
    result = install.install_mod(tmp_path, "cloth-config", "fabric", "1.21.1")
    assert result.status == "installed"
    assert (tmp_path / "cloth-config.jar").read_bytes() == b"EXISTING"  # not re-downloaded


def test_install_checksum_mismatch_aborts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tmp_path.mkdir(exist_ok=True)
    monkeypatch.setattr(
        modrinth,
        "find_install",
        lambda mod_id, loader, gv: {
            "url": "x",
            "filename": "architectury.jar",
            "sha1": "expected-but-wrong",
            "version_number": "9.0.0",
            "project_title": "Architectury API",
        },
    )
    monkeypatch.setattr(install, "_download", _fake_download(b"corrupt"))
    result = install.install_mod(tmp_path, "architectury", "fabric", "1.21.1")
    assert result.status == "error"
    assert not (tmp_path / "architectury.jar").exists()  # nothing installed


def test_find_install_resolves_by_slug(monkeypatch: pytest.MonkeyPatch) -> None:
    version_obj = {
        "version_number": "0.100.0",
        "files": [
            {
                "primary": True,
                "url": "https://cdn/fabric-api-0.100.jar",
                "filename": "fabric-api-0.100.jar",
                "hashes": {"sha1": "deadbeef"},
            }
        ],
    }

    def fake_get(path: str, params: dict | None = None):
        # "fabric" aliases to the "fabric-api" slug; the version endpoint answers.
        assert path == "/v2/project/fabric-api/version"
        return [version_obj]

    monkeypatch.setattr(modrinth, "_api_get", fake_get)
    info = modrinth.find_install("fabric", "fabric", "1.21.1")
    assert info is not None
    assert info["filename"] == "fabric-api-0.100.jar"
    assert info["sha1"] == "deadbeef"


def test_find_install_falls_back_to_search(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_get(path: str, params: dict | None = None):
        calls.append(path)
        if path == "/v2/project/some-mod/version":
            return []  # slug miss → trigger search
        if path == "/v2/search":
            return {"hits": [{"slug": "real-slug", "title": "Real Mod"}]}
        if path == "/v2/project/real-slug/version":
            return [
                {
                    "version_number": "2.0.0",
                    "files": [
                        {
                            "primary": True,
                            "url": "https://cdn/real.jar",
                            "filename": "real-2.0.0.jar",
                            "hashes": {"sha1": "abc123"},
                        }
                    ],
                }
            ]
        return None

    monkeypatch.setattr(modrinth, "_api_get", fake_get)
    info = modrinth.find_install("some-mod", "fabric", "1.21.1")
    assert info is not None
    assert info["filename"] == "real-2.0.0.jar"
    assert info["project_title"] == "Real Mod"
    assert "/v2/search" in calls


def test_find_install_skips_platform_pseudo_deps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        modrinth, "_api_get", lambda *a, **k: pytest.fail("must not hit the network")
    )
    assert modrinth.find_install("minecraft", "fabric", "1.21.1") is None
    assert modrinth.find_install("fabricloader", "fabric", "1.21.1") is None


# --- disable_mod / enable_mod: reversible sideline, no download ----------------


def test_disable_sidelines_jar(tmp_path: Path) -> None:
    _old_jar(tmp_path, "spell_engine-1.0.jar")
    result = install.disable_mod(tmp_path, "spell_engine-1.0.jar")
    assert result.status == "disabled"
    assert not (tmp_path / "spell_engine-1.0.jar").exists()  # out of the active set
    assert (tmp_path / "disabled" / "spell_engine-1.0.jar").read_bytes() == b"OLD"  # preserved


def test_disable_not_found(tmp_path: Path) -> None:
    tmp_path.mkdir(exist_ok=True)
    result = install.disable_mod(tmp_path, "nope.jar")
    assert result.status == "not_found"


def test_enable_restores_jar(tmp_path: Path) -> None:
    _old_jar(tmp_path, "spell_engine-1.0.jar")
    install.disable_mod(tmp_path, "spell_engine-1.0.jar")
    result = install.enable_mod(tmp_path, "spell_engine-1.0.jar")
    assert result.status == "enabled"
    assert (tmp_path / "spell_engine-1.0.jar").read_bytes() == b"OLD"  # back in the set
    assert not (tmp_path / "disabled" / "spell_engine-1.0.jar").exists()


def test_enable_not_found_when_not_disabled(tmp_path: Path) -> None:
    tmp_path.mkdir(exist_ok=True)
    result = install.enable_mod(tmp_path, "spell_engine-1.0.jar")
    assert result.status == "not_found"
