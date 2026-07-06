"""The AI fix loop: strict-tool decisions executed deterministically, capped, gated."""

import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.ai import fixer
from app.config import settings
from app.main import app
from app.models import MixinVerifyResult, RunVerdict
from app.profile import get_profile

client = TestClient(app)
PROFILE = get_profile("1.21.1")


def _jar(folder: Path, mod_id: str) -> None:
    with zipfile.ZipFile(folder / f"{mod_id}.jar", "w") as zf:
        zf.writestr(
            "fabric.mod.json",
            json.dumps({"id": mod_id, "version": "1.0", "depends": {"minecraft": "1.21.1"}}),
        )


def _tool_response(action: dict) -> SimpleNamespace:
    block = SimpleNamespace(type="tool_use", id="toolu_1", input=action)
    return SimpleNamespace(
        content=[block],
        stop_reason="tool_use",
        usage=SimpleNamespace(input_tokens=1000, output_tokens=200),
    )


def _verify(fixed: bool) -> MixinVerifyResult:
    return MixinVerifyResult(
        verdict=RunVerdict(status="ok" if fixed else "crash", profile="1.21.1", duration_ms=1),
        fixed=fixed,
    )


def test_loop_applies_then_reports_fixed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _jar(tmp_path, "a")
    decisions = iter(
        [
            _tool_response(
                {
                    "action": "apply_fixes",
                    "reasoning": "toggle covers it",
                    "losers": [],
                    "targets": [],
                    "jar": "",
                }
            )
        ]
    )
    monkeypatch.setattr(fixer, "_create_message", lambda c, **k: next(decisions))
    monkeypatch.setattr(fixer, "verify_mixin_fixes", lambda root, profile, run_id: _verify(True))
    monkeypatch.setattr(fixer.anthropic, "Anthropic", lambda api_key: SimpleNamespace())

    result = fixer.run_ai_fix(
        tmp_path,
        PROFILE,
        api_key="sk-test",
        model="claude-opus-4-8",
        max_iterations=3,
        token_cap=500_000,
        baseline_run_id=None,
    )

    assert result.status == "fixed"
    assert [i.action for i in result.iterations] == ["apply_fixes"]
    assert result.input_tokens == 1000
    assert result.output_tokens == 200


def test_loop_stops_when_model_says_stop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _jar(tmp_path, "a")
    decisions = iter(
        [
            _tool_response(
                {
                    "action": "stop",
                    "reasoning": "conflict is client-side only",
                    "losers": [],
                    "targets": [],
                    "jar": "",
                }
            )
        ]
    )
    monkeypatch.setattr(fixer, "_create_message", lambda c, **k: next(decisions))
    monkeypatch.setattr(fixer.anthropic, "Anthropic", lambda api_key: SimpleNamespace())

    result = fixer.run_ai_fix(
        tmp_path,
        PROFILE,
        api_key="sk-test",
        model="claude-opus-4-8",
        max_iterations=3,
        token_cap=500_000,
        baseline_run_id=None,
    )
    assert result.status == "stopped"
    assert "client-side" in (result.message or "")


def test_loop_hits_iteration_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _jar(tmp_path, "a")

    def endless(_client, **_kwargs):
        return _tool_response(
            {
                "action": "disable_mod",
                "reasoning": "try sidelining",
                "losers": [],
                "targets": [],
                "jar": "nope.jar",
            }
        )

    monkeypatch.setattr(fixer, "_create_message", endless)
    monkeypatch.setattr(fixer, "verify_mixin_fixes", lambda root, profile, run_id: _verify(False))
    monkeypatch.setattr(fixer.anthropic, "Anthropic", lambda api_key: SimpleNamespace())

    result = fixer.run_ai_fix(
        tmp_path,
        PROFILE,
        api_key="sk-test",
        model="claude-opus-4-8",
        max_iterations=2,
        token_cap=500_000,
        baseline_run_id=None,
    )
    assert result.status == "not_fixed"
    assert len(result.iterations) == 2


def test_endpoint_requires_configured_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "anthropic_api_key", None)
    _jar(tmp_path, "a")
    res = client.post("/ai/fix", json={"path": str(tmp_path)})
    assert res.status_code == 400
    assert "Anthropic API key" in res.json()["detail"]


def test_key_config_endpoints(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app import credentials

    monkeypatch.setattr(credentials, "_store_path", lambda: tmp_path / "credentials.json")
    monkeypatch.setattr(settings, "anthropic_api_key", None)

    assert client.get("/config/anthropic").json() == {"configured": False}
    saved = client.post("/config/anthropic", json={"apiKey": "sk-ant-test"})
    assert saved.json() == {"configured": True}
    assert settings.anthropic_api_key == "sk-ant-test"

    cleared = client.post("/config/anthropic", json={"apiKey": ""})
    assert cleared.json() == {"configured": False}
