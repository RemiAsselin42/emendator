"""Cross-stack contract: backend subject-id derivation matches the shared fixture.

Winner maps (recipe_winners / tag_winners) are keyed by a conflict's *subject*
string. The backend derives it from a jar data path and stores it in
``detail.recipe`` / ``detail.tag``; the front re-reads it via ``conflictSubject``.
Both sides must produce identical strings. This test pins the backend derivation
to ``src/lib/__fixtures__/conflict-subjects.json``; the matching front test
(``conflicts.test.ts``) pins ``conflictSubject`` to the same file, so the two
stay in lockstep.
"""

import json
from pathlib import Path

from app.analyzer.detectors import (
    _CONVENTIONAL_NAMESPACES,
    _recipe_id_from_path,
    _tag_id_from_path,
)

_FIXTURE = (
    Path(__file__).resolve().parents[2] / "src" / "lib" / "__fixtures__" / "conflict-subjects.json"
)


def _cases() -> dict:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def test_recipe_subject_derivation_matches_fixture() -> None:
    for case in _cases()["recipe_collision"]:
        assert _recipe_id_from_path(case["path"]) == case["subject"], case["path"]


def test_tag_subject_derivation_matches_fixture() -> None:
    for case in _cases()["tag_overlap"]:
        assert _tag_id_from_path(case["path"], _CONVENTIONAL_NAMESPACES) == case["subject"], case[
            "path"
        ]
