"""Parse a Forge/NeoForge ``(neoforge.)mods.toml`` into the common :class:`Mod`.

Both loaders share the TOML schema: a ``[[mods]]`` table (the primary mod is the
first) and ``[[dependencies.<modId>]]`` tables. Version ranges use **Maven**
notation (``[1.21,1.22)``), which we convert to the comparator syntax the rest
of the tool speaks (:func:`app.version.parse_constraint`) so version detection is
loader-agnostic. ``tomllib`` is stdlib (Python 3.11+), so no dependency is added.
"""

import re
import tomllib
from typing import Any

from app.models import Mod, ScanError

# A Maven range group: an opening bracket, low, high, closing bracket.
_RANGE_RE = re.compile(r"([\[(])\s*([^,\]\)]*)\s*,\s*([^,\]\)]*)\s*([\])])")
# An exact single version: [x] (no comma inside).
_EXACT_RE = re.compile(r"\[\s*([^,\]\)]+)\s*\]")
# Forge ``[[mods]] version`` is often the build placeholder, resolved from the
# jar manifest at load time — not a real version we can report statically.
_PLACEHOLDER = "${"


def maven_to_constraint(spec: object) -> str:
    """Convert a Maven version range to comparator syntax (``"*"`` if unbounded).

    ``[1.21,1.22)`` -> ``>=1.21 <1.22``; ``[1.21,)`` -> ``>=1.21``;
    ``(,1.20]`` -> ``<=1.20``; ``[1.21]`` -> ``=1.21``; multiple groups -> OR.
    Anything unrecognised falls back to ``"*"`` (ignored by detection).
    """
    if not isinstance(spec, str):
        return "*"
    text = spec.strip()
    if not text or text == "*":
        return "*"
    parts: list[str] = []
    for m in _EXACT_RE.finditer(text):
        if "," not in m.group(0):  # a real [x] exact, not part of a range
            parts.append(f"={m.group(1).strip()}")
    for m in _RANGE_RE.finditer(text):
        open_b, low, high, close_b = m.groups()
        tokens: list[str] = []
        if low.strip():
            tokens.append((">=" if open_b == "[" else ">") + low.strip())
        if high.strip():
            tokens.append(("<=" if close_b == "]" else "<") + high.strip())
        parts.append(" ".join(tokens) if tokens else "*")
    if not parts:
        # A bare version with no brackets is a Maven "soft" minimum.
        return f">={text}" if re.match(r"^[\d.]+$", text) else "*"
    return " || ".join(parts)


# Loader/runtime ids that are never shipped as a mod jar (excluded from depends
# so they don't surface as missing dependencies).
_RUNTIME_IDS = {"minecraft", "forge", "neoforge", "fml", "javafml", "java", "mixinextras"}


def _depends_map(deps: object) -> tuple[dict[str, str | list[str]], str | None]:
    """``[[dependencies.<id>]]`` -> ``({modId: range}, minecraft_range)``.

    Optional dependencies are dropped (only mandatory/required ones count toward
    missing-dependency detection). Runtime ids stay out of the map but the
    Minecraft range is returned separately for version detection.
    """
    out: dict[str, str | list[str]] = {}
    mc_version: str | None = None
    if not isinstance(deps, list):
        return out, mc_version
    for dep in deps:
        if not isinstance(dep, dict):
            continue
        dep_id = dep.get("modId")
        if not isinstance(dep_id, str) or not dep_id:
            continue
        constraint = maven_to_constraint(dep.get("versionRange"))
        if dep_id.lower() == "minecraft":
            mc_version = constraint if constraint != "*" else None
            continue
        if dep_id.lower() in _RUNTIME_IDS:
            continue
        # mandatory: Forge uses `mandatory`, NeoForge uses `type="required"`.
        optional = dep.get("mandatory") is False or dep.get("type") in {
            "optional",
            "incompatible",
            "discouraged",
        }
        if optional:
            continue
        out[dep_id] = constraint
    return out, mc_version


def parse_forge(
    raw: bytes, jar_name: str, *, neoforge: bool
) -> tuple[Mod | None, ScanError | None]:
    """Parse a ``mods.toml`` / ``neoforge.mods.toml`` into a :class:`Mod`."""
    label = "neoforge.mods.toml" if neoforge else "mods.toml"
    try:
        data: dict[str, Any] = tomllib.loads(raw.decode("utf-8", errors="replace"))
    except (tomllib.TOMLDecodeError, ValueError) as exc:
        return None, ScanError(jar=jar_name, reason=f"invalid {label}: {exc}")

    mods = data.get("mods")
    if not isinstance(mods, list) or not mods or not isinstance(mods[0], dict):
        return None, ScanError(jar=jar_name, reason=f"{label} missing [[mods]]")
    primary = mods[0]
    mod_id = primary.get("modId")
    if not isinstance(mod_id, str) or not mod_id:
        return None, ScanError(jar=jar_name, reason=f"{label} missing 'modId'")

    raw_deps = data.get("dependencies")
    deps_for_mod = raw_deps.get(mod_id) if isinstance(raw_deps, dict) else None
    depends, mc_version = _depends_map(deps_for_mod)

    version = primary.get("version")
    version_str = str(version) if isinstance(version, str) and _PLACEHOLDER not in version else None
    display = primary.get("displayName")
    provides = primary.get("provides")
    mod = Mod(
        id=mod_id,
        name=display if isinstance(display, str) else None,
        version=version_str,
        mc_version=mc_version,
        environment="*",
        loader="neoforge" if neoforge else "forge",
        depends=depends,
        provides=[p for p in provides if isinstance(p, str)] if isinstance(provides, list) else [],
        jar=jar_name,
    )
    return mod, None
