"""Filter-mod selection + config generation (Mixin Blacklist / Mixin Helper)."""

import json

from app.resolve.mixin_filters import (
    MIXIN_BLACKLIST,
    MIXIN_HELPER,
    generate_filter_config,
    pick_filter_mod,
)


def test_pick_prefers_blacklist_on_fabric_and_quilt() -> None:
    assert pick_filter_mod("fabric", "1.20.1") is MIXIN_BLACKLIST
    assert pick_filter_mod("quilt", "1.19.2") is MIXIN_BLACKLIST
    assert pick_filter_mod("fabric", "1.16.5") is MIXIN_BLACKLIST


def test_pick_helper_on_forge_within_window_only() -> None:
    assert pick_filter_mod("neoforge", "1.21.1") is MIXIN_HELPER
    assert pick_filter_mod("forge", "1.20.1") is MIXIN_HELPER
    assert pick_filter_mod("forge", "1.19.2") is None  # outside Mixin Helper's window
    assert pick_filter_mod("neoforge", "1.20.4") is None


def test_pick_none_beyond_known_windows() -> None:
    assert pick_filter_mod("fabric", "26.1") is None  # post-1.x versions unsupported
    assert pick_filter_mod("unknown", "1.21.1") is None


def test_generate_blacklist_config_schema() -> None:
    generated = generate_filter_config(
        MIXIN_BLACKLIST, {"com.b.mixin.FooMixin", "com.a.mixin.BarMixin"}
    )
    assert generated is not None
    assert generated.path == "config/mixinblacklist.json"
    config = json.loads(generated.content)
    assert config["common"]["mixinClassNames"] == ["com.a.mixin.BarMixin", "com.b.mixin.FooMixin"]
    assert config["common"]["targetClassNames"] == []  # class-name blacklisting only
    assert config["client"] == {"mixinClassNames": [], "targetClassNames": []}


def test_generate_helper_config_schema() -> None:
    generated = generate_filter_config(MIXIN_HELPER, {"com.x.mixin.LevelMixin"})
    assert generated is not None
    assert generated.path == "config/mixinhelper.json"
    config = json.loads(generated.content)
    assert config["enabled"] is True
    assert config["blacklist"]["mixins"] == ["com.x.mixin.LevelMixin"]
    # the per-mixin priorities map is dead config upstream: never emitted
    assert "priorities" not in config


def test_generate_returns_none_for_empty_set() -> None:
    assert generate_filter_config(MIXIN_BLACKLIST, set()) is None
