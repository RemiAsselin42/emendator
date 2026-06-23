"""Version parsing + block detection (PROJECT.md §6)."""

from app.profile import block_of, detect_version, resolve_profile
from app.version import McVersion, parse_constraint

# --- McVersion ------------------------------------------------------------


def test_mcversion_parse_two_and_three_parts() -> None:
    assert McVersion.parse("1.21.5") == McVersion(1, 21, 5)
    assert McVersion.parse("1.21") == McVersion(1, 21, 0)
    assert McVersion.parse("26.1") == McVersion(26, 1, 0)


def test_mcversion_post_2026_sorts_above_all_1x() -> None:
    assert McVersion.parse("26.1") > McVersion.parse("1.21.99")
    assert McVersion.parse("1.21.5") > McVersion.parse("1.21")


def test_mcversion_str_drops_zero_patch() -> None:
    assert str(McVersion(1, 21, 0)) == "1.21"
    assert str(McVersion(1, 21, 5)) == "1.21.5"
    assert str(McVersion(26, 1, 0)) == "26.1"


def test_mcversion_parse_tolerates_suffix_and_prefix() -> None:
    assert McVersion.parse("v1.21.1") == McVersion(1, 21, 1)
    assert McVersion.parse("1.21.1+build.3") == McVersion(1, 21, 1)


# --- parse_constraint -----------------------------------------------------


def _contains(raw: object, version: str) -> bool:
    return parse_constraint(raw).contains(McVersion.parse(version))


def test_exact_constraint() -> None:
    assert _contains("1.21.1", "1.21.1")
    assert not _contains("1.21.1", "1.21.2")


def test_comparator_constraints() -> None:
    assert _contains(">=1.21", "1.21")
    assert _contains(">=1.21", "1.21.8")
    assert not _contains(">=1.21", "1.20.6")
    assert _contains("<=1.20.6", "1.20.6")
    assert not _contains("<=1.20.6", "1.21")
    assert not _contains(">1.21", "1.21")
    assert not _contains("<1.21", "1.21")


def test_compound_range() -> None:
    assert _contains(">=1.20.5 <=1.20.6", "1.20.5")
    assert _contains(">=1.20.5 <=1.20.6", "1.20.6")
    assert not _contains(">=1.20.5 <=1.20.6", "1.21")
    assert not _contains(">=1.20.5 <=1.20.6", "1.20.4")


def test_tilde_and_caret() -> None:
    assert _contains("~1.21", "1.21.5")  # >=1.21 <1.22
    assert not _contains("~1.21", "1.22")
    assert _contains("~1.21.4", "1.21.9")
    assert not _contains("~1.21.4", "1.21.3")
    assert _contains("^1.21", "1.21.8")  # >=1.21 <2.0
    assert not _contains("^1.21", "2.0")


def test_wildcard_and_any() -> None:
    assert _contains("1.21.x", "1.21.7")
    assert not _contains("1.21.x", "1.22")
    assert _contains("1.x", "1.20.1")
    assert parse_constraint("*").is_any
    assert parse_constraint("").is_any
    assert parse_constraint(None).is_any


def test_list_is_or() -> None:
    c = parse_constraint(["1.20.1", "1.21.1"])
    assert c.contains(McVersion.parse("1.20.1"))
    assert c.contains(McVersion.parse("1.21.1"))
    assert not c.contains(McVersion.parse("1.21.5"))


# --- block_of / resolve_profile -------------------------------------------


def _block_id(version: str) -> str | None:
    block = block_of(McVersion.parse(version))
    return block.id if block else None


def test_block_of_spans_all_five_blocks() -> None:
    assert _block_id("1.20.1") == "1.18–1.20.4"
    assert _block_id("1.20.6") == "1.20.5–1.20.6"
    assert _block_id("1.21.1") == "1.21–1.21.1"
    assert _block_id("1.21.5") == "1.21.2+"
    assert _block_id("26.1") == "26.1+"
    assert _block_id("1.16") is None


def test_resolve_profile_pulls_block_constants() -> None:
    old = resolve_profile("1.20.1")
    assert old.jdk == "17"
    assert old.item_format == "nbt"
    assert old.recipe_path == "data/{mod}/recipes"

    new = resolve_profile("1.21.5")
    assert new.profile == "1.21.5"
    assert new.jdk == "21"
    assert new.item_format == "components"
    assert new.recipe_path == "data/{mod}/recipe"

    future = resolve_profile("26.1")
    assert future.jdk == "25"
    assert future.runner_supported is False


def test_datapack_format_is_version_exact_not_block_level() -> None:
    # Same block ("1.18–1.20.4"), different exact pack_format per version — the bug
    # this fixes: a 1.19.2 pack must not inherit the block's 1.20.4 value (26).
    assert resolve_profile("1.18").datapack_format == 8
    assert resolve_profile("1.18.2").datapack_format == 9
    assert resolve_profile("1.19.2").datapack_format == 10
    assert resolve_profile("1.19.4").datapack_format == 12
    assert resolve_profile("1.20.1").datapack_format == 15
    assert resolve_profile("1.20.4").datapack_format == 26
    # Newer blocks: top-of-block versions get their own value, not the block floor's.
    assert resolve_profile("1.21.1").datapack_format == 48
    assert resolve_profile("1.21.5").datapack_format == 71
    assert resolve_profile("1.21.8").datapack_format == 81


# --- detect_version -------------------------------------------------------


def test_detect_confident_picks_highest_floor() -> None:
    det = detect_version([("a", ">=1.21"), ("b", ">=1.21.4"), ("c", "*")])
    assert det.status == "confident"
    assert det.detected_version == "1.21.4"  # highest floor; "*" ignored
    assert det.block == "1.21.2+"
    assert det.confidence == 1.0
    assert det.outliers == []


def test_detect_single_old_block() -> None:
    det = detect_version([("a", "1.20.1"), ("b", ">=1.20")])
    assert det.status == "confident"
    assert det.detected_version == "1.20.1"
    assert det.block == "1.18–1.20.4"


def test_detect_ambiguous_when_blocks_conflict() -> None:
    # One mod caps at 1.20.6, another needs >=1.21 — no single version satisfies both.
    det = detect_version([("old", "<=1.20.6"), ("new1", ">=1.21"), ("new2", ">=1.21")])
    assert det.status == "ambiguous"
    assert "old" in det.outliers
    assert {c.block for c in det.candidates} >= {"1.20.5–1.20.6", "1.21–1.21.1"}


def test_detect_ambiguous_when_no_constraints() -> None:
    det = detect_version([("a", "*"), ("b", None)])
    assert det.status == "ambiguous"
    assert det.detected_version is None
    assert det.confidence == 0.0
    # The picker must still offer every block to choose from (not an empty list).
    assert {c.block for c in det.candidates} == {
        "1.18–1.20.4",
        "1.20.5–1.20.6",
        "1.21–1.21.1",
        "1.21.2+",
        "26.1+",
    }


def test_detect_runner_gated_for_future_block() -> None:
    det = detect_version([("a", ">=26.1")])
    assert det.detected_version == "26.1"
    assert det.runner_supported is False


def test_block_candidates_cover_constraint_above_latest_known() -> None:
    # ">=1.21.9" sits above the newest known 1.21.x but still inside the 1.21.2+ block.
    det = detect_version([("a", ">=1.21.9")])
    blocks = {c.block for c in det.candidates}
    assert "1.21.2+" in blocks


def test_forced_version_reflects_picked_block() -> None:
    # Mods point at 1.21.x, but the user forces the old NBT block.
    det = detect_version([("a", ">=1.21"), ("b", ">=1.21")], forced="1.20.1")
    assert det.status == "confident"
    assert det.detected_version == "1.20.1"
    assert det.block == "1.18–1.20.4"
    assert det.jdk == "17"
    assert det.outliers == ["a", "b"]  # neither supports 1.20.1


def test_stray_newer_mod_does_not_hijack_the_pack() -> None:
    # A 1.19.2 pack: many open-ended ">=1.19.2" mods + one stray ">=1.21" library.
    # The pack must still be detected as 1.19.2 (the cluster), not dragged to 1.21.
    mods = [(f"m{i}", ">=1.19.2") for i in range(20)] + [("stray", ">=1.21")]
    det = detect_version(mods)
    assert det.detected_version == "1.19.2"
    assert det.block == "1.18–1.20.4"
    assert det.status == "confident"  # 20/21 ≥ 0.9
    assert det.outliers == ["stray"]


def test_same_block_patch_differences_stay_confident() -> None:
    # A real 1.19.2 pack: most mods open/loose, a long tail pins narrower or older
    # patches ("1.19", "=1.19.0", "=1.19.1"). Those are the same block, so the
    # pack stays a confident 1.19.2 — they are not counted as outliers.
    mods = [
        ("a", ">=1.19.2"),
        ("b", "1.19.x"),
        ("c", "~1.19"),
        ("d", "1.19"),  # bare 1.19 == exact 1.19.0
        ("e", "=1.19.0"),
        ("f", "=1.19.1"),
        ("g", "<=1.19.2"),
    ]
    det = detect_version(mods)
    assert det.detected_version == "1.19.2"
    assert det.block == "1.18–1.20.4"
    assert det.status == "confident"
    assert det.outliers == []


def test_or_pipe_constraint() -> None:
    c = parse_constraint("1.20.1 || >=1.21")
    assert c.contains(McVersion.parse("1.20.1"))
    assert c.contains(McVersion.parse("1.21.5"))
    assert not c.contains(McVersion.parse("1.20.4"))
