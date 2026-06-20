import struct

from app.analyzer.detectors import (
    JarIndex,
    detect_conflicts,
    detect_missing_dependencies,
    detect_mixin_overlaps,
    detect_recipe_collisions,
    detect_tag_overlaps,
)
from app.analyzer.mixin_targets import extract_mixin_targets
from app.models import Mod
from app.profile import get_profile

PROFILE = get_profile("1.21.1")


def _index(
    mod_id: str,
    *,
    jar: str | None = None,
    environment: str = "*",
    depends: dict | None = None,
    provides: list[str] | None = None,
    recipes: dict | None = None,
    item_tags: dict | None = None,
    mixin_targets: set[str] | None = None,
    mixin_method_targets: set[str] | None = None,
) -> JarIndex:
    mod = Mod(
        id=mod_id,
        environment=environment,  # type: ignore[arg-type]
        depends=depends or {},
        provides=provides or [],
        jar=jar or f"{mod_id}.jar",
    )
    return JarIndex(
        jar=mod.jar,
        mod=mod,
        sha256="0" * 64,
        recipes=recipes or {},
        item_tags=item_tags or {},
        mixin_targets=mixin_targets or set(),
        mixin_method_targets=mixin_method_targets or set(),
    )


def test_duplicate_jar_detected_and_sorted_first() -> None:
    indexes = [_index("dup", jar="a.jar"), _index("dup", jar="b.jar")]
    conflicts = detect_conflicts(indexes, PROFILE)
    assert len(conflicts) == 1
    c = conflicts[0]
    assert c.type == "duplicate_jar"
    assert c.severity == "error"
    assert c.detail["jars"] == ["a.jar", "b.jar"]


def test_missing_dependency() -> None:
    indexes = [_index("a", depends={"b": "*", "minecraft": "1.21.1"})]
    conflicts = detect_missing_dependencies(indexes)
    assert len(conflicts) == 1
    assert conflicts[0].detail == {"mod": "a", "missing": "b"}


def test_dependency_satisfied_by_provides_and_env() -> None:
    indexes = [
        _index("a", depends={"fabric-api-base": "*", "minecraft": "*", "fabricloader": "*"}),
        _index("fabric-api", provides=["fabric-api-base", "fabric"]),
    ]
    assert detect_missing_dependencies(indexes) == []


def test_tag_overlap_two_mods_same_c_tag() -> None:
    indexes = [
        _index(
            "moda",
            item_tags={"data/c/tags/items/ingots/tin.json": {"values": ["moda:tin_ingot"]}},
        ),
        _index(
            "modb",
            item_tags={"data/c/tags/items/ingots/tin.json": {"values": ["modb:tin_ingot"]}},
        ),
    ]
    conflicts = detect_tag_overlaps(indexes, PROFILE)
    assert len(conflicts) == 1
    assert conflicts[0].detail["tag"] == "c:ingots/tin"
    assert conflicts[0].members == ["moda", "modb"]
    assert conflicts[0].detail["items"] == ["moda:tin_ingot", "modb:tin_ingot"]


def test_tag_overlap_ignores_single_contributor_and_non_c_namespace() -> None:
    indexes = [
        _index("a", item_tags={"data/c/tags/items/ingots/tin.json": {"values": ["a:tin"]}}),
        _index(
            "b",
            item_tags={"data/minecraft/tags/items/planks.json": {"values": ["b:plank"]}},
        ),
    ]
    assert detect_tag_overlaps(indexes, PROFILE) == []


def test_recipe_collision_same_id() -> None:
    indexes = [
        _index("a", recipes={"data/minecraft/recipe/torch.json": {"type": "minecraft:crafting"}}),
        _index("b", recipes={"data/minecraft/recipe/torch.json": {"type": "minecraft:crafting"}}),
    ]
    conflicts = detect_recipe_collisions(indexes, PROFILE)
    assert len(conflicts) == 1
    assert conflicts[0].detail["recipe"] == "minecraft:torch"
    assert conflicts[0].members == ["a", "b"]


def test_recipe_no_collision_distinct_ids() -> None:
    indexes = [
        _index("a", recipes={"data/a/recipe/x.json": {}}),
        _index("b", recipes={"data/b/recipe/x.json": {}}),
    ]
    assert detect_recipe_collisions(indexes, PROFILE) == []


def test_mixin_overlap_class_only_is_info() -> None:
    target = "net.minecraft.class_310"
    indexes = [
        _index("a", mixin_targets={target}),
        _index("b", mixin_targets={target, "net.minecraft.class_2960"}),
    ]
    conflicts = detect_mixin_overlaps(indexes)
    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict.detail["target"] == target
    assert conflict.severity == "info"
    assert "sharedMethods" not in conflict.detail
    assert conflict.members == ["a", "b"]


def test_mixin_overlap_shared_method_is_warning() -> None:
    target = "net.minecraft.class_310"
    indexes = [
        _index("a", mixin_targets={target}, mixin_method_targets={f"{target}#tick"}),
        _index(
            "b",
            mixin_targets={target},
            mixin_method_targets={f"{target}#tick", f"{target}#render"},
        ),
    ]
    conflicts = detect_mixin_overlaps(indexes)
    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict.severity == "warning"
    assert conflict.detail["sharedMethods"] == ["tick"]  # render is only in b
    assert conflict.members == ["a", "b"]


# --- mixin bytecode parser ------------------------------------------------


def _utf8(text: str) -> bytes:
    encoded = text.encode("utf-8")
    return struct.pack(">BH", 1, len(encoded)) + encoded


def _build_mixin_class(class_target: str, string_target: str, method_target: str = "tick") -> bytes:
    """Hand-build a mixin class: class-level @Mixin(value, targets) plus a method
    carrying @Inject(method={...}) — exercising both class- and method-level parsing."""
    descriptor = "L" + class_target.replace(".", "/") + ";"
    pool = b"".join(
        [
            _utf8("MixinTest"),  # #1
            struct.pack(">BH", 7, 1),  # #2 Class -> #1
            _utf8("java/lang/Object"),  # #3
            struct.pack(">BH", 7, 3),  # #4 Class -> #3
            _utf8("RuntimeInvisibleAnnotations"),  # #5
            _utf8("Lorg/spongepowered/asm/mixin/Mixin;"),  # #6
            _utf8("value"),  # #7
            _utf8(descriptor),  # #8
            _utf8("targets"),  # #9
            _utf8(string_target),  # #10
            _utf8("m"),  # #11 method name
            _utf8("()V"),  # #12 method descriptor
            _utf8("Code"),  # #13
            _utf8("RuntimeVisibleAnnotations"),  # #14
            _utf8("Lorg/spongepowered/asm/mixin/injection/Inject;"),  # #15
            _utf8("method"),  # #16
            _utf8(method_target),  # #17
        ]
    )
    constant_pool_count = struct.pack(">H", 18)

    # class-level @Mixin(value={class}, targets={"string"})
    mixin = struct.pack(">HH", 6, 2)
    mixin += struct.pack(">H", 7) + b"[" + struct.pack(">H", 1) + b"c" + struct.pack(">H", 8)
    mixin += struct.pack(">H", 9) + b"[" + struct.pack(">H", 1) + b"s" + struct.pack(">H", 10)
    class_annos = struct.pack(">H", 1) + mixin
    class_attr = struct.pack(">H", 5) + struct.pack(">I", len(class_annos)) + class_annos

    # method-level @Inject(method={"<method_target>"})
    inject = struct.pack(">HH", 15, 1)
    inject += struct.pack(">H", 16) + b"[" + struct.pack(">H", 1) + b"s" + struct.pack(">H", 17)
    method_annos = struct.pack(">H", 1) + inject
    method_anno_attr = struct.pack(">H", 14) + struct.pack(">I", len(method_annos)) + method_annos
    code_attr = struct.pack(">H", 13) + struct.pack(">I", 4) + b"\x00\x01\x02\x03"
    method = struct.pack(">HHH", 0x0001, 11, 12)  # access, name #11, descriptor #12
    method += struct.pack(">H", 2) + code_attr + method_anno_attr  # two attributes

    body = b"\xca\xfe\xba\xbe" + struct.pack(">HH", 0, 52)
    body += constant_pool_count + pool
    body += struct.pack(">H", 0x0001)  # access_flags
    body += struct.pack(">H", 2)  # this_class
    body += struct.pack(">H", 4)  # super_class
    body += struct.pack(">H", 0)  # interfaces_count
    body += struct.pack(">H", 0)  # fields_count
    body += struct.pack(">H", 1) + method  # methods_count + the method
    body += struct.pack(">H", 1) + class_attr  # attributes_count + class annotations
    return body


def test_extract_mixin_targets_from_bytecode() -> None:
    targets = _build_mixin_class(
        "net.minecraft.server.MinecraftServer", "net.minecraft.world.World"
    )
    result = extract_mixin_targets(targets)
    assert result.classes == {
        "net.minecraft.server.MinecraftServer",
        "net.minecraft.world.World",
    }
    # method-level: each target class paired with the injected method "tick"
    assert "net.minecraft.server.MinecraftServer#tick" in result.methods
    assert "net.minecraft.world.World#tick" in result.methods


def test_extract_mixin_targets_ignores_garbage() -> None:
    result = extract_mixin_targets(b"not a class file")
    assert result.classes == set()
    assert result.methods == set()
