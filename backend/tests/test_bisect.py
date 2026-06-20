import json
import zipfile
from pathlib import Path

from app.models import RunRequest
from app.profile import get_profile
from app.runner import bisect
from app.runner.bisect import _partition, _split_base_candidates, bisect_set, ddmin

PROFILE = get_profile("1.21.1")


def test_partition_even_and_uneven() -> None:
    assert _partition([1, 2, 3, 4], 2) == [[1, 2], [3, 4]]
    assert _partition([1, 2, 3, 4, 5], 2) == [[1, 2, 3], [4, 5]]
    assert _partition([1, 2], 4) == [[1], [2]]  # n clamped to len


def test_ddmin_isolates_pair_across_halves() -> None:
    elements = [f"m{i}" for i in range(64)]
    guilty = {"m5", "m40"}  # one in each initial half — the hard case
    calls = 0

    def reproduces(subset: list[str]) -> bool:
        nonlocal calls
        calls += 1
        return guilty.issubset(set(subset))

    result = ddmin(elements, reproduces)
    assert set(result) == guilty
    # 1-minimal: removing either element stops reproduction
    assert not reproduces([result[0]])
    assert calls < 100  # far below brute force, roughly logarithmic


def test_ddmin_single_culprit() -> None:
    assert ddmin(list(range(32)), lambda s: 7 in s) == [7]


def test_ddmin_returns_self_when_irreducible_pair() -> None:
    # both elements needed; cannot shrink below the pair
    assert sorted(ddmin(["a", "b"], lambda s: "a" in s and "b" in s)) == ["a", "b"]


def _make_jar(folder: Path, name: str, metadata: dict) -> None:
    with zipfile.ZipFile(folder / name, "w") as zf:
        zf.writestr("fabric.mod.json", json.dumps(metadata))


def test_split_base_candidates(tmp_path: Path) -> None:
    _make_jar(tmp_path, "fabric-api.jar", {"id": "fabric-api", "provides": ["fabric-rl-v0"]})
    _make_jar(
        tmp_path, "lithium.jar", {"id": "lithium", "depends": {"fabric-api": "*", "minecraft": "*"}}
    )
    _make_jar(tmp_path, "sodium.jar", {"id": "sodium", "depends": {"fabric-rl-v0": "*"}})

    base, candidates, jar_to_id = _split_base_candidates(tmp_path, "1.21.1")

    assert {p.name for p in base} == {"fabric-api.jar"}  # provides/id depended upon
    assert {p.name for p in candidates} == {"lithium.jar", "sodium.jar"}
    assert jar_to_id["lithium.jar"] == "lithium"


def test_bisect_rejects_non_directory(tmp_path: Path) -> None:
    result = bisect_set(RunRequest(path=str(tmp_path / "missing")), PROFILE)
    assert result.status == "error"
    assert result.note and "directory" in result.note.lower()


def test_bisect_reports_when_docker_unavailable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(bisect, "is_docker_available", lambda: False)
    result = bisect_set(RunRequest(path=str(tmp_path)), PROFILE)
    assert result.status == "error"
    assert result.note and "docker" in result.note.lower()
    assert result.profile == "1.21.1"
