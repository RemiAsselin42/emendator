"""Minecraft version parsing + constraint math (PROJECT.md §6).

Pure helpers, no I/O and no pydantic. A ``fabric.mod.json`` declares
``depends.minecraft`` as a version *constraint* — exact (``1.21.1``), range
(``>=1.21``), tilde/caret (``~1.21``, ``^1.21``), wildcard (``1.21.x``), the
catch-all ``*``, or an OR-list. We parse those into :class:`Constraint` objects
and expose ``contains`` / ``floor`` so :mod:`app.profile` can derive the version
a whole mod set provably runs on (the highest floor any mod requires).

Versions are stored as a comparable ``(major, minor, patch)`` tuple, so the
post-2026 scheme (Mojang dropped the ``1.`` prefix, e.g. ``26.1``) orders above
every ``1.x`` automatically.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_ANY_TOKENS = {"", "*", "any"}
_WILDCARDS = {"x", "X", "*"}


@dataclass(frozen=True, order=True)
class McVersion:
    """A Minecraft version as a comparable numeric tuple (``26.1`` > ``1.21.8``)."""

    major: int
    minor: int
    patch: int = 0

    @classmethod
    def parse(cls, raw: str) -> McVersion:
        """``"1.21.5"`` / ``"1.21"`` / ``"26.1"`` -> :class:`McVersion`."""
        # Drop a leading v and any build/pre-release suffix (1.21.1+build.7).
        token = raw.strip().lstrip("vV").split("-", 1)[0].split("+", 1)[0]
        parts = [p for p in token.split(".") if p != ""]
        if not parts or not all(p.isdigit() for p in parts[:3]):
            raise ValueError(f"not a Minecraft version: {raw!r}")
        nums = [int(p) for p in parts[:3]]
        while len(nums) < 3:
            nums.append(0)
        return cls(nums[0], nums[1], nums[2])

    def __str__(self) -> str:
        # Minecraft writes "1.21", not "1.21.0".
        if self.patch == 0:
            return f"{self.major}.{self.minor}"
        return f"{self.major}.{self.minor}.{self.patch}"


# Sentinels for open-ended bounds. _MAX sits above any real release.
_MIN = McVersion(0, 0, 0)
_MAX = McVersion(9999, 0, 0)


@dataclass(frozen=True)
class _Range:
    """A single ``[low, high]`` version interval with inclusivity flags."""

    low: McVersion
    low_inc: bool
    high: McVersion
    high_inc: bool

    def contains(self, v: McVersion) -> bool:
        above_low = v > self.low or (v == self.low and self.low_inc)
        below_high = v < self.high or (v == self.high and self.high_inc)
        return above_low and below_high


@dataclass(frozen=True)
class Constraint:
    """A parsed ``depends.minecraft`` value: a union of ranges (OR for lists)."""

    ranges: tuple[_Range, ...]
    is_any: bool = False

    def contains(self, v: McVersion) -> bool:
        return self.is_any or any(r.contains(v) for r in self.ranges)

    def intersects(self, low: McVersion, high: McVersion) -> bool:
        """Does any accepted version fall within the inclusive ``[low, high]``?"""
        return self.is_any or any(r.low <= high and low <= r.high for r in self.ranges)

    def floor(self) -> McVersion:
        """Lowest version this constraint accepts (``_MIN`` if unbounded below)."""
        if self.is_any or not self.ranges:
            return _MIN
        return min(r.low for r in self.ranges)


_ANY = Constraint(ranges=(), is_any=True)


def _tilde_bounds(ver: str) -> tuple[McVersion, McVersion]:
    """``~X`` -> ``>=X`` and the exclusive upper bound (locks the minor)."""
    parts = [int(p) for p in ver.split(".") if p.isdigit()]
    nums = (parts + [0, 0, 0])[:3]
    low = McVersion(*nums)
    high = McVersion(nums[0], nums[1] + 1, 0) if len(parts) >= 2 else McVersion(nums[0] + 1, 0, 0)
    return low, high


def _caret_bounds(ver: str) -> tuple[McVersion, McVersion]:
    """``^X`` -> ``>=X`` and the exclusive next-major upper bound."""
    nums = ([int(p) for p in ver.split(".") if p.isdigit()] + [0, 0, 0])[:3]
    return McVersion(*nums), McVersion(nums[0] + 1, 0, 0)


def _exact_or_wildcard(ver: str) -> _Range:
    """Bare ``1.21.1`` (exact) or ``1.21.x`` / ``1.x`` (wildcard interval)."""
    parts = ver.split(".")
    wild = next((i for i, p in enumerate(parts) if p in _WILDCARDS), None)
    if wild is None:
        v = McVersion.parse(ver)
        return _Range(v, True, v, True)
    base = parts[:wild]
    if not base:  # "x" / "*" -> any
        return _Range(_MIN, True, _MAX, True)
    nums = ([int(p) for p in base] + [0, 0, 0])[:3]
    low = McVersion(*nums)
    # major.x -> bump major; major.minor.x -> bump minor (exclusive upper bound).
    high = McVersion(nums[0] + 1, 0, 0) if wild == 1 else McVersion(nums[0], nums[1] + 1, 0)
    return _Range(low, True, high, False)


def _parse_token(token: str) -> _Range:
    """One comparator token (``>=1.21``, ``~1.21``, ``1.21.x``, ``1.21.1``)."""
    match = re.match(r"^\s*(>=|<=|>|<|\^|~|=)?\s*(.+?)\s*$", token)
    if match is None:
        raise ValueError(f"unparseable constraint token: {token!r}")
    op, ver = match.group(1) or "=", match.group(2)
    if op in (">=", ">"):
        return _Range(McVersion.parse(ver), op == ">=", _MAX, True)
    if op in ("<=", "<"):
        return _Range(_MIN, True, McVersion.parse(ver), op == "<=")
    if op == "~":
        low, high = _tilde_bounds(ver)
        return _Range(low, True, high, False)
    if op == "^":
        low, high = _caret_bounds(ver)
        return _Range(low, True, high, False)
    return _exact_or_wildcard(ver)


def _intersect_tokens(tokens: list[str]) -> _Range:
    """AND together space/comma-separated tokens (``>=1.20.5 <=1.20.6``)."""
    low, low_inc, high, high_inc = _MIN, True, _MAX, True
    for token in tokens:
        r = _parse_token(token)
        if r.low > low or (r.low == low and not r.low_inc):
            low, low_inc = r.low, r.low_inc
        if r.high < high or (r.high == high and not r.high_inc):
            high, high_inc = r.high, r.high_inc
    return _Range(low, low_inc, high, high_inc)


def parse_constraint(raw: object) -> Constraint:
    """Parse a ``depends.minecraft`` value (str / list / None) into a Constraint.

    Anything unbounded (``*``, missing, or unparseable) becomes a non-constraining
    :data:`_ANY`, so it is ignored by version detection rather than guessed at.
    """
    if raw is None:
        return _ANY
    if isinstance(raw, (list, tuple)):
        ranges: list[_Range] = []
        for item in raw:
            sub = parse_constraint(item)
            if sub.is_any:
                return _ANY  # an OR branch that matches anything makes the whole any
            ranges.extend(sub.ranges)
        return Constraint(tuple(ranges)) if ranges else _ANY
    text = str(raw).strip()
    if text.lower() in _ANY_TOKENS:
        return _ANY
    # "||" is OR (each side an independent range); commas/spaces inside are AND.
    or_parts = [part.strip() for part in text.split("||")]
    if len(or_parts) > 1:
        ranges: list[_Range] = []
        for part in or_parts:
            sub = parse_constraint(part)
            if sub.is_any:
                return _ANY
            ranges.extend(sub.ranges)
        return Constraint(tuple(ranges)) if ranges else _ANY
    tokens = [t for t in re.split(r"[\s,]+", text) if t]
    try:
        return Constraint((_intersect_tokens(tokens),))
    except ValueError:
        return _ANY
