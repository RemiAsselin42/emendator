"""Extract ``@Mixin`` target classes from a compiled mixin ``.class`` file.

Mixin configs (``*.mixins.json``) only list mixin *class names*, never their
targets. The targets live in the ``@Mixin(value = {...}, targets = {...})``
annotation baked into each mixin class's bytecode. This is the only static
signal for "which vanilla class does this mod patch", so the mixin_overlap
detector parses just enough of the Java class file to read that annotation.

This is a deliberately minimal class-file reader (JVMS §4): it walks the
constant pool, skips fields/methods, and decodes the class-level annotation
attributes. Anything unexpected yields an empty set rather than raising.
"""

import struct

_MIXIN_DESCRIPTOR = "Lorg/spongepowered/asm/mixin/Mixin;"
_MAGIC = 0xCAFEBABE


def _descriptor_to_class(descriptor: str) -> str | None:
    """``Lnet/minecraft/server/MinecraftServer;`` -> dotted class name."""
    if descriptor.startswith("L") and descriptor.endswith(";"):
        return descriptor[1:-1].replace("/", ".")
    return None


class _ClassFile:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.off = 0
        self.utf8: dict[int, str] = {}
        self._parse_until_class_attributes()

    def _u1(self) -> int:
        value = self.data[self.off]
        self.off += 1
        return value

    def _u2(self) -> int:
        (value,) = struct.unpack_from(">H", self.data, self.off)
        self.off += 2
        return value

    def _u4(self) -> int:
        (value,) = struct.unpack_from(">I", self.data, self.off)
        self.off += 4
        return value

    def _parse_until_class_attributes(self) -> None:
        if self._u4() != _MAGIC:
            raise ValueError("not a class file")
        self._u2()  # minor
        self._u2()  # major
        self._parse_constant_pool()
        self.off += 6  # access_flags, this_class, super_class
        # NB: keep the read separate — `self.off += 2 * self._u2()` would clobber
        # the read's own offset advance (augmented-assignment reads the target first).
        interfaces_count = self._u2()
        self.off += 2 * interfaces_count
        self._skip_members()  # fields
        self._skip_members()  # methods
        # self.off now sits at the class-level attributes_count.

    def _parse_constant_pool(self) -> None:
        count = self._u2()
        index = 1
        while index < count:
            tag = self._u1()
            if tag == 1:  # Utf8
                length = self._u2()
                self.utf8[index] = self.data[self.off : self.off + length].decode(
                    "utf-8", "replace"
                )
                self.off += length
            elif tag in (7, 8, 16, 19, 20):  # Class, String, MethodType, Module, Package
                self.off += 2
            elif tag == 15:  # MethodHandle
                self.off += 3
            elif tag in (3, 4, 9, 10, 11, 12, 17, 18):  # Int/Float/refs/NameAndType/(Invoke)Dynamic
                self.off += 4
            elif tag in (5, 6):  # Long / Double occupy two pool slots
                self.off += 8
                index += 1
            else:
                raise ValueError(f"unknown constant pool tag {tag}")
            index += 1

    def _skip_members(self) -> None:
        for _ in range(self._u2()):
            self.off += 6  # access_flags, name_index, descriptor_index
            for _ in range(self._u2()):  # attributes
                self.off += 2  # attribute_name_index
                # Separate read: `self.off += self._u4()` would discard the read's
                # own 4-byte advance (augmented assignment evaluates the target first).
                length = self._u4()
                self.off += length

    def mixin_targets(self) -> set[str]:
        targets: set[str] = set()
        for _ in range(self._u2()):  # class attributes_count
            name = self.utf8.get(self._u2(), "")
            length = self._u4()
            end = self.off + length
            if name in ("RuntimeVisibleAnnotations", "RuntimeInvisibleAnnotations"):
                self._parse_annotations(targets)
            self.off = end
        return targets

    def _parse_annotations(self, targets: set[str]) -> None:
        for _ in range(self._u2()):
            self._parse_annotation(targets)

    def _parse_annotation(self, targets: set[str]) -> None:
        is_mixin = self.utf8.get(self._u2()) == _MIXIN_DESCRIPTOR
        for _ in range(self._u2()):  # element_value_pairs
            element_name = self.utf8.get(self._u2(), "")
            self._parse_element_value(targets if is_mixin else None, element_name)

    def _parse_element_value(self, targets: set[str] | None, element_name: str) -> None:
        tag = chr(self._u1())
        if tag in "BCDFIJSZs":  # primitive or String constant
            index = self._u2()
            if targets is not None and element_name == "targets" and tag == "s":
                value = self.utf8.get(index)
                if value:
                    targets.add(value.replace("/", "."))
        elif tag == "e":  # enum
            self.off += 4
        elif tag == "c":  # class
            index = self._u2()
            if targets is not None and element_name == "value":
                descriptor = self.utf8.get(index)
                resolved = _descriptor_to_class(descriptor) if descriptor else None
                if resolved:
                    targets.add(resolved)
        elif tag == "@":  # nested annotation
            self._parse_annotation(set())
        elif tag == "[":  # array
            for _ in range(self._u2()):
                self._parse_element_value(targets, element_name)
        else:
            raise ValueError(f"unknown element_value tag {tag!r}")


def extract_mixin_targets(class_bytes: bytes) -> set[str]:
    """Dotted target class names from a mixin's ``@Mixin`` annotation.

    Returns an empty set for non-mixin classes or anything we fail to parse —
    this is a best-effort heuristic, never a hard failure.
    """
    try:
        return _ClassFile(class_bytes).mixin_targets()
    except (ValueError, IndexError, struct.error):
        return set()
