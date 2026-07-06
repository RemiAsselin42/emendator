"""Hand-assembled class-file fixtures shared by mixin-related tests.

A growable constant pool plus element_value encoders, so each test declares
only the annotations it exercises (JVMS §4 shapes the parser understands).
"""

import struct


class Pool:
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


def anno(pool: Pool, descriptor: str, elements: list[tuple[str, bytes]]) -> bytes:
    out = struct.pack(">HH", pool.utf8(descriptor), len(elements))
    for name, value in elements:
        out += struct.pack(">H", pool.utf8(name)) + value
    return out


def ev_string(pool: Pool, text: str) -> bytes:
    return b"s" + struct.pack(">H", pool.utf8(text))


def ev_class(pool: Pool, dotted: str) -> bytes:
    return b"c" + struct.pack(">H", pool.utf8("L" + dotted.replace(".", "/") + ";"))


def ev_int(pool: Pool, value: int) -> bytes:
    return b"I" + struct.pack(">H", pool.integer(value))


def ev_array(items: list[bytes]) -> bytes:
    return b"[" + struct.pack(">H", len(items)) + b"".join(items)


def ev_anno(annotation: bytes) -> bytes:
    return b"@" + annotation


def mixin_anno(
    pool: Pool,
    *,
    value: str | None = None,
    targets: list[str] | None = None,
    priority: int | None = None,
) -> bytes:
    elements: list[tuple[str, bytes]] = []
    if value is not None:
        elements.append(("value", ev_array([ev_class(pool, value)])))
    if targets is not None:
        elements.append(("targets", ev_array([ev_string(pool, t) for t in targets])))
    if priority is not None:
        elements.append(("priority", ev_int(pool, priority)))
    return anno(pool, "Lorg/spongepowered/asm/mixin/Mixin;", elements)


def assemble(
    pool: Pool, class_annos: list[bytes], methods: list[tuple[str, str, list[bytes]]]
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


def overwrite_class(target_class: str, method: str = "tick") -> bytes:
    """A mixin class @Overwrite-ing ``method`` in ``target_class``."""
    pool = Pool()
    ow = anno(pool, "Lorg/spongepowered/asm/mixin/Overwrite;", [])
    mixin = mixin_anno(pool, value=target_class)
    return assemble(pool, [mixin], [(method, "()V", [ow])])


def strings_class(*strings: str) -> bytes:
    """A minimal class whose constant pool carries the given strings."""
    pool = Pool()
    for text in strings:
        pool.utf8(text)
    return assemble(pool, [], [])
