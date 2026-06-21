"""Multi-loader metadata parsing: Quilt, Forge and NeoForge alongside Fabric."""

import json
import zipfile
from pathlib import Path

from app.analyzer.metadata.forge import maven_to_constraint
from app.analyzer.mods import scan_mods_folder

FORGE_TOML = """
modLoader="javafml"
loaderVersion="[47,)"
[[mods]]
modId="forgemod"
version="1.0.0"
displayName="Forge Mod"
[[dependencies.forgemod]]
modId="minecraft"
mandatory=true
versionRange="[1.21,1.21.2)"
side="BOTH"
[[dependencies.forgemod]]
modId="jei"
mandatory=true
versionRange="[15,)"
side="BOTH"
[[dependencies.forgemod]]
modId="optionaldep"
mandatory=false
versionRange="[1,)"
side="BOTH"
"""

NEOFORGE_TOML = """
modLoader="javafml"
loaderVersion="[1,)"
[[mods]]
modId="neomod"
version="2.0.0"
displayName="Neo Mod"
[[dependencies.neomod]]
modId="neoforge"
type="required"
versionRange="[21,)"
[[dependencies.neomod]]
modId="minecraft"
type="required"
versionRange="[1.21,1.21.2)"
"""

QUILT_JSON = {
    "schema_version": 1,
    "quilt_loader": {
        "id": "quiltmod",
        "version": "1.0.0",
        "metadata": {"name": "Quilt Mod"},
        "depends": [
            {"id": "minecraft", "versions": ">=1.21"},
            {"id": "quilt_base", "versions": "*", "optional": True},
            "fabric-api",
        ],
    },
}


def _jar(folder: Path, name: str, entries: dict[str, str]) -> None:
    with zipfile.ZipFile(folder / name, "w") as zf:
        for path, content in entries.items():
            zf.writestr(path, content)


def test_forge_mods_toml_parsed(tmp_path: Path) -> None:
    _jar(tmp_path, "forgemod.jar", {"META-INF/mods.toml": FORGE_TOML})
    result = scan_mods_folder(tmp_path, "1.21.1")
    assert result.counts.errors == 0
    mod = result.mods[0]
    assert mod.id == "forgemod"
    assert mod.loader == "forge"
    assert mod.name == "Forge Mod"
    assert mod.version == "1.0.0"
    # minecraft + runtime ids excluded from depends; optional dep dropped.
    assert "jei" in mod.depends
    assert "minecraft" not in mod.depends
    assert "optionaldep" not in mod.depends


def test_neoforge_toml_parsed(tmp_path: Path) -> None:
    _jar(tmp_path, "neomod.jar", {"META-INF/neoforge.mods.toml": NEOFORGE_TOML})
    result = scan_mods_folder(tmp_path, "1.21.1")
    assert result.counts.errors == 0
    mod = result.mods[0]
    assert mod.id == "neomod"
    assert mod.loader == "neoforge"
    # required minecraft range normalised; floor lands in the 1.21 block.
    assert mod.mc_version == ">=1.21 <1.21.2"


def test_quilt_json_parsed(tmp_path: Path) -> None:
    _jar(tmp_path, "quiltmod.jar", {"quilt.mod.json": json.dumps(QUILT_JSON)})
    result = scan_mods_folder(tmp_path, "1.21.1")
    assert result.counts.errors == 0
    mod = result.mods[0]
    assert mod.id == "quiltmod"
    assert mod.loader == "quilt"
    assert mod.name == "Quilt Mod"
    assert mod.mc_version == ">=1.21"
    assert "fabric-api" in mod.depends
    assert "quilt_base" not in mod.depends  # optional dropped


def test_mixed_loaders_scan_together(tmp_path: Path) -> None:
    _jar(tmp_path, "fab.jar", {"fabric.mod.json": json.dumps({"id": "fab", "version": "1"})})
    _jar(tmp_path, "quilt.jar", {"quilt.mod.json": json.dumps(QUILT_JSON)})
    _jar(tmp_path, "forge.jar", {"META-INF/mods.toml": FORGE_TOML})
    _jar(tmp_path, "neo.jar", {"META-INF/neoforge.mods.toml": NEOFORGE_TOML})
    result = scan_mods_folder(tmp_path, "1.21.1")
    assert result.counts.errors == 0
    loaders = {m.id: m.loader for m in result.mods}
    assert loaders == {
        "fab": "fabric",
        "quiltmod": "quilt",
        "forgemod": "forge",
        "neomod": "neoforge",
    }


def test_fabric_wins_when_both_metadata_present(tmp_path: Path) -> None:
    # Architectury-style multi-loader jar: Fabric metadata takes priority.
    _jar(
        tmp_path,
        "multi.jar",
        {
            "fabric.mod.json": json.dumps({"id": "multimod", "version": "1"}),
            "META-INF/mods.toml": FORGE_TOML,
        },
    )
    result = scan_mods_folder(tmp_path, "1.21.1")
    assert result.mods[0].id == "multimod"
    assert result.mods[0].loader == "fabric"


def test_unrecognized_jar_is_error(tmp_path: Path) -> None:
    _jar(tmp_path, "plain.jar", {"README.txt": "nope"})
    result = scan_mods_folder(tmp_path, "1.21.1")
    assert result.counts.mods == 0
    assert result.counts.errors == 1
    assert "no recognized mod metadata" in result.errors[0].reason


def test_maven_to_constraint() -> None:
    assert maven_to_constraint("[1.21,1.22)") == ">=1.21 <1.22"
    assert maven_to_constraint("[1.21,)") == ">=1.21"
    assert maven_to_constraint("(,1.20.1]") == "<=1.20.1"
    assert maven_to_constraint("[1.21.1]") == "=1.21.1"
    assert maven_to_constraint("*") == "*"
    assert maven_to_constraint("") == "*"
    assert maven_to_constraint("1.20.1") == ">=1.20.1"  # bare = soft minimum
