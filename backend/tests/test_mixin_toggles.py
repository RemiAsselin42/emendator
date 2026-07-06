"""Mod-own mixin toggle detection (CaffeineMC-style / Debugify) + generation."""

import io
import json
import struct
import zipfile

from app.analyzer.detectors import MixinToggleSystem
from app.analyzer.mods import _collect_mixin_targets, _toggle_key
from app.resolve.mixin_toggles import generate_mixin_toggles, togglable_classes


# minimal class file: just a constant pool carrying the given utf8 strings
def _class_with_strings(*strings: str) -> bytes:
    pool = b""
    count = 1
    for text in strings:
        encoded = text.encode("utf-8")
        pool += struct.pack(">BH", 1, len(encoded)) + encoded
        count += 1
    this_utf8 = b"PluginClass"
    pool += struct.pack(">BH", 1, len(this_utf8)) + this_utf8
    pool += struct.pack(">BH", 7, count)  # Class -> the utf8 above
    obj_utf8 = b"java/lang/Object"
    pool += struct.pack(">BH", 1, len(obj_utf8)) + obj_utf8
    pool += struct.pack(">BH", 7, count + 2)
    header = b"\xca\xfe\xba\xbe" + struct.pack(">HH", 0, 52)
    body = struct.pack(">HHHH", 0x0001, count + 1, count + 3, 0)  # access/this/super/ifaces
    body += struct.pack(">HHH", 0, 0, 0)  # fields, methods, attributes
    return header + struct.pack(">H", count + 4) + pool + body


def _mixin_class_bytes() -> bytes:
    # reuse the string-pool builder: extract_mixin_targets tolerates plain classes
    return _class_with_strings("unused")


def _jar(entries: dict[str, bytes | str]) -> zipfile.ZipFile:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return zipfile.ZipFile(io.BytesIO(buffer.getvalue()))


def test_detects_caffeinemc_properties_system() -> None:
    config = {
        "package": "net.caffeinemc.mods.lithium.mixin",
        "plugin": "net.caffeinemc.mods.lithium.mixin.LithiumMixinPlugin",
        "mixins": ["alloc.composter.ComposterMixin"],
    }
    with _jar(
        {
            "lithium.mixins.json": json.dumps(config),
            "net/caffeinemc/mods/lithium/mixin/LithiumMixinPlugin.class": _class_with_strings(
                "./config/lithium.properties"
            ),
            "net/caffeinemc/mods/lithium/mixin/alloc/composter/ComposterMixin.class": (
                _mixin_class_bytes()
            ),
        }
    ) as zf:
        result = _collect_mixin_targets(zf, zf.namelist())

    assert result.toggles is not None
    assert result.toggles.kind == "properties"
    assert result.toggles.file == "config/lithium.properties"
    full = "net.caffeinemc.mods.lithium.mixin.alloc.composter.ComposterMixin"
    assert result.toggles.keys == {full: "mixin.alloc.composter"}


def test_no_toggle_system_without_properties_constant() -> None:
    config = {
        "package": "com.example.mixin",
        "plugin": "com.example.mixin.Plugin",
        "mixins": ["foo.BarMixin"],
    }
    with _jar(
        {
            "example.mixins.json": json.dumps(config),
            "com/example/mixin/Plugin.class": _class_with_strings("just/a/string"),
            "com/example/mixin/foo/BarMixin.class": _mixin_class_bytes(),
        }
    ) as zf:
        result = _collect_mixin_targets(zf, zf.namelist())
    assert result.toggles is None


def test_debugify_keys_from_package_bug_id() -> None:
    assert (
        _toggle_key(
            "debugify",
            "basic.mc100991.FishingHookMixin",
            "dev.isxander.debugify.mixins.basic.mc100991.FishingHookMixin",
        )
        == "MC-100991"
    )
    # root-package class in a properties system has no per-package key
    assert _toggle_key("properties", "RootMixin", "a.b.RootMixin") is None
    assert _toggle_key("properties", "alloc.composter.ComposterMixin", "x") == (
        "mixin.alloc.composter"
    )


def test_generate_properties_toggle_file() -> None:
    system = MixinToggleSystem(
        kind="properties",
        file="config/lithium.properties",
        keys={
            "a.mixin.alloc.composter.ComposterMixin": "mixin.alloc.composter",
            "a.mixin.ai.pathing.PathMixin": "mixin.ai.pathing",
        },
    )
    generated = generate_mixin_toggles(
        system, {"a.mixin.alloc.composter.ComposterMixin", "a.mixin.ai.pathing.PathMixin"}
    )
    assert generated is not None
    assert generated.path == "config/lithium.properties"
    assert "mixin.ai.pathing=false\n" in generated.content
    assert "mixin.alloc.composter=false\n" in generated.content
    assert generated.content.startswith("#")  # header comment


def test_generate_debugify_toggle_file() -> None:
    system = MixinToggleSystem(
        kind="debugify",
        file="config/debugify.json",
        keys={"dev.isxander.debugify.mixins.basic.mc100991.FishingHookMixin": "MC-100991"},
    )
    generated = generate_mixin_toggles(
        system, {"dev.isxander.debugify.mixins.basic.mc100991.FishingHookMixin"}
    )
    assert generated is not None
    assert json.loads(generated.content) == {"MC-100991": False}


def test_generate_returns_none_without_coverage() -> None:
    system = MixinToggleSystem(kind="properties", file="config/x.properties", keys={})
    assert generate_mixin_toggles(system, {"a.B"}) is None
    assert togglable_classes(system, {"a.B"}) == set()
    assert togglable_classes(None, {"a.B"}) == set()
