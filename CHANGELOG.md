# Changelog

All notable changes to Emendator are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.1] — 2026-06-22

### Added

- **Multi-loader support.** Per-loader metadata adapters parse Fabric, Quilt, Forge and
  NeoForge into one common `Mod`, with a normalised Minecraft-version constraint so detection
  stays loader-agnostic (`app/analyzer/metadata/`).
- **Launcher-native ingestion.** Discover installed instances from CurseForge, Modrinth, Prism,
  MultiMC and the vanilla launcher, then scan an instance directly (offline, best-effort)
  — endpoints `GET /instances/discover`, `POST /instance/detect`, `POST /instance/scan`
  (`app/sources/`). The frontend scan client moves from folder-based `scanMods` to
  instance-based `scanInstance`.
- **Beyond mods.** Inventory of resource packs, datapacks and shaders with override detection
  (assets/data shipped by ≥2 packs) and a global, approximate index of the items/blocks the pack
  adds (`app/analyzer/packs.py`, `app/analyzer/registry_index.py`).
- **Online enrichment.** Modrinth hash lookup with update check, plus CurseForge project links
  (offline manifest + optional API key), attaching project links and update status
  (`app/enrich/`).
- **One-click update / install.** `update_mod` swaps a jar to its latest Modrinth version;
  `install_mod` adds a runner-flagged missing dependency. Both are atomic via a `.part` temp file
  and SHA-1 verified, so IO/network failures leave `mods/` untouched
  — endpoints `POST /mods/update`, `POST /mods/install`.
- **Automatic Minecraft version detection** with block-level confidence and multi-block profiles,
  plus a manual override pinned to the header (`app/version.py`, `GET /profiles`,
  `POST /mods/detect`).
- **UI.** Instance badge, content and items tabs, loader and update controls, consequence-based
  conflict triage, and a Recipes tab; broad restyle of `App`, views and styles.

### Changed

- Runner is now a single loader-parameterised orchestrator: the headless server boot sets the
  `itzg` image `TYPE` from the detected loader (FABRIC / QUILT / FORGE / NEOFORGE) instead of
  assuming Fabric.
- Documentation (`PROJECT.md`, `DESIGN.md`) widened to multi-loader, instances, content and
  enrichment.

### Removed

- Unused `@tauri-apps/plugin-shell` dependency.

### Fixed

- Guard optional `Mod.homepage` before string operations (pyright).

## [0.1.0] — 2026-06-20

### Added

- **Phase 0 — Foundation.** Tauri + React/Vite scaffold, local FastAPI sidecar (auto-spawned by
  the shell), ingestion of a `mods/` folder into the conflict map.
- **Phase 1 — Static analyzer.** Version-profile-driven detection of tag overlap, recipe
  collision, declared mixin overlap (method-level precision, including nested-jar mixins),
  dependencies and duplicate jars; the conflict map as the shared contract.
- **Phase 2 — Headless runner.** Docker server boot with mixin-debug flags, log capture and
  OK / crash + cause classification, with hardened container isolation.
- **Phase 3 — Automated bisection.** Binary search over a crashing set down to the guilty pair(s)
  in ~log₂(N) boots.
- **Phase 4 — No-code resolution.** Generation of Almost Unified `unify.json` and recipe-override
  datapacks, with preview and export from the UI.
- **CI.** Windows installer build and draft release on tag.

[Unreleased]: https://github.com/RemiAsselin42/emendator/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/RemiAsselin42/emendator/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/RemiAsselin42/emendator/releases/tag/v0.1.0
