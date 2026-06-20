"""Data contracts shared across the analyzer, the runner and the front.

The shapes here implement the **conflict map** (PROJECT.md §9) and the
**version profile** (§6). Phase 0 only populates the `mods` / `untestable`
slices; later phases add `conflicts` on top of the same models.

JSON is emitted in camelCase (matching §9: ``mcVersion``, ``detectedBy``) while
Python keeps snake_case attributes — the alias generator bridges the two.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

# environment as declared in fabric.mod.json; "*" means both sides.
Environment = Literal["server", "client", "*"]


class CamelModel(BaseModel):
    """Base model: snake_case in Python, camelCase on the wire."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class Mod(CamelModel):
    """One Fabric mod resolved from a jar's ``fabric.mod.json``."""

    id: str
    name: str | None = None
    version: str | None = None
    mc_version: str | None = None
    environment: Environment = "*"
    depends: dict[str, str | list[str]] = {}
    jar: str


class UntestableMod(CamelModel):
    """A mod the server boot cannot exercise (e.g. ``environment:client``)."""

    id: str
    reason: str


class ScanError(CamelModel):
    """A jar that could not be parsed (not Fabric, corrupt, missing id…)."""

    jar: str
    reason: str


class ScanCounts(CamelModel):
    """Summary counts surfaced directly in the UI."""

    total: int
    mods: int
    testable: int
    untestable: int
    errors: int


class ScanRequest(CamelModel):
    """Body of ``POST /mods/scan``: absolute path to a ``mods/`` folder."""

    path: str


class ScanResult(CamelModel):
    """Outcome of scanning a ``mods/`` folder (Phase 0 slice of the map)."""

    profile: str
    mods_path: str
    mods: list[Mod]
    untestable: list[UntestableMod]
    errors: list[ScanError]
    counts: ScanCounts
