"""Extract mixin targets from a compiled mixin ``.class`` file.

Mixin configs only list mixin class names; the real targets live in bytecode:

- the class-level ``@Mixin(value = {...}, targets = {...}, priority = ...)`` —
  *which* vanilla classes the mixin patches, and who wins on collisions, and
- each method's injector annotation (``@Inject``/``@Redirect``/``@Overwrite``/
  MixinExtras' ``@WrapOperation``…) — *which methods* inside those classes it
  touches, *how* (the kind decides whether two mods can coexist), and *where*
  (the ``@At`` injection point).

Class-level overlap gives the coarse signal (runtime-confirmable via the mixin
export); the per-method :class:`MixinInjection` records sharpen it: two mods
``@Overwrite``-ing the same method are guaranteed incompatible, two
``@Redirect``-ing the same call site cannot coexist, while two ``@Inject`` at
the tail usually can.

This is a deliberately minimal class-file reader (JVMS §4): walk the constant
pool, the methods (for injector annotations) and the class attributes (for
``@Mixin``). Anything unexpected yields empty results rather than raising.
"""

import struct
from dataclasses import dataclass, field
from typing import Any

_MAGIC = 0xCAFEBABE
_MIXIN_DESCRIPTOR = "Lorg/spongepowered/asm/mixin/Mixin;"
_OVERWRITE_DESCRIPTOR = "Lorg/spongepowered/asm/mixin/Overwrite;"
_DESC_DESCRIPTOR = "Lorg/spongepowered/asm/mixin/injection/Desc;"
# Injector annotations whose ``method`` element names the patched target
# methods, mapped to a stable kind. Vanilla Mixin plus MixinExtras — bundled by
# every modern loader, so its injectors are just as conflict-relevant.
_INJECTOR_KINDS = {
    "Lorg/spongepowered/asm/mixin/injection/Inject;": "inject",
    "Lorg/spongepowered/asm/mixin/injection/Redirect;": "redirect",
    "Lorg/spongepowered/asm/mixin/injection/ModifyArg;": "modify_arg",
    "Lorg/spongepowered/asm/mixin/injection/ModifyArgs;": "modify_args",
    "Lorg/spongepowered/asm/mixin/injection/ModifyVariable;": "modify_variable",
    "Lorg/spongepowered/asm/mixin/injection/ModifyConstant;": "modify_constant",
    "Lcom/llamalad7/mixinextras/injector/ModifyExpressionValue;": "modify_expression_value",
    "Lcom/llamalad7/mixinextras/injector/ModifyReceiver;": "modify_receiver",
    "Lcom/llamalad7/mixinextras/injector/ModifyReturnValue;": "modify_return_value",
    "Lcom/llamalad7/mixinextras/injector/WrapWithCondition;": "wrap_with_condition",
    "Lcom/llamalad7/mixinextras/injector/v2/WrapWithCondition;": "wrap_with_condition",
    "Lcom/llamalad7/mixinextras/injector/wrapmethod/WrapMethod;": "wrap_method",
    "Lcom/llamalad7/mixinextras/injector/wrapoperation/WrapOperation;": "wrap_operation",
}
_ANNOTATION_ATTRS = ("RuntimeVisibleAnnotations", "RuntimeInvisibleAnnotations")

# Mixin's default when neither the annotation nor the config sets one.
DEFAULT_PRIORITY = 1000
# Kinds that claim exclusive ownership of the *instruction* they patch: two
# mods doing so at the same site cannot coexist, unlike chainable @Inject /
# MixinExtras @Wrap* handlers. (@Overwrite is exclusive at method level and is
# handled separately by the detector.)
INSTRUCTION_EXCLUSIVE_KINDS = frozenset({"redirect", "modify_constant"})


@dataclass(frozen=True)
class MixinInjection:
    """One injector-annotated handler method inside a mixin class."""

    kind: str  # "inject" | "redirect" | "overwrite" | "wrap_operation" | ...
    method: str  # bare target method name (wildcard selectors kept verbatim)
    descriptor: str | None = None  # explicit ``(…)…`` descriptor when the selector had one
    owner: str | None = None  # explicit dotted target class when the selector had one
    at: tuple[str, ...] = ()  # ``@At`` values (``HEAD``, ``INVOKE``, ...)
    at_targets: tuple[str, ...] = ()  # ``@At`` target member selectors


@dataclass
class MixinTargets:
    """Targets declared by one mixin class."""

    classes: set[str] = field(default_factory=set)
    # "<dotted target class>#<method name>" pairs, when both are known.
    methods: set[str] = field(default_factory=set)
    # ``@Mixin(priority = ...)`` when present (Mixin defaults to 1000).
    priority: int | None = None
    injections: list[MixinInjection] = field(default_factory=list)


def _descriptor_to_class(descriptor: str) -> str | None:
    if descriptor.startswith("L") and descriptor.endswith(";"):
        return descriptor[1:-1].replace("/", ".")
    return None


def _split_selector(selector: str) -> tuple[str | None, str, str | None]:
    """``Lnet/x/Y;tick(I)V`` -> ``("net.x.Y", "tick", "(I)V")``; ``tick`` -> owner/desc None."""
    owner = None
    rest = selector
    if rest.startswith("L") and ";" in rest:
        owner_part, rest = rest.split(";", 1)
        owner = owner_part[1:].replace("/", ".")
    name, paren, descriptor = rest.partition("(")
    return owner, name, f"({descriptor}" if paren else None


_Annotation = tuple[str | None, dict[str, Any]]


class _ClassFile:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.off = 0
        self.utf8: dict[int, str] = {}
        self.ints: dict[int, int] = {}
        self.class_annotations: list[_Annotation] = []
        # (method name, method descriptor, its annotations)
        self.method_annotations: list[tuple[str, str, list[_Annotation]]] = []
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
        self.class_annotations = self._parse_attributes(collect=True)  # @Mixin

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
            elif tag == 3:  # Integer (e.g. @Mixin priority)
                (self.ints[index],) = struct.unpack_from(">i", self.data, self.off)
                self.off += 4
            elif tag in (7, 8, 16, 19, 20):
                self.off += 2
            elif tag == 15:
                self.off += 3
            elif tag in (4, 9, 10, 11, 12, 17, 18):
                self.off += 4
            elif tag in (5, 6):
                self.off += 8
                index += 1
            else:
                raise ValueError(f"unknown constant pool tag {tag}")
            index += 1

    def _parse_members(self, is_method: bool) -> None:
        for _ in range(self._u2()):
            self.off += 2  # access_flags
            name = self.utf8.get(self._u2(), "")
            descriptor = self.utf8.get(self._u2(), "")
            annotations = self._parse_attributes(collect=is_method)
            if is_method and annotations:
                self.method_annotations.append((name, descriptor, annotations))

    def _parse_attributes(self, collect: bool) -> list[_Annotation]:
        collected: list[_Annotation] = []
        for _ in range(self._u2()):
            name = self.utf8.get(self._u2(), "")
            length = self._u4()
            end = self.off + length
            if collect and name in _ANNOTATION_ATTRS:
                collected.extend(self._parse_annotation() for _ in range(self._u2()))
            self.off = end  # resync — annotation parsing stays inside the attribute
        return collected

    def _parse_annotation(self) -> _Annotation:
        descriptor = self.utf8.get(self._u2())
        elements: dict[str, Any] = {}
        for _ in range(self._u2()):
            name = self.utf8.get(self._u2(), "")
            elements[name] = self._parse_element_value()
        return descriptor, elements

    def _parse_element_value(self) -> Any:
        tag = chr(self._u1())
        if tag == "s":
            return self.utf8.get(self._u2())
        if tag in "BCIJSZDF":  # primitive constants; only Integers are kept
            return self.ints.get(self._u2())
        if tag == "e":  # enum: type descriptor + constant name
            self.off += 2
            return self.utf8.get(self._u2())
        if tag == "c":  # class: return the raw descriptor string
            return self.utf8.get(self._u2())
        if tag == "@":  # nested annotation (e.g. @At)
            return self._parse_annotation()
        if tag == "[":
            return [self._parse_element_value() for _ in range(self._u2())]
        raise ValueError(f"unknown element_value tag {tag!r}")


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _flatten_at(value: Any) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """``at`` element (one ``@At`` or an array of them) -> (values, targets)."""
    values: list[str] = []
    targets: list[str] = []
    for anno in _as_list(value):
        if not (isinstance(anno, tuple) and len(anno) == 2):
            continue
        elements = anno[1]
        at_value = elements.get("value")
        if isinstance(at_value, str):
            values.append(at_value)
        at_target = elements.get("target")
        if isinstance(at_target, str):
            targets.append(at_target)
    return tuple(values), tuple(targets)


def _class_targets(annotations: list[_Annotation]) -> tuple[set[str], int | None]:
    """``@Mixin`` target classes (dotted) and explicit priority, if any."""
    classes: set[str] = set()
    priority: int | None = None
    for descriptor, elements in annotations:
        if descriptor != _MIXIN_DESCRIPTOR:
            continue
        for target in _as_list(elements.get("value")):
            resolved = _descriptor_to_class(target) if isinstance(target, str) else None
            if resolved:
                classes.add(resolved)
        for target in _as_list(elements.get("targets")):
            if isinstance(target, str) and target:
                classes.add(target.replace("/", "."))
        raw_priority = elements.get("priority")
        if isinstance(raw_priority, int):
            priority = raw_priority
    return classes, priority


def _method_injections(
    parsed_methods: list[tuple[str, str, list[_Annotation]]],
) -> list[MixinInjection]:
    injections: list[MixinInjection] = []
    for method_name, method_descriptor, annotations in parsed_methods:
        for descriptor, elements in annotations:
            if descriptor == _OVERWRITE_DESCRIPTOR:
                # @Overwrite has no selector: the target is the annotated
                # method itself, in every @Mixin target class.
                injections.append(
                    MixinInjection(
                        kind="overwrite",
                        method=method_name,
                        descriptor=method_descriptor or None,
                    )
                )
                continue
            kind = _INJECTOR_KINDS.get(descriptor or "")
            if kind is None:
                continue
            at_values, at_targets = _flatten_at(elements.get("at"))
            for selector in _as_list(elements.get("method")):
                if not isinstance(selector, str) or not selector:
                    continue
                owner, name, explicit_descriptor = _split_selector(selector)
                # A lone ``*`` matches every method: class-level info only, a
                # method key would be noise. Prefix wildcards (``tick*``) are
                # kept verbatim — they can't be expanded statically.
                if not name or name == "*":
                    continue
                injections.append(
                    MixinInjection(
                        kind=kind,
                        method=name,
                        descriptor=explicit_descriptor,
                        owner=owner,
                        at=at_values,
                        at_targets=at_targets,
                    )
                )
            # ``target = @Desc(owner = X.class, value = "name")`` selectors.
            for desc in _as_list(elements.get("target")):
                if not (isinstance(desc, tuple) and len(desc) == 2):
                    continue
                desc_descriptor, desc_elements = desc
                if desc_descriptor != _DESC_DESCRIPTOR:
                    continue
                name = desc_elements.get("value")
                if not isinstance(name, str) or not name:
                    continue
                raw_owner = desc_elements.get("owner")
                owner = _descriptor_to_class(raw_owner) if isinstance(raw_owner, str) else None
                injections.append(
                    MixinInjection(
                        kind=kind,
                        method=name,
                        owner=owner,
                        at=at_values,
                        at_targets=at_targets,
                    )
                )
    return injections


def extract_mixin_targets(class_bytes: bytes) -> MixinTargets:
    """Class targets, ``Class#method`` pairs and injection records from bytecode.

    Selectors with an explicit owner (``Lnet/x/Y;tick()V``) attribute to that
    owner only; bare selectors attribute to every ``@Mixin`` target class (the
    unavoidable static over-approximation for multi-target mixins).

    Best-effort: returns empty results for non-mixin classes or parse failures.
    """
    try:
        parsed = _ClassFile(class_bytes)
    except (ValueError, IndexError, struct.error):
        return MixinTargets()

    classes, priority = _class_targets(parsed.class_annotations)
    injections = _method_injections(parsed.method_annotations)

    methods: set[str] = set()
    for injection in injections:
        owners = [injection.owner] if injection.owner else sorted(classes)
        methods.update(f"{owner}#{injection.method}" for owner in owners)
    return MixinTargets(classes=classes, methods=methods, priority=priority, injections=injections)
