"""Extract mixin targets from a compiled mixin ``.class`` file.

Mixin configs only list mixin class names; the real targets live in bytecode:

- the class-level ``@Mixin(value = {...}, targets = {...})`` — *which* vanilla
  classes the mixin patches, and
- each method's injector annotation (``@Inject``/``@Redirect``/``@ModifyArg``…)
  ``method = {...}`` — *which methods* inside those classes it touches.

The first gives class-level overlap (runtime-confirmable via the mixin export);
the second sharpens it: two mods touching the same *method* of the same class
are a much stronger conflict candidate than two merely sharing a class.

This is a deliberately minimal class-file reader (JVMS §4): walk the constant
pool, the methods (for injector annotations) and the class attributes (for
``@Mixin``). Anything unexpected yields empty results rather than raising.
"""

import struct
from dataclasses import dataclass, field

_MAGIC = 0xCAFEBABE
_MIXIN_DESCRIPTOR = "Lorg/spongepowered/asm/mixin/Mixin;"
# Injector annotations whose ``method`` element names the patched target methods.
_INJECTOR_DESCRIPTORS = {
    "Lorg/spongepowered/asm/mixin/injection/Inject;",
    "Lorg/spongepowered/asm/mixin/injection/Redirect;",
    "Lorg/spongepowered/asm/mixin/injection/ModifyArg;",
    "Lorg/spongepowered/asm/mixin/injection/ModifyArgs;",
    "Lorg/spongepowered/asm/mixin/injection/ModifyVariable;",
    "Lorg/spongepowered/asm/mixin/injection/ModifyConstant;",
}
_ANNOTATION_ATTRS = ("RuntimeVisibleAnnotations", "RuntimeInvisibleAnnotations")


@dataclass
class MixinTargets:
    """Targets declared by one mixin class."""

    classes: set[str] = field(default_factory=set)
    # "<dotted target class>#<method name>" pairs, when both are known.
    methods: set[str] = field(default_factory=set)


def _descriptor_to_class(descriptor: str) -> str | None:
    if descriptor.startswith("L") and descriptor.endswith(";"):
        return descriptor[1:-1].replace("/", ".")
    return None


def _method_name(selector: str) -> str:
    """``method_123(Lnet/…;)V`` / ``Lnet/…;tick(...)`` -> bare method name."""
    name = selector.split("(", 1)[0]
    if ";" in name:
        name = name.rsplit(";", 1)[1]
    return name


class _ClassFile:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.off = 0
        self.utf8: dict[int, str] = {}
        self.class_targets: set[str] = set()
        self.method_selectors: set[str] = set()
        self._parse()

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

    def _parse(self) -> None:
        if self._u4() != _MAGIC:
            raise ValueError("not a class file")
        self.off += 4  # minor + major
        self._parse_constant_pool()
        self.off += 6  # access_flags, this_class, super_class
        # NB: read first — `self.off += 2 * self._u2()` would discard the read's
        # own offset advance (augmented assignment evaluates the target first).
        interfaces_count = self._u2()
        self.off += 2 * interfaces_count
        self._parse_members(is_method=False)  # fields
        self._parse_members(is_method=True)  # methods (injector annotations)
        self._parse_attributes(class_level=True)  # @Mixin

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
            elif tag in (7, 8, 16, 19, 20):
                self.off += 2
            elif tag == 15:
                self.off += 3
            elif tag in (3, 4, 9, 10, 11, 12, 17, 18):
                self.off += 4
            elif tag in (5, 6):
                self.off += 8
                index += 1
            else:
                raise ValueError(f"unknown constant pool tag {tag}")
            index += 1

    def _parse_members(self, is_method: bool) -> None:
        for _ in range(self._u2()):
            self.off += 6  # access_flags, name_index, descriptor_index
            self._parse_attributes(class_level=False, in_method=is_method)

    def _parse_attributes(self, class_level: bool, in_method: bool = False) -> None:
        for _ in range(self._u2()):
            name = self.utf8.get(self._u2(), "")
            length = self._u4()
            end = self.off + length
            if (class_level or in_method) and name in _ANNOTATION_ATTRS:
                self._parse_annotations(class_level)
            self.off = end

    def _parse_annotations(self, class_level: bool) -> None:
        for _ in range(self._u2()):
            self._parse_annotation(class_level)

    def _parse_annotation(self, class_level: bool) -> None:
        descriptor = self.utf8.get(self._u2())
        collect_class = class_level and descriptor == _MIXIN_DESCRIPTOR
        collect_method = (not class_level) and descriptor in _INJECTOR_DESCRIPTORS
        for _ in range(self._u2()):
            element_name = self.utf8.get(self._u2(), "")
            self._parse_element_value(element_name, collect_class, collect_method)

    def _parse_element_value(
        self, element_name: str, collect_class: bool, collect_method: bool
    ) -> None:
        tag = chr(self._u1())
        if tag in "BCDFIJSZs":
            index = self._u2()
            if collect_class and element_name == "targets" and tag == "s":
                value = self.utf8.get(index)
                if value:
                    self.class_targets.add(value.replace("/", "."))
            elif collect_method and element_name == "method" and tag == "s":
                value = self.utf8.get(index)
                if value:
                    self.method_selectors.add(value)
        elif tag == "e":  # enum
            self.off += 4
        elif tag == "c":  # class
            index = self._u2()
            if collect_class and element_name == "value":
                resolved = _descriptor_to_class(self.utf8.get(index, ""))
                if resolved:
                    self.class_targets.add(resolved)
        elif tag == "@":  # nested annotation (e.g. @At) — consume, don't collect
            self._consume_annotation()
        elif tag == "[":  # array
            for _ in range(self._u2()):
                self._parse_element_value(element_name, collect_class, collect_method)
        else:
            raise ValueError(f"unknown element_value tag {tag!r}")

    def _consume_annotation(self) -> None:
        self._u2()  # type index
        for _ in range(self._u2()):
            self._u2()  # element name
            self._parse_element_value("", False, False)


def extract_mixin_targets(class_bytes: bytes) -> MixinTargets:
    """Class targets and ``Class#method`` pairs from a mixin's bytecode.

    Best-effort: returns empty sets for non-mixin classes or parse failures.
    """
    try:
        parsed = _ClassFile(class_bytes)
    except (ValueError, IndexError, struct.error):
        return MixinTargets()

    methods = {
        f"{target}#{_method_name(selector)}"
        for target in parsed.class_targets
        for selector in parsed.method_selectors
    }
    return MixinTargets(classes=parsed.class_targets, methods=methods)
