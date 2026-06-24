"""The CurseForge connection endpoints: status + saving/clearing the API key."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import credentials
from app.config import settings
from app.enrich import curseforge
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Never touch the real ~/.emendator, and start each test keyless.
    monkeypatch.setattr(credentials, "_store_path", lambda: tmp_path / "credentials.json")
    monkeypatch.setattr(settings, "curseforge_api_key", None)


def test_status_unconfigured_by_default() -> None:
    res = client.get("/config/curseforge")
    assert res.status_code == 200
    assert res.json() == {"configured": False, "valid": None, "detail": None}


def test_set_key_persists_trimmed_and_reports_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(curseforge, "verify_key", lambda key: (True, None))
    res = client.post("/config/curseforge", json={"apiKey": "  secret-key  "})
    assert res.status_code == 200
    assert res.json() == {"configured": True, "valid": True, "detail": None}
    assert settings.curseforge_api_key == "secret-key"  # trimmed + live
    # A subsequent status GET sees it configured (does not re-probe).
    assert client.get("/config/curseforge").json() == {
        "configured": True,
        "valid": None,
        "detail": None,
    }


def test_set_key_saves_even_when_unverified(monkeypatch: pytest.MonkeyPatch) -> None:
    reason = "CurseForge returned HTTP 403."
    monkeypatch.setattr(curseforge, "verify_key", lambda key: (False, reason))
    res = client.post("/config/curseforge", json={"apiKey": "bad-or-offline"})
    assert res.json() == {"configured": True, "valid": False, "detail": reason}
    assert settings.curseforge_api_key == "bad-or-offline"  # saved anyway


def test_blank_key_clears(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(curseforge, "verify_key", lambda key: (True, None))
    client.post("/config/curseforge", json={"apiKey": "x"})
    res = client.post("/config/curseforge", json={"apiKey": "   "})
    assert res.json() == {"configured": False, "valid": None, "detail": None}
    assert settings.curseforge_api_key is None


def test_stored_key_loads_into_settings_on_boot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(curseforge, "verify_key", lambda key: (True, None))
    client.post("/config/curseforge", json={"apiKey": "stored"})  # writes the file
    monkeypatch.setattr(settings, "curseforge_api_key", None)  # simulate a fresh boot, no env
    credentials.load_into_settings()
    assert settings.curseforge_api_key == "stored"


def test_env_key_wins_over_stored_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(curseforge, "verify_key", lambda key: (True, None))
    client.post("/config/curseforge", json={"apiKey": "from-file"})
    monkeypatch.setattr(settings, "curseforge_api_key", "from-env")  # env already set
    credentials.load_into_settings()
    assert settings.curseforge_api_key == "from-env"  # not overwritten
