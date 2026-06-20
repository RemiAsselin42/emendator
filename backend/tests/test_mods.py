import json
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.analyzer.mods import scan_mods_folder
from app.main import app

client = TestClient(app)


def _make_jar(folder: Path, name: str, metadata: dict | str | None) -> Path:
    """Write a minimal jar (zip). ``metadata`` None = no fabric.mod.json;
    a str is written verbatim (to inject malformed JSON)."""
    path = folder / name
    with zipfile.ZipFile(path, "w") as zf:
        if isinstance(metadata, str):
            zf.writestr("fabric.mod.json", metadata)
        elif metadata is not None:
            zf.writestr("fabric.mod.json", json.dumps(metadata))
        else:
            zf.writestr("README.txt", "not a fabric mod")
    return path


def test_scan_lists_mods_with_fields(tmp_path: Path) -> None:
    _make_jar(
        tmp_path,
        "examplemod-1.2.0.jar",
        {
            "id": "examplemod",
            "name": "Example Mod",
            "version": "1.2.0",
            "environment": "*",
            "depends": {"minecraft": "1.21.1", "fabric-api": "*"},
        },
    )
    result = scan_mods_folder(tmp_path, "1.21.1")

    assert result.profile == "1.21.1"
    assert result.counts.total == 1
    assert result.counts.mods == 1
    assert result.counts.errors == 0
    mod = result.mods[0]
    assert mod.id == "examplemod"
    assert mod.version == "1.2.0"
    assert mod.mc_version == "1.21.1"
    assert mod.environment == "*"
    assert mod.jar == "examplemod-1.2.0.jar"


def test_client_mod_is_untestable(tmp_path: Path) -> None:
    _make_jar(tmp_path, "client.jar", {"id": "shadermod", "environment": "client"})
    _make_jar(tmp_path, "server.jar", {"id": "servermod", "environment": "server"})

    result = scan_mods_folder(tmp_path, "1.21.1")

    assert result.counts.mods == 2
    assert result.counts.untestable == 1
    assert result.counts.testable == 1
    assert result.untestable[0].id == "shadermod"
    assert "client" in result.untestable[0].reason


def test_missing_environment_defaults_to_both(tmp_path: Path) -> None:
    _make_jar(tmp_path, "lib.jar", {"id": "libmod"})
    result = scan_mods_folder(tmp_path, "1.21.1")
    assert result.mods[0].environment == "*"
    assert result.counts.untestable == 0


def test_non_fabric_and_corrupt_jars_become_errors(tmp_path: Path) -> None:
    _make_jar(tmp_path, "plain.jar", None)  # no fabric.mod.json
    _make_jar(tmp_path, "bad.jar", "{not valid json")  # malformed metadata
    _make_jar(tmp_path, "noid.jar", {"name": "missing id"})  # missing required id

    result = scan_mods_folder(tmp_path, "1.21.1")

    assert result.counts.mods == 0
    assert result.counts.errors == 3
    reasons = {e.jar: e.reason for e in result.errors}
    assert "no fabric.mod.json" in reasons["plain.jar"]
    assert "invalid fabric.mod.json" in reasons["bad.jar"]
    assert "missing 'id'" in reasons["noid.jar"]


def test_control_characters_in_metadata_are_tolerated(tmp_path: Path) -> None:
    # Real mods (e.g. Debugify) embed literal newlines in string values, which
    # strict JSON rejects but Fabric's lenient loader accepts.
    _make_jar(tmp_path, "ctrl.jar", '{"id": "ctrlmod", "description": "multi\nline"}')
    result = scan_mods_folder(tmp_path, "1.21.1")
    assert result.counts.errors == 0
    assert result.mods[0].id == "ctrlmod"


def test_mc_version_from_list_depends(tmp_path: Path) -> None:
    _make_jar(
        tmp_path,
        "multi.jar",
        {"id": "multimod", "depends": {"minecraft": ["1.21", "1.21.1"]}},
    )
    result = scan_mods_folder(tmp_path, "1.21.1")
    assert result.mods[0].mc_version == "1.21"


def test_scan_endpoint_returns_camelcase(tmp_path: Path) -> None:
    _make_jar(tmp_path, "m.jar", {"id": "m", "depends": {"minecraft": "1.21.1"}})
    res = client.post("/mods/scan", json={"path": str(tmp_path)})
    assert res.status_code == 200
    body = res.json()
    assert body["modsPath"] == str(tmp_path)
    assert body["mods"][0]["mcVersion"] == "1.21.1"
    assert body["counts"]["total"] == 1


def test_scan_endpoint_auto_detects_version(tmp_path: Path) -> None:
    _make_jar(tmp_path, "a.jar", {"id": "a", "depends": {"minecraft": ">=1.21.4"}})
    res = client.post("/mods/scan", json={"path": str(tmp_path)})
    assert res.status_code == 200
    body = res.json()
    assert body["profile"] == "1.21.4"
    assert body["detection"]["status"] == "confident"
    assert body["detection"]["block"] == "1.21.2+"


def test_scan_endpoint_409_on_ambiguous(tmp_path: Path) -> None:
    _make_jar(tmp_path, "old.jar", {"id": "old", "depends": {"minecraft": "<=1.20.6"}})
    _make_jar(tmp_path, "new.jar", {"id": "new", "depends": {"minecraft": ">=1.21"}})
    res = client.post("/mods/scan", json={"path": str(tmp_path)})
    assert res.status_code == 409
    detection = res.json()["detail"]
    assert detection["status"] == "ambiguous"
    assert len(detection["candidates"]) >= 2


def test_scan_endpoint_honors_explicit_version(tmp_path: Path) -> None:
    # Ambiguous set, but the user picked 1.20.6 — scan must proceed with it.
    _make_jar(tmp_path, "old.jar", {"id": "old", "depends": {"minecraft": "<=1.20.6"}})
    _make_jar(tmp_path, "new.jar", {"id": "new", "depends": {"minecraft": ">=1.21"}})
    res = client.post("/mods/scan", json={"path": str(tmp_path), "version": "1.20.6"})
    assert res.status_code == 200
    body = res.json()
    assert body["profile"] == "1.20.6"
    # Detection must reflect the picked version, not the auto-detected one.
    assert body["detection"]["block"] == "1.20.5–1.20.6"
    assert body["detection"]["status"] == "confident"
    assert "new" in body["detection"]["outliers"]  # >=1.21 mod can't run on 1.20.6


def test_detect_endpoint(tmp_path: Path) -> None:
    _make_jar(tmp_path, "a.jar", {"id": "a", "depends": {"minecraft": "1.21.1"}})
    res = client.post("/mods/detect", json={"path": str(tmp_path)})
    assert res.status_code == 200
    body = res.json()
    assert body["detectedVersion"] == "1.21.1"
    assert body["block"] == "1.21–1.21.1"


def test_profiles_endpoint_lists_blocks() -> None:
    res = client.get("/profiles")
    assert res.status_code == 200
    blocks = {p["block"] for p in res.json()}
    assert "1.21–1.21.1" in blocks
    assert "26.1+" in blocks


def test_scan_endpoint_rejects_missing_path() -> None:
    res = client.post("/mods/scan", json={"path": "C:/does/not/exist/__nope__"})
    assert res.status_code == 400


def test_scan_endpoint_rejects_file_path(tmp_path: Path) -> None:
    f = tmp_path / "a-file.txt"
    f.write_text("x")
    res = client.post("/mods/scan", json={"path": str(f)})
    assert res.status_code == 400
