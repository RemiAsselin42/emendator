"""In-place mod update: download newest Modrinth version, verify, swap."""

import hashlib
import json
import os
import tempfile
import zipfile
from pathlib import Path

import httpx
import pytest

from app.enrich import curseforge, install, modrinth


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


# --- CurseForge fallback when Modrinth has no match ---------------------------


def test_install_falls_back_to_curseforge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tmp_path.mkdir(exist_ok=True)
    content = b"GECKOLIB-JAR"
    sha1 = hashlib.sha1(content).hexdigest()
    monkeypatch.setattr(modrinth, "find_install", lambda *a, **k: None)  # Modrinth misses
    monkeypatch.setattr(install.settings, "curseforge_api_key", "key")
    monkeypatch.setattr(
        curseforge,
        "find_install",
        lambda mod_id, loader, gv, key: {
            "url": "https://edge/geckolib.jar",
            "filename": "geckolib-1.0.jar",
            "sha1": sha1,
            "version_number": "1.0",
            "project_title": "GeckoLib",
        },
    )
    monkeypatch.setattr(install, "_download", _fake_download(content))

    result = install.install_mod(tmp_path, "geckolib", "fabric", "1.21.1")

    assert result.status == "installed"
    assert result.jar == "geckolib-1.0.jar"
    assert result.message == "Installed from CurseForge."  # source flagged for the user
    assert (tmp_path / "geckolib-1.0.jar").read_bytes() == content


def test_install_skips_curseforge_without_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tmp_path.mkdir(exist_ok=True)
    monkeypatch.setattr(modrinth, "find_install", lambda *a, **k: None)
    monkeypatch.setattr(modrinth, "probe_project", lambda *a, **k: None)
    monkeypatch.setattr(install.settings, "curseforge_api_key", None)  # no key → no fallback
    monkeypatch.setattr(
        curseforge,
        "find_install",
        lambda *a, **k: pytest.fail("must not call CurseForge without a key"),
    )
    monkeypatch.setattr(
        curseforge,
        "probe_project",
        lambda *a, **k: pytest.fail("must not probe CurseForge without a key"),
    )
    result = install.install_mod(tmp_path, "geckolib", "fabric", "1.21.1")
    assert result.status == "not_found"
    assert result.links == []
    assert "Modrinth" in (result.message or "") and "CurseForge" not in (result.message or "")


def test_curseforge_find_install_resolves_by_slug(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(path: str, params: dict, api_key: str):
        assert api_key == "key"
        if path == "/v1/mods/search":
            assert params.get("slug") == "geckolib"  # exact slug tried first
            return {"data": [{"id": 388172, "name": "GeckoLib", "slug": "geckolib"}]}
        if path == "/v1/mods/388172/files":
            return {
                "data": [
                    {
                        "fileName": "geckolib-1.0.jar",
                        "downloadUrl": "https://edge/geckolib-1.0.jar",
                        "fileDate": "2024-01-01T00:00:00Z",
                        "displayName": "1.0",
                        "hashes": [{"value": "deadbeef", "algo": 1}],
                    }
                ]
            }
        return None

    monkeypatch.setattr(curseforge, "_api_get", fake_get)
    info = curseforge.find_install("geckolib", "fabric", "1.21.1", "key")
    assert info is not None
    assert info["filename"] == "geckolib-1.0.jar"
    assert info["sha1"] == "deadbeef"
    assert info["project_title"] == "GeckoLib"


def test_curseforge_find_install_falls_back_to_search(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    def fake_get(path: str, params: dict, api_key: str):
        calls.append(params)
        if path == "/v1/mods/search" and "slug" in params:
            return {"data": []}  # slug miss → trigger fuzzy search
        if path == "/v1/mods/search" and "searchFilter" in params:
            return {"data": [{"id": 999, "name": "Real Mod"}]}
        if path == "/v1/mods/999/files":
            return {
                "data": [
                    {
                        "fileName": "real-2.0.jar",
                        "downloadUrl": "https://edge/real.jar",
                        "fileDate": "2024-05-01T00:00:00Z",
                        "displayName": "2.0",
                        "hashes": [{"value": "abc123", "algo": 1}],
                    }
                ]
            }
        return None

    monkeypatch.setattr(curseforge, "_api_get", fake_get)
    info = curseforge.find_install("some-mod", "fabric", "1.21.1", "key")
    assert info is not None
    assert info["filename"] == "real-2.0.jar"
    assert info["project_title"] == "Real Mod"
    assert any("searchFilter" in p for p in calls)


def test_curseforge_find_install_skips_third_party_optout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get(path: str, params: dict, api_key: str):
        if path == "/v1/mods/search":
            return {"data": [{"id": 1, "name": "Opted Out"}]}
        if path == "/v1/mods/1/files":
            # author disabled third-party distribution → no downloadUrl
            return {"data": [{"fileName": "x.jar", "downloadUrl": None, "fileDate": "2024-01-01"}]}
        return None

    monkeypatch.setattr(curseforge, "_api_get", fake_get)
    assert curseforge.find_install("x", "fabric", "1.21.1", "key") is None


def test_curseforge_find_install_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        curseforge, "_api_get", lambda *a, **k: pytest.fail("must not hit the network")
    )
    assert curseforge.find_install("jei", "fabric", "1.21.1", "") is None  # no key
    assert curseforge.find_install("minecraft", "fabric", "1.21.1", "key") is None  # platform dep


class _Resp:
    """Minimal stand-in for an httpx.Response in verify_key probes (status only)."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


def test_curseforge_verify_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # 200 → verified, no detail.
    monkeypatch.setattr(curseforge.httpx, "get", lambda *a, **k: _Resp(200))
    assert curseforge.verify_key("good") == (True, None)
    # A rejected key reports the status in the detail.
    monkeypatch.setattr(curseforge.httpx, "get", lambda *a, **k: _Resp(403))
    ok, detail = curseforge.verify_key("bad")
    assert ok is False
    assert detail is not None and "403" in detail

    # A network failure is distinguished from a rejection.
    def _boom(*a: object, **k: object) -> object:
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(curseforge.httpx, "get", _boom)
    ok, detail = curseforge.verify_key("x")
    assert ok is False
    assert detail is not None and "reach" in detail.lower()
    # No probe for an empty key.
    assert curseforge.verify_key("") == (False, "No key was entered.")


# --- probe_project: precise not_found (project exists, just no compatible build) ----


def test_modrinth_probe_project_finds_by_slug(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(path: str, params: dict | None = None):
        assert path == "/v2/project/luna"  # slug-exact, no version filter
        return {"id": "abc", "slug": "luna", "title": "Luna"}

    monkeypatch.setattr(modrinth, "_api_get", fake_get)
    assert modrinth.probe_project("luna", "fabric") == {
        "slug": "luna",
        "title": "Luna",
        "url": "https://modrinth.com/mod/luna",
    }


def test_modrinth_probe_project_none_and_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(modrinth, "_api_get", lambda path, params=None: None)
    assert modrinth.probe_project("nope", "fabric") is None
    # Platform pseudo-deps never hit the network.
    monkeypatch.setattr(modrinth, "_api_get", lambda *a, **k: pytest.fail("no network"))
    assert modrinth.probe_project("minecraft", "fabric") is None


def test_curseforge_probe_project_uses_website_url(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(path: str, params: dict, api_key: str):
        assert path == "/v1/mods/search" and params.get("slug") == "luna"
        return {
            "data": [
                {
                    "id": 1,
                    "name": "Luna",
                    "slug": "luna",
                    "links": {"websiteUrl": "https://www.curseforge.com/minecraft/mc-mods/luna"},
                }
            ]
        }

    monkeypatch.setattr(curseforge, "_api_get", fake_get)
    assert curseforge.probe_project("luna", "fabric", "key") == {
        "title": "Luna",
        "url": "https://www.curseforge.com/minecraft/mc-mods/luna",
    }


def test_curseforge_probe_project_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        curseforge, "_api_get", lambda *a, **k: pytest.fail("must not hit the network")
    )
    assert curseforge.probe_project("luna", "fabric", "") is None  # no key
    assert curseforge.probe_project("minecraft", "fabric", "key") is None  # platform dep


def test_install_not_found_links_to_existing_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No compatible build, but the project exists on Modrinth → message + direct link.
    tmp_path.mkdir(exist_ok=True)
    monkeypatch.setattr(modrinth, "find_install", lambda *a, **k: None)
    monkeypatch.setattr(install.settings, "curseforge_api_key", None)
    monkeypatch.setattr(
        modrinth,
        "probe_project",
        lambda mod_id, loader: {
            "slug": "luna",
            "title": "Luna",
            "url": "https://modrinth.com/mod/luna",
        },
    )
    result = install.install_mod(tmp_path, "luna", "fabric", "1.21.1")
    assert result.status == "not_found"
    assert "Luna" in (result.message or "") and "1.21.1" in (result.message or "")
    assert [(link.provider, link.url) for link in result.links] == [
        ("modrinth", "https://modrinth.com/mod/luna")
    ]


def test_install_not_found_probes_curseforge_when_keyed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tmp_path.mkdir(exist_ok=True)
    monkeypatch.setattr(modrinth, "find_install", lambda *a, **k: None)
    monkeypatch.setattr(curseforge, "find_install", lambda *a, **k: None)
    monkeypatch.setattr(install.settings, "curseforge_api_key", "key")
    monkeypatch.setattr(modrinth, "probe_project", lambda *a, **k: None)
    monkeypatch.setattr(
        curseforge,
        "probe_project",
        lambda mod_id, loader, key: {
            "title": "Luna",
            "url": "https://www.curseforge.com/minecraft/mc-mods/luna",
        },
    )
    result = install.install_mod(tmp_path, "luna", "fabric", "1.21.1")
    assert result.status == "not_found"
    assert [link.provider for link in result.links] == ["curseforge"]
    assert "CurseForge" in (result.message or "")


# --- disable_mod / enable_mod: reversible sideline, no download ----------------


def test_disable_suffixes_jar_in_place(tmp_path: Path) -> None:
    _old_jar(tmp_path, "spell_engine-1.0.jar")
    result = install.disable_mod(tmp_path, "spell_engine-1.0.jar")
    assert result.status == "disabled"
    assert not (tmp_path / "spell_engine-1.0.jar").exists()  # out of the active set
    # renamed in place (no sidecar folder), content preserved
    assert (tmp_path / "spell_engine-1.0.jar.disabled").read_bytes() == b"OLD"
    assert not (tmp_path / "disabled").exists()


def test_disable_not_found(tmp_path: Path) -> None:
    tmp_path.mkdir(exist_ok=True)
    result = install.disable_mod(tmp_path, "nope.jar")
    assert result.status == "not_found"


def test_enable_strips_suffix(tmp_path: Path) -> None:
    _old_jar(tmp_path, "spell_engine-1.0.jar")
    install.disable_mod(tmp_path, "spell_engine-1.0.jar")
    result = install.enable_mod(tmp_path, "spell_engine-1.0.jar")
    assert result.status == "enabled"
    assert (tmp_path / "spell_engine-1.0.jar").read_bytes() == b"OLD"  # back in the set
    assert not (tmp_path / "spell_engine-1.0.jar.disabled").exists()


def test_enable_not_found_when_not_disabled(tmp_path: Path) -> None:
    tmp_path.mkdir(exist_ok=True)
    result = install.enable_mod(tmp_path, "spell_engine-1.0.jar")
    assert result.status == "not_found"


def _fabric_jar(folder: Path, name: str, mod_id: str) -> Path:
    """A minimal, parsable Fabric jar declaring ``mod_id``."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("fabric.mod.json", json.dumps({"id": mod_id, "version": "1.0"}))
    return path


def test_install_reenables_disabled_dependency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The dependency is present, only disabled — install must re-enable it, not download.
    _fabric_jar(tmp_path, "spell_engine-1.0.jar.disabled", "spell_engine")
    monkeypatch.setattr(
        modrinth, "find_install", lambda *a, **k: pytest.fail("must not download a disabled mod")
    )
    result = install.install_mod(tmp_path, "spell_engine", "fabric", "1.21.1")
    assert result.status == "installed"
    assert result.jar == "spell_engine-1.0.jar"
    assert (tmp_path / "spell_engine-1.0.jar").exists()
    assert not (tmp_path / "spell_engine-1.0.jar.disabled").exists()
