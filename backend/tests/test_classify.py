from app.runner.classify import extract_cause, reached_done, tail

DONE_LINE = '[12:00:05] [Server thread/INFO]: Done (8.123s)! For help, type "help"'


def test_reached_done_true_on_clean_start() -> None:
    log = "[Server thread/INFO]: Loading 60 mods\n" + DONE_LINE
    assert reached_done(log) is True


def test_reached_done_false_without_done_line() -> None:
    assert reached_done("[Server thread/INFO]: Loading 60 mods\n") is False


def test_mixin_apply_failure() -> None:
    log = (
        "[Server thread/ERROR]: Mixin apply for mod sodium failed "
        "sodium.mixins.json:WorldRendererMixin from mod sodium\n"
        "org.spongepowered.asm.mixin.transformer.throwables.InvalidMixinException: ..."
    )
    cause = extract_cause(log)
    assert cause.category == "mixin_apply"
    assert cause.mods == ["sodium"]
    assert "mixin" in cause.summary.lower()


def test_missing_dependency() -> None:
    log = (
        "[main/WARN]: Mod 'Example' (example) 1.0.0 requires version 0.100.0 or later "
        "of fabric-api, which is missing!"
    )
    cause = extract_cause(log)
    assert cause.category == "missing_dependency"
    assert cause.mods == ["fabric-api"]


def test_duplicate_mod() -> None:
    cause = extract_cause("[main/FATAL]: Duplicate mods: sodium")
    assert cause.category == "duplicate_mod"
    assert cause.mods == ["sodium"]


def test_incompatible_mod() -> None:
    cause = extract_cause("Mod alpha is incompatible with mod beta")
    assert cause.category == "incompatible_mod"
    assert cause.mods == ["beta"]


def test_recipe_error() -> None:
    cause = extract_cause("[Server thread/ERROR]: Error parsing recipe modx:foo")
    assert cause.category == "recipe_error"


def test_fabric_resolution_banner_without_detail() -> None:
    cause = extract_cause("Incompatible mods found! See the log for details.")
    assert cause.category == "missing_dependency"


def test_forge_fml_missing_dependency() -> None:
    log = (
        "Missing or unsupported mandatory dependencies:\n"
        "\tMod ID: 'jei', Requested by: 'somemod', Expected range: '[15,)', "
        "Actual version: '[MISSING]'"
    )
    cause = extract_cause(log)
    assert cause.category == "missing_dependency"
    assert cause.mods == ["jei"]


def test_neoforge_mandatory_deps_banner_only() -> None:
    cause = extract_cause("Missing or unsupported mandatory dependencies: see log")
    assert cause.category == "missing_dependency"


def test_forge_found_duplicate_mods() -> None:
    cause = extract_cause("Found duplicate mods:\n\tjei")
    assert cause.category == "duplicate_mod"
    assert cause.mods == ["jei"]


def test_generic_exception_falls_back_to_startup_error() -> None:
    log = (
        "[Server thread/ERROR]: Encountered an unexpected exception\n"
        "Caused by: java.lang.NullPointerException: Cannot invoke method on null"
    )
    cause = extract_cause(log)
    assert cause.category == "startup_error"
    assert "NullPointerException" in cause.summary


def test_unknown_when_nothing_matches() -> None:
    cause = extract_cause("[Server thread/INFO]: Loading mods\n[Server thread/INFO]: Preparing")
    assert cause.category == "unknown"
    assert cause.excerpt


def test_mixin_signature_wins_over_generic_exception() -> None:
    log = (
        "Mixin apply for mod lithium failed lithium.mixins.json:Foo from mod lithium\n"
        "Caused by: java.lang.RuntimeException: boom"
    )
    assert extract_cause(log).category == "mixin_apply"


def test_tail_keeps_last_lines() -> None:
    text = "\n".join(f"line{i}" for i in range(50))
    assert tail(text, 5).splitlines() == ["line45", "line46", "line47", "line48", "line49"]
