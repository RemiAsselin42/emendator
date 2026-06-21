"""Parse a Fabric ``fabric.mod.json`` into the common :class:`Mod`."""

import json

from app.models import Environment, Mod, ScanError

_VALID_ENVIRONMENTS: tuple[Environment, ...] = ("server", "client", "*")


def coerce_environment(value: object) -> Environment:
    """Map the raw ``environment`` field to the contract; default to ``"*"``."""
    if value in _VALID_ENVIRONMENTS:
        return value  # type: ignore[return-value]
    return "*"


def coerce_mc_version(depends: object) -> str | None:
    """Pull the Minecraft version constraint out of ``depends`` (str or list)."""
    if not isinstance(depends, dict):
        return None
    mc = depends.get("minecraft")
    if isinstance(mc, list):
        mc = mc[0] if mc else None
    if mc is None:
        return None
    return mc if isinstance(mc, str) else str(mc)


def parse_fabric(raw: bytes, jar_name: str) -> tuple[Mod | None, ScanError | None]:
    """Parse ``fabric.mod.json`` bytes into a :class:`Mod`."""
    try:
        # strict=False tolerates literal control characters (newlines/tabs) that
        # real fabric.mod.json files embed in string values; Fabric's own loader
        # is lenient here, so we must be too (e.g. Debugify).
        data = json.loads(raw, strict=False)
    except json.JSONDecodeError as exc:
        return None, ScanError(jar=jar_name, reason=f"invalid fabric.mod.json: {exc}")

    if not isinstance(data, dict):
        return None, ScanError(jar=jar_name, reason="fabric.mod.json is not an object")

    mod_id = data.get("id")
    if not isinstance(mod_id, str) or not mod_id:
        return None, ScanError(jar=jar_name, reason="fabric.mod.json missing 'id'")

    depends = data.get("depends")
    version = data.get("version")
    name = data.get("name")
    provides = data.get("provides")
    mod = Mod(
        id=mod_id,
        name=name if isinstance(name, str) else None,
        version=str(version) if version is not None else None,
        mc_version=coerce_mc_version(depends),
        environment=coerce_environment(data.get("environment")),
        loader="fabric",
        depends=depends if isinstance(depends, dict) else {},
        provides=[p for p in provides if isinstance(p, str)] if isinstance(provides, list) else [],
        jar=jar_name,
    )
    return mod, None
