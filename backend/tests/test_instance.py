"""Instance detection: CurseForge / Modrinth / Prism / vanilla / raw mods."""

import json
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.sources.instance import detect_instance, mods_jars

client = TestClient(app)


def _jar(folder: Path, name: str, meta: dict) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(folder / name, "w") as zf:
        zf.writestr("fabric.mod.json", json.dumps(meta))


def test_raw_mods_folder(tmp_path: Path) -> None:
    _jar(tmp_path, "a.jar", {"id": "a", "version": "1"})
    _jar(tmp_path, "b.jar", {"id": "b", "version": "1"})
    inst = detect_instance(tmp_path)
    assert inst.source == "raw_mods"
    assert inst.folders.mods == str(tmp_path.resolve())
    assert inst.mod_count == 2
    assert len(mods_jars(inst)) == 2


def test_vanilla_minecraft_layout(tmp_path: Path) -> None:
    _jar(tmp_path / "mods", "a.jar", {"id": "a", "version": "1"})
    (tmp_path / "resourcepacks").mkdir()
    inst = detect_instance(tmp_path)
    assert inst.source == "vanilla"
    assert inst.folders.mods == str((tmp_path / "mods").resolve())
    assert inst.folders.resourcepacks == str((tmp_path / "resourcepacks").resolve())
    assert inst.mod_count == 1


def test_curseforge_instance(tmp_path: Path) -> None:
    (tmp_path / "minecraftinstance.json").write_text(
        json.dumps(
            {
                "name": "My CF Pack",
                "gameVersion": "1.20.1",
                "baseModLoader": {"name": "forge-47.2.0"},
            }
        )
    )
    _jar(tmp_path / "mods", "a.jar", {"id": "a", "version": "1"})
    inst = detect_instance(tmp_path)
    assert inst.source == "curseforge"
    assert inst.name == "My CF Pack"
    assert inst.loader == "forge"
    assert inst.mc_version == "1.20.1"
    assert inst.mod_count == 1


def test_modrinth_instance(tmp_path: Path) -> None:
    (tmp_path / "profile.json").write_text(
        json.dumps(
            {"metadata": {"name": "My Modrinth Pack", "game_version": "1.21.1", "loader": "fabric"}}
        )
    )
    _jar(tmp_path / "mods", "a.jar", {"id": "a", "version": "1"})
    inst = detect_instance(tmp_path)
    assert inst.source == "modrinth"
    assert inst.name == "My Modrinth Pack"
    assert inst.loader == "fabric"
    assert inst.mc_version == "1.21.1"


def test_prism_instance(tmp_path: Path) -> None:
    (tmp_path / "instance.cfg").write_text("name=My Prism Pack\n")
    (tmp_path / "mmc-pack.json").write_text(
        json.dumps(
            {
                "components": [
                    {"uid": "net.minecraft", "version": "1.21.1"},
                    {"uid": "net.fabricmc.fabric-loader", "version": "0.16.0"},
                ]
            }
        )
    )
    _jar(tmp_path / ".minecraft" / "mods", "a.jar", {"id": "a", "version": "1"})
    inst = detect_instance(tmp_path)
    assert inst.source == "prism"
    assert inst.name == "My Prism Pack"
    assert inst.loader == "fabric"
    assert inst.mc_version == "1.21.1"
    assert inst.folders.mods == str((tmp_path / ".minecraft" / "mods").resolve())


def test_instance_detect_endpoint(tmp_path: Path) -> None:
    _jar(tmp_path / "mods", "a.jar", {"id": "a", "depends": {"minecraft": "1.21.1"}})
    res = client.post("/instance/detect", json={"path": str(tmp_path)})
    assert res.status_code == 200
    body = res.json()
    assert body["source"] == "vanilla"
    assert body["modCount"] == 1


def test_instance_scan_endpoint(tmp_path: Path) -> None:
    _jar(tmp_path / "mods", "a.jar", {"id": "a", "depends": {"minecraft": "1.21.1"}})
    res = client.post("/instance/scan", json={"path": str(tmp_path)})
    assert res.status_code == 200
    body = res.json()
    # /instance/scan now returns an InstanceReport: mods conflict map nested under
    # "mods", plus the instance metadata and (empty here) content-pack sections.
    assert body["mods"]["counts"]["mods"] == 1
    assert body["mods"]["profile"] == "1.21.1"
    assert body["mods"]["mods"][0]["loader"] == "fabric"
    assert body["instance"]["source"] == "vanilla"
    assert body["resourcepacks"] == []


def _stream_events(text: str) -> list[dict]:
    """Parse an SSE stream body into its decoded ``data:`` payloads."""
    events: list[dict] = []
    for frame in text.split("\n\n"):
        for line in frame.split("\n"):
            if line.startswith("data:"):
                events.append(json.loads(line[len("data:") :].strip()))
    return events


def test_instance_scan_stream_endpoint(tmp_path: Path) -> None:
    _jar(tmp_path / "mods", "a.jar", {"id": "a", "depends": {"minecraft": "1.21.1"}})
    res = client.post("/instance/scan/stream", json={"path": str(tmp_path)})
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")

    events = _stream_events(res.text)
    phases = [e["phase"] for e in events]
    assert "progress" in phases
    assert phases[-1] == "done"

    # Progress is monotonic and stays below 100 until the terminal "done" frame.
    percents = [e["percent"] for e in events if e["phase"] == "progress"]
    assert percents == sorted(percents)
    assert all(0 <= p < 100 for p in percents)

    # The "done" frame carries the same InstanceReport shape as /instance/scan.
    report = events[-1]["report"]
    assert report["mods"]["counts"]["mods"] == 1
    assert report["mods"]["profile"] == "1.21.1"
    assert report["instance"]["source"] == "vanilla"


def test_instance_scan_stream_409_on_ambiguous(tmp_path: Path) -> None:
    # Ambiguity is resolved before the stream opens, so it still 409s up front.
    _jar(tmp_path / "mods", "old.jar", {"id": "old", "depends": {"minecraft": "<=1.20.6"}})
    _jar(tmp_path / "mods", "new.jar", {"id": "new", "depends": {"minecraft": ">=1.21"}})
    res = client.post("/instance/scan/stream", json={"path": str(tmp_path)})
    assert res.status_code == 409
    assert res.json()["detail"]["status"] == "ambiguous"


def test_instance_scan_detects_datapacks(tmp_path: Path) -> None:
    _jar(tmp_path / "mods", "a.jar", {"id": "a", "version": "1"})
    (tmp_path / "saves" / "world" / "datapacks" / "dp").mkdir(parents=True)
    inst = detect_instance(tmp_path)
    assert any("world" in d for d in inst.folders.datapacks)
