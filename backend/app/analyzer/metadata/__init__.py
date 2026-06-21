"""Loader-agnostic mod-metadata parsing.

A jar declares its loader by the metadata file it ships. :func:`parse_mod_metadata`
detects which is present and dispatches to the matching parser, all returning the
common :class:`Mod`. Order matters for multi-loader jars (e.g. Architectury ships
both ``fabric.mod.json`` and a Forge toml): Fabric wins, then Quilt, then NeoForge,
then Forge — newest/most-specific first.
"""

import zipfile

from app.analyzer.metadata.fabric import parse_fabric
from app.analyzer.metadata.forge import parse_forge
from app.analyzer.metadata.quilt import parse_quilt
from app.models import Mod, ScanError

FABRIC_METADATA = "fabric.mod.json"
QUILT_METADATA = "quilt.mod.json"
NEOFORGE_METADATA = "META-INF/neoforge.mods.toml"
FORGE_METADATA = "META-INF/mods.toml"

# Metadata files we recognise, listed in dispatch priority order.
METADATA_FILES = (FABRIC_METADATA, QUILT_METADATA, NEOFORGE_METADATA, FORGE_METADATA)

_NO_METADATA = "no recognized mod metadata (not a Fabric/Quilt/Forge/NeoForge mod)"


def parse_mod_metadata(
    zf: zipfile.ZipFile, names: list[str], jar_name: str
) -> tuple[Mod | None, ScanError | None]:
    """Detect the loader from the jar's metadata file and parse it into a Mod."""
    present = set(names)
    if FABRIC_METADATA in present:
        return parse_fabric(zf.read(FABRIC_METADATA), jar_name)
    if QUILT_METADATA in present:
        return parse_quilt(zf.read(QUILT_METADATA), jar_name)
    if NEOFORGE_METADATA in present:
        return parse_forge(zf.read(NEOFORGE_METADATA), jar_name, neoforge=True)
    if FORGE_METADATA in present:
        return parse_forge(zf.read(FORGE_METADATA), jar_name, neoforge=False)
    return None, ScanError(jar=jar_name, reason=_NO_METADATA)
