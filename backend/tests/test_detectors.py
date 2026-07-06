import io
import json
import struct
import zipfile

from app.analyzer.detectors import (
    JarIndex,
    MixinMethodPatch,
    detect_conflicts,
    detect_missing_dependencies,
    detect_mixin_overlaps,
    detect_recipe_collisions,
    detect_tag_overlaps,
)
from app.analyzer.mixin_targets import extract_mixin_targets
from app.analyzer.mods import _collect_mixin_targets
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
    mixin_method_patches: dict[str, MixinMethodPatch] | None = None,
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
        mixin_method_patches=mixin_method_patches or {},
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


def _mixin_index(mod_id: str, target: str, method: str, patch: MixinMethodPatch) -> JarIndex:
    key = f"{target}#{method}"
    return _index(
        mod_id,
        mixin_targets={target},
        mixin_method_targets={key},
        mixin_method_patches={key: patch},
    )


def test_double_overwrite_same_priority_is_error() -> None:
    target = "net.minecraft.server.MinecraftServer"
    indexes = [
        _mixin_index("a", target, "tick", MixinMethodPatch(kinds={"overwrite"})),
        _mixin_index("b", target, "tick", MixinMethodPatch(kinds={"overwrite"})),
    ]
    conflicts = detect_mixin_overlaps(indexes)
    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict.severity == "error"
    entry = conflict.detail["methodDetails"]["tick"]
    assert entry["overwrites"] == ["a", "b"]
    assert entry["priorities"] == {"a": [1000], "b": [1000]}  # Mixin default


def test_double_overwrite_distinct_priorities_stays_warning() -> None:
    target = "net.minecraft.server.MinecraftServer"
    indexes = [
        _mixin_index("a", target, "tick", MixinMethodPatch(kinds={"overwrite"}, priorities={900})),
        _mixin_index("b", target, "tick", MixinMethodPatch(kinds={"overwrite"}, priorities={1100})),
    ]
    conflicts = detect_mixin_overlaps(indexes)
    assert conflicts[0].severity == "warning"  # highest priority silently wins
    assert conflicts[0].detail["methodDetails"]["tick"]["overwrites"] == ["a", "b"]


def test_redirect_same_call_site_is_error() -> None:
    target = "net.minecraft.server.MinecraftServer"
    site = "Lnet/minecraft/world/World;getTime()J"
    indexes = [
        _mixin_index(
            "a", target, "tick", MixinMethodPatch(kinds={"redirect"}, exclusive_at={site})
        ),
        _mixin_index(
            "b", target, "tick", MixinMethodPatch(kinds={"redirect"}, exclusive_at={site})
        ),
    ]
    conflicts = detect_mixin_overlaps(indexes)
    assert conflicts[0].severity == "error"
    assert conflicts[0].detail["methodDetails"]["tick"]["exclusive"] == ["a", "b"]


def test_redirect_different_call_sites_stays_warning() -> None:
    target = "net.minecraft.server.MinecraftServer"
    indexes = [
        _mixin_index(
            "a",
            target,
            "tick",
            MixinMethodPatch(kinds={"redirect"}, exclusive_at={"Lx/Y;a()V"}),
        ),
        _mixin_index(
            "b",
            target,
            "tick",
            MixinMethodPatch(kinds={"redirect"}, exclusive_at={"Lx/Y;b()V"}),
        ),
    ]
    conflicts = detect_mixin_overlaps(indexes)
    # provably different instructions: exclusive kinds can coexist
    assert conflicts[0].severity == "warning"


def test_redirect_unknown_call_site_is_error() -> None:
    target = "net.minecraft.server.MinecraftServer"
    indexes = [
        _mixin_index(
            "a",
            target,
            "tick",
            MixinMethodPatch(kinds={"redirect"}, exclusive_at={"Lx/Y;a()V"}),
        ),
        # no recorded @At target: cannot prove the sites differ
        _mixin_index("b", target, "tick", MixinMethodPatch(kinds={"redirect"})),
    ]
    conflicts = detect_mixin_overlaps(indexes)
    assert conflicts[0].severity == "error"


def test_inject_only_shared_method_stays_warning_with_kinds() -> None:
    target = "net.minecraft.server.MinecraftServer"
    indexes = [
        _mixin_index("a", target, "tick", MixinMethodPatch(kinds={"inject"})),
        _mixin_index("b", target, "tick", MixinMethodPatch(kinds={"wrap_operation"})),
    ]
    conflicts = detect_mixin_overlaps(indexes)
    conflict = conflicts[0]
    assert conflict.severity == "warning"
    assert conflict.detail["methodDetails"]["tick"]["kinds"] == {
        "a": ["inject"],
        "b": ["wrap_operation"],
    }


# --- mixin bytecode parser ------------------------------------------------
# Class files are hand-assembled: a growable constant pool plus element_value
# encoders, so each test declares only the annotations it exercises.


class _Pool:
    def __init__(self) -> None:
        self.entries: list[bytes] = []

    def _add(self, blob: bytes) -> int:
        self.entries.append(blob)
        return len(self.entries)  # the constant pool is 1-based

    def utf8(self, text: str) -> int:
        encoded = text.encode("utf-8")
        return self._add(struct.pack(">BH", 1, len(encoded)) + encoded)

    def integer(self, value: int) -> int:
        return self._add(struct.pack(">Bi", 3, value))

    def klass(self, name: str) -> int:
        return self._add(struct.pack(">BH", 7, self.utf8(name)))


def _anno(pool: _Pool, descriptor: str, elements: list[tuple[str, bytes]]) -> bytes:
    out = struct.pack(">HH", pool.utf8(descriptor), len(elements))
    for name, value in elements:
        out += struct.pack(">H", pool.utf8(name)) + value
    return out


def _ev_string(pool: _Pool, text: str) -> bytes:
    return b"s" + struct.pack(">H", pool.utf8(text))


def _ev_class(pool: _Pool, dotted: str) -> bytes:
    return b"c" + struct.pack(">H", pool.utf8("L" + dotted.replace(".", "/") + ";"))


def _ev_int(pool: _Pool, value: int) -> bytes:
    return b"I" + struct.pack(">H", pool.integer(value))


def _ev_array(items: list[bytes]) -> bytes:
    return b"[" + struct.pack(">H", len(items)) + b"".join(items)


def _ev_anno(anno: bytes) -> bytes:
    return b"@" + anno


def _mixin_anno(
    pool: _Pool,
    *,
    value: str | None = None,
    targets: list[str] | None = None,
    priority: int | None = None,
) -> bytes:
    elements: list[tuple[str, bytes]] = []
    if value is not None:
        elements.append(("value", _ev_array([_ev_class(pool, value)])))
    if targets is not None:
        elements.append(("targets", _ev_array([_ev_string(pool, t) for t in targets])))
    if priority is not None:
        elements.append(("priority", _ev_int(pool, priority)))
    return _anno(pool, "Lorg/spongepowered/asm/mixin/Mixin;", elements)


def _assemble(
    pool: _Pool, class_annos: list[bytes], methods: list[tuple[str, str, list[bytes]]]
) -> bytes:
    """Minimal class file: (name, descriptor, annotations) per method + class annos."""
    this_class = pool.klass("MixinTest")
    super_class = pool.klass("java/lang/Object")
    attr_name = pool.utf8("RuntimeInvisibleAnnotations")

    def anno_attr(annos: list[bytes]) -> bytes:
        payload = struct.pack(">H", len(annos)) + b"".join(annos)
        return struct.pack(">H", attr_name) + struct.pack(">I", len(payload)) + payload

    methods_blob = b""
    for name, descriptor, annos in methods:
        methods_blob += struct.pack(">HHH", 0x0001, pool.utf8(name), pool.utf8(descriptor))
        methods_blob += (struct.pack(">H", 1) + anno_attr(annos)) if annos else struct.pack(">H", 0)

    body = struct.pack(">HHHH", 0x0001, this_class, super_class, 0)  # access/this/super/ifaces
    body += struct.pack(">H", 0)  # fields_count
    body += struct.pack(">H", len(methods)) + methods_blob
    body += (struct.pack(">H", 1) + anno_attr(class_annos)) if class_annos else struct.pack(">H", 0)

    header = b"\xca\xfe\xba\xbe" + struct.pack(">HH", 0, 52)
    return header + struct.pack(">H", len(pool.entries) + 1) + b"".join(pool.entries) + body


def test_extract_mixin_targets_from_bytecode() -> None:
    pool = _Pool()
    inject = _anno(
        pool,
        "Lorg/spongepowered/asm/mixin/injection/Inject;",
        [("method", _ev_array([_ev_string(pool, "tick")]))],
    )
    mixin = _mixin_anno(
        pool, value="net.minecraft.server.MinecraftServer", targets=["net.minecraft.world.World"]
    )
    result = extract_mixin_targets(_assemble(pool, [mixin], [("m", "()V", [inject])]))
    assert result.classes == {
        "net.minecraft.server.MinecraftServer",
        "net.minecraft.world.World",
    }
    # bare selector: each target class paired with the injected method "tick"
    assert "net.minecraft.server.MinecraftServer#tick" in result.methods
    assert "net.minecraft.world.World#tick" in result.methods
    assert [i.kind for i in result.injections] == ["inject"]


def test_extract_overwrite_targets_annotated_method() -> None:
    pool = _Pool()
    overwrite = _anno(pool, "Lorg/spongepowered/asm/mixin/Overwrite;", [])
    mixin = _mixin_anno(pool, value="net.minecraft.server.MinecraftServer")
    result = extract_mixin_targets(_assemble(pool, [mixin], [("tick", "()V", [overwrite])]))
    assert result.methods == {"net.minecraft.server.MinecraftServer#tick"}
    (injection,) = result.injections
    assert injection.kind == "overwrite"
    assert injection.descriptor == "()V"


def test_extract_redirect_at_and_priority() -> None:
    pool = _Pool()
    at = _anno(
        pool,
        "Lorg/spongepowered/asm/mixin/injection/At;",
        [
            ("value", _ev_string(pool, "INVOKE")),
            ("target", _ev_string(pool, "Lnet/minecraft/world/World;getTime()J")),
        ],
    )
    redirect = _anno(
        pool,
        "Lorg/spongepowered/asm/mixin/injection/Redirect;",
        [("method", _ev_array([_ev_string(pool, "tick")])), ("at", _ev_anno(at))],
    )
    mixin = _mixin_anno(pool, value="net.minecraft.server.MinecraftServer", priority=900)
    result = extract_mixin_targets(_assemble(pool, [mixin], [("h", "()V", [redirect])]))
    assert result.priority == 900
    (injection,) = result.injections
    assert injection.kind == "redirect"
    assert injection.at == ("INVOKE",)
    assert injection.at_targets == ("Lnet/minecraft/world/World;getTime()J",)


def test_extract_mixinextras_wrap_operation() -> None:
    pool = _Pool()
    wrap = _anno(
        pool,
        "Lcom/llamalad7/mixinextras/injector/wrapoperation/WrapOperation;",
        [("method", _ev_array([_ev_string(pool, "render")]))],
    )
    mixin = _mixin_anno(pool, value="net.minecraft.client.Minecraft")
    result = extract_mixin_targets(_assemble(pool, [mixin], [("h", "()V", [wrap])]))
    assert result.methods == {"net.minecraft.client.Minecraft#render"}
    assert [i.kind for i in result.injections] == ["wrap_operation"]


def test_extract_owner_scoped_selector_not_cross_product() -> None:
    pool = _Pool()
    inject = _anno(
        pool,
        "Lorg/spongepowered/asm/mixin/injection/Inject;",
        [("method", _ev_array([_ev_string(pool, "Lnet/other/Target;tick(I)V")]))],
    )
    mixin = _mixin_anno(pool, value="net.a.A", targets=["net.b.B"])
    result = extract_mixin_targets(_assemble(pool, [mixin], [("h", "()V", [inject])]))
    # the explicit owner wins: no cross-product over the two @Mixin targets
    assert result.methods == {"net.other.Target#tick"}
    (injection,) = result.injections
    assert injection.owner == "net.other.Target"
    assert injection.descriptor == "(I)V"


def test_extract_mixin_targets_ignores_garbage() -> None:
    result = extract_mixin_targets(b"not a class file")
    assert result.classes == set()
    assert result.methods == set()
    assert result.injections == []


def test_extract_desc_selector_owner_scoped() -> None:
    pool = _Pool()
    desc = _anno(
        pool,
        "Lorg/spongepowered/asm/mixin/injection/Desc;",
        [("owner", _ev_class(pool, "net.other.Target")), ("value", _ev_string(pool, "tick"))],
    )
    inject = _anno(
        pool,
        "Lorg/spongepowered/asm/mixin/injection/Inject;",
        [("target", _ev_array([_ev_anno(desc)]))],
    )
    mixin = _mixin_anno(pool, value="net.a.A")
    result = extract_mixin_targets(_assemble(pool, [mixin], [("h", "()V", [inject])]))
    assert result.methods == {"net.other.Target#tick"}
    (injection,) = result.injections
    assert injection.kind == "inject"
    assert injection.owner == "net.other.Target"


def test_extract_match_all_wildcard_selector_is_skipped() -> None:
    pool = _Pool()
    inject = _anno(
        pool,
        "Lorg/spongepowered/asm/mixin/injection/Inject;",
        [("method", _ev_array([_ev_string(pool, "*")]))],
    )
    mixin = _mixin_anno(pool, value="net.a.A")
    result = extract_mixin_targets(_assemble(pool, [mixin], [("h", "()V", [inject])]))
    assert result.classes == {"net.a.A"}  # class-level info stays
    assert result.methods == set()  # no meaningless "*" method key
    assert result.injections == []


def test_collect_mixin_targets_builds_patches_with_config_priority() -> None:
    pool = _Pool()
    overwrite = _anno(pool, "Lorg/spongepowered/asm/mixin/Overwrite;", [])
    mixin = _mixin_anno(pool, value="net.minecraft.server.MinecraftServer")
    class_bytes = _assemble(pool, [mixin], [("tick", "()V", [overwrite])])

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr(
            "mymod.mixins.json",
            json.dumps(
                {"package": "com.example.mixin", "priority": 1200, "mixins": ["ServerMixin"]}
            ),
        )
        zf.writestr("com/example/mixin/ServerMixin.class", class_bytes)
    with zipfile.ZipFile(io.BytesIO(buffer.getvalue())) as zf:
        result = _collect_mixin_targets(zf, zf.namelist())

    key = "net.minecraft.server.MinecraftServer#tick"
    assert result.methods == {key}
    patch = result.patches[key]
    assert patch.kinds == {"overwrite"}
    assert patch.priorities == {1200}  # config-level priority, no @Mixin override
    assert patch.required is False


def test_collect_mixin_targets_discovers_declared_configs_and_required() -> None:
    pool = _Pool()
    overwrite = _anno(pool, "Lorg/spongepowered/asm/mixin/Overwrite;", [])
    mixin = _mixin_anno(pool, value="net.minecraft.server.MinecraftServer")
    class_bytes = _assemble(pool, [mixin], [("tick", "()V", [overwrite])])

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        # config declared in fabric.mod.json but NOT matching *.mixins.json
        zf.writestr("fabric.mod.json", json.dumps({"id": "m", "mixins": ["custom-config.json"]}))
        zf.writestr(
            "custom-config.json",
            json.dumps(
                {"package": "com.example.mixin", "required": True, "mixins": ["ServerMixin"]}
            ),
        )
        zf.writestr("com/example/mixin/ServerMixin.class", class_bytes)
    with zipfile.ZipFile(io.BytesIO(buffer.getvalue())) as zf:
        result = _collect_mixin_targets(zf, zf.namelist())

    patch = result.patches["net.minecraft.server.MinecraftServer#tick"]
    assert patch.kinds == {"overwrite"}
    assert patch.required is True


def test_collect_mixin_targets_reads_manifest_mixinconfigs() -> None:
    pool = _Pool()
    inject = _anno(
        pool,
        "Lorg/spongepowered/asm/mixin/injection/Inject;",
        [("method", _ev_array([_ev_string(pool, "tick")]))],
    )
    mixin = _mixin_anno(pool, value="net.minecraft.server.MinecraftServer")
    class_bytes = _assemble(pool, [mixin], [("h", "()V", [inject])])

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr(
            "META-INF/MANIFEST.MF",
            "Manifest-Version: 1.0\r\nMixinConfigs: forgemod.custom.json\r\n",
        )
        zf.writestr(
            "forgemod.custom.json",
            json.dumps({"package": "com.example.mixin", "mixins": ["ServerMixin"]}),
        )
        zf.writestr("com/example/mixin/ServerMixin.class", class_bytes)
    with zipfile.ZipFile(io.BytesIO(buffer.getvalue())) as zf:
        result = _collect_mixin_targets(zf, zf.namelist())

    assert result.methods == {"net.minecraft.server.MinecraftServer#tick"}


def test_required_mods_surface_in_method_details() -> None:
    target = "net.minecraft.server.MinecraftServer"
    indexes = [
        _mixin_index("a", target, "tick", MixinMethodPatch(kinds={"overwrite"}, required=True)),
        _mixin_index("b", target, "tick", MixinMethodPatch(kinds={"overwrite"})),
    ]
    conflicts = detect_mixin_overlaps(indexes)
    assert conflicts[0].detail["methodDetails"]["tick"]["requiredBy"] == ["a"]
