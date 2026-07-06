"""The MCP tool surface: wrappers, guardrails, structured errors."""

import json
import zipfile
from pathlib import Path

from app import mcp as server


def _jar(folder: Path, mod_id: str) -> None:
    with zipfile.ZipFile(folder / f"{mod_id}.jar", "w") as zf:
        zf.writestr(
            "fabric.mod.json",
            json.dumps({"id": mod_id, "version": "1.0", "depends": {"minecraft": "1.21.1"}}),
        )


def test_tools_are_registered() -> None:
    # the inventory the manifest and docs promise
    import anyio

    tools = {t.name for t in anyio.run(server.mcp.list_tools)}
    assert {
        "scan_instance",
        "run_test",
        "bisect",
        "list_runs",
        "get_run",
        "get_run_log",
        "get_run_crash",
        "plan_mixin_fixes",
        "apply_mixin_fixes",
        "revert_mixin_fixes",
        "verify_mixin_fixes",
        "disable_mod",
        "enable_mod",
        "update_mod",
        "rollback_mod",
    } <= tools


def test_scan_instance_returns_conflict_map(tmp_path: Path) -> None:
    _jar(tmp_path, "a")
    result = server.scan_instance(str(tmp_path))
    assert result["profile"] == "1.21.1"
    assert result["counts"]["mods"] == 1


def test_scan_reports_ambiguous_version_as_structured_error(tmp_path: Path) -> None:
    with zipfile.ZipFile(tmp_path / "old.jar", "w") as zf:
        zf.writestr(
            "fabric.mod.json", json.dumps({"id": "old", "depends": {"minecraft": "<=1.20.6"}})
        )
    with zipfile.ZipFile(tmp_path / "new.jar", "w") as zf:
        zf.writestr(
            "fabric.mod.json", json.dumps({"id": "new", "depends": {"minecraft": ">=1.21"}})
        )
    result = server.scan_instance(str(tmp_path))
    assert result["error"] == "ambiguous_version"
    assert result["detail"]["status"] == "ambiguous"


def test_mutations_are_dry_run_by_default(tmp_path: Path) -> None:
    _jar(tmp_path, "a")
    preview = server.apply_mixin_fixes(str(tmp_path))
    assert preview["applied"] is False
    assert "apply=true" in preview["note"]
    assert "plan" in preview

    gated = server.disable_mod(str(tmp_path), "a.jar")
    assert gated["applied"] is False
    assert (tmp_path / "a.jar").is_file()  # untouched

    reverted = server.revert_mixin_fixes(str(tmp_path / "nope.json"))
    assert reverted["applied"] is False  # gated before even touching the manifest


def test_disable_applies_with_consent(tmp_path: Path) -> None:
    _jar(tmp_path, "a")
    result = server.disable_mod(str(tmp_path), "a.jar", apply=True)
    assert result["status"] == "disabled"
    assert (tmp_path / "a.jar.disabled").is_file()


def test_get_run_structured_error() -> None:
    assert "error" in server.get_run("nope00000000")
    assert server.get_run_log("nope00000000").startswith("error:")
