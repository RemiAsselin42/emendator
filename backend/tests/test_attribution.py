"""Mixin attribution from captured boot output (verbose log + stack frames)."""

from app.runner.attribution import mods_in_stack_frames, parse_mixin_applications

_VERBOSE_LOG = """\
[main/INFO] Mixing common.RendererMixin from sodium.mixins.json into net.minecraft.class_761
[main/INFO] Mixing alloc.MixinChunk from lithium.mixins.json into net.minecraft.class_2818
[main/INFO] Mixing common.RendererMixin from sodium.mixins.json into net.minecraft.class_761
[main/ERROR] Mixin apply for mod lithium failed lithium.mixins.json:alloc.MixinChunk \
from mod lithium
"""


def test_parse_mixin_applications_dedupes_and_attributes() -> None:
    applications = parse_mixin_applications(_VERBOSE_LOG)
    assert len(applications) == 2  # duplicate Mixing line collapsed
    by_config = {a.config: a for a in applications}
    sodium = by_config["sodium.mixins.json"]
    assert sodium.mixin_class == "common.RendererMixin"
    assert sodium.target_class == "net.minecraft.class_761"
    assert sodium.mod is None  # no "from mod" annotation for sodium in this log
    lithium = by_config["lithium.mixins.json"]
    assert lithium.mod == "lithium"  # attributed via the error-line annotation


def test_parse_mixin_applications_empty_log() -> None:
    assert parse_mixin_applications("") == []


_STACK_TRACE = """\
java.lang.NullPointerException: boom
\tat net.minecraft.class_761.handler$zzn000$sodium$onRender(class_761.java:123)
\tat net.minecraft.class_761.method_22710(class_761.java:456)
\tat me.jellysquid.mods.lithium.common.LithiumHelper.tick(LithiumHelper.java:7)
"""


def test_mods_in_stack_frames_blames_synthetic_handlers_only() -> None:
    known = {"sodium", "lithium", "createmod"}
    # "sodium" appears in a synthetic $-segment: blamed. "lithium" only appears
    # as a package segment (no $): not blamed — packages are not proof of a
    # mixin handler in the trace.
    assert mods_in_stack_frames(_STACK_TRACE, known) == ["sodium"]


def test_mods_in_stack_frames_requires_known_ids() -> None:
    assert mods_in_stack_frames(_STACK_TRACE, set()) == []
    # an unknown $-segment never produces a blame
    assert mods_in_stack_frames(_STACK_TRACE, {"othermod"}) == []
