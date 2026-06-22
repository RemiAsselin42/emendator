"""Auto-discovery of installed modpack instances across launcher directories."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.sources import discovery

client = TestClient(app)


def _instance(root: Path, jars: int, manifest: dict | None = None) -> None:
    mods = root / "mods"
    mods.mkdir(parents=True)
    for i in range(jars):
        (mods / f"mod{i}.jar").write_bytes(b"PK")
    if manifest is not None:
        (root / "minecraftinstance.json").write_text(json.dumps(manifest))


def test_discovers_instances_with_mods(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cf = tmp_path / "curseforge" / "Instances"
    _instance(cf / "PackA", 3, {"name": "Pack A", "gameVersion": "1.20.1"})
    _instance(cf / "PackB", 1)
    (cf / "Empty").mkdir(parents=True)  # no mods → excluded

    monkeypatch.setattr(discovery, "_candidate_parents", lambda: [(cf, "curseforge")])
    monkeypatch.setattr(discovery, "_candidate_singles", lambda: [])

    found = discovery.discover_instances()
    names = {i.name for i in found}
    assert "Pack A" in names and "PackB" in names
    assert all(i.source == "curseforge" for i in found)
    assert found[0].name == "Pack A"  # richest pack (3 mods) sorts first
    assert found[0].mod_count == 3


def test_source_is_trusted_from_launcher(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A Modrinth profile with no per-folder manifest would detect as "vanilla";
    # discovery trusts the launcher dir it came from.
    profiles = tmp_path / "ModrinthApp" / "profiles"
    _instance(profiles / "MyPack", 2)

    monkeypatch.setattr(discovery, "_candidate_parents", lambda: [(profiles, "modrinth")])
    monkeypatch.setattr(discovery, "_candidate_singles", lambda: [])

    found = discovery.discover_instances()
    assert len(found) == 1
    assert found[0].source == "modrinth"
    assert found[0].name == "MyPack"  # falls back to folder name


def test_dedupes_across_overlapping_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cf = tmp_path / "Instances"
    _instance(cf / "Pack", 1)
    parents = [(cf, "curseforge"), (cf, "prism")]
    monkeypatch.setattr(discovery, "_candidate_parents", lambda: parents)
    monkeypatch.setattr(discovery, "_candidate_singles", lambda: [])
    assert len(discovery.discover_instances()) == 1


def test_discover_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(discovery, "_candidate_parents", lambda: [])
    monkeypatch.setattr(discovery, "_candidate_singles", lambda: [])
    res = client.get("/instances/discover")
    assert res.status_code == 200
    assert res.json() == []
