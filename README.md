# Emendator — Modpack Conflict Analyzer

> From Latin *emendator*, "the one who removes flaws" (*emendare*: to remove defects).
> Emendator detects and resolves conflicts in large Minecraft modpacks **before** they crash your server.

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](./LICENSE)
[![Status: WIP](https://img.shields.io/badge/status-work%20in%20progress-orange.svg)](#roadmap)

---

> **Note** — Built in public and under active development; see the [roadmap](#roadmap) for what
> is shippable today. The internal design brief lives in [`PROJECT.md`](./PROJECT.md).

## The problem

Building large modpacks (200–400 mods) produces conflicts that are painful to diagnose.
Since 1.13, registries are namespaced (`modid:item`), so the old *numeric ID* collisions are gone.
The conflicts that remain are subtler:

- **Content duplication** — several mods add the same resource (copper, tin, …).
- **Recipe collisions** — crafting recipes overlapping on the same grid.
- **Mixin conflicts** — two mods patch the same vanilla method incompatibly (failed application = crash on load). The nastiest case.
- **Dependency / version mismatches** — incompatibilities, duplicate jars.

Existing tooling is **fragmented and reactive** (post-crash). Nobody does **aggregated
pre-launch analysis** or **automated bisection** of conflicts. Emendator does both.

## What it does

A desktop application that takes a modpack — a launcher instance (CurseForge, Modrinth,
Prism/MultiMC, or the vanilla launcher) or a bare `mods/` folder, on **any loader** (Fabric,
Quilt, Forge, NeoForge) — and:

1. produces a **conflict map** via static analysis (fast, offline-first);
2. **confirms load-time conflicts with certainty** by booting a real headless server in an isolated container;
3. **isolates the guilty pairs** through automated bisection when a boot crashes;
4. **generates no-code resolution configs** (Almost Unified `unify.json`, recipe-override datapacks).

It also takes inventory **beyond mods** (resource packs, datapacks, shaders, and an approximate
index of the items/blocks the pack adds), and **enriches** the pack online (best-effort): Modrinth
hash lookup with update checks, plus CurseForge project links, so you can **update** an outdated jar
or **install** a missing dependency in one click.

### Core design bet

> **A conflict is not a property of a jar — it is a property of a *set*.**

Sandboxing each jar in isolation reveals nothing cross-mod: a mixin only breaks when both mods
are present and the loader applies both transformers to the same class. The unit of test is
therefore **the full set (or a subset) booted together**, never a lone jar.

**Hybrid strategy:** static analysis triages fast and for free (tags, recipes, declared mixin
targets); a headless runtime decides with certainty on load-time conflicts, and **bisection**
locates the culprits. Static only triggers a boot on ambiguous cases → boots (expensive) are minimized.

## Stack

| Layer              | Choice                                | Notes                                                              |
| ------------------ | ------------------------------------- | ----------------------------------------------------------------- |
| Desktop shell      | **Tauri + React/Vite (TypeScript)**   | Lightweight; Rust limited to config + spawning the orchestrator.  |
| Local backend      | **FastAPI (Python)**                  | Serves the API the front consumes; drives Docker and parsing.     |
| Static analyzer    | Python (`zipfile` + JSON parsing)     | Unzips jars, reads metadata / mixins / recipes / tags.            |
| Runtime runner     | **Docker** (one container per boot)   | Headless server (`itzg` image, `TYPE` from the detected loader), mods injected, logs captured. |
| Log parsing        | MCLA / mclo.gs patterns               | Reuse existing error classification, don't reinvent it.           |

Two contracts hold the system together:

- **Conflict map** — the pivot data model shared by the static analyzer, the runtime runner, and the resolution generator.
- **Version profile** — all version-dependent constants (JDK, item format, datapack folders, tag namespace, Fabric API) live in a profile, never hardcoded. Supporting a new Minecraft version = adding a profile, not rewriting logic.

The Minecraft version is **auto-detected** from the pack (with a manual override), and the
detected loader drives the runner. **Default target block: `1.21.1`** (Java 21, item *components*,
singular datapack folders, `c:` tags).

## Scope

**In scope:** all four loaders (Fabric, Quilt, Forge, NeoForge), each parsed by a per-loader
metadata adapter into a common `Mod` · launcher-native ingestion (CurseForge, Modrinth, Prism,
MultiMC, vanilla) or a bare `mods/` folder · inventory beyond mods (resource packs, datapacks,
shaders) with override detection and an approximate item/block index · online enrichment (Modrinth
hash lookup + update check, CurseForge links) with one-click update/install · headless **server**
boot · detection of content duplication (tags), recipe collisions, declared mixin overlaps,
dependency/version issues, duplicate jars · generation of `unify.json` and recipe-override datapacks.

**Out of scope (surfaced in the UI, not silently ignored):** client-only mods (not loaded by a
server, so visual/render conflicts are untestable) · *silent* conflicts (two mixins that coexist
without crashing but break behavior) · a **headless client** (Xvfb / offscreen GL) — the runner
does server boots only. The item index is **approximate** (built from `lang`/`model` assets, so
items registered purely in code aren't listed).

## Roadmap

Phases are strictly incremental — each ships independently with a clear Definition of Done.
Items below are implemented but the project remains pre-release WIP (interfaces and behavior may
still change).

- [x] **Phase 0 — Foundation.** Tauri + React/Vite scaffold; local FastAPI; ingest a `mods/` folder; parse loader metadata → mod list + versions + environment in the UI.
- [x] **Phase 1 — Static analyzer.** Load the version profile; detect tag overlap, recipe collision, declared mixin overlap, dependencies, duplicate jars; emit the conflict map; sortable UI.
- [x] **Phase 2 — Headless runner.** Docker server (JDK + loader from the profile/detection); boot a given set with mixin-debug flags; capture + classify the log (OK / crash + cause).
- [x] **Phase 3 — Automated bisection.** On crash, orchestrated binary search down to the guilty pair(s) in ~log₂(N) boots.
- [x] **Phase 4 — No-code resolution.** Generate `unify.json` and recipe-override datapacks; preview and export from the UI.

Landed beyond the original phases (see [`PROJECT.md`](./PROJECT.md) §2/§5/§7/§8):

- **Multi-loader** ingestion (Fabric, Quilt, Forge, NeoForge) via per-loader metadata adapters.
- **Launcher-native instances** — auto-discover and scan CurseForge / Modrinth / Prism / MultiMC / vanilla instances.
- **Beyond mods** — resource packs, datapacks, shaders, override detection, approximate item/block index.
- **Online enrichment** — Modrinth hash lookup + update check, CurseForge links; one-click **update** / **install**.
- **Auto version detection** with a manual override pinned in the header.

## Safety

Running jars means running arbitrary code. Every boot happens in an **isolated container**
(restricted filesystem + network), never directly on the host.

## Prior art

[Almost Unified](https://github.com/AlmostReliable/almostunified) · [PackTest](https://github.com/misode/packtest) · Crash Assistant / MCDoctor.ai / [mclo.gs](https://mclo.gs) · [SpongePowered Mixin](https://github.com/SpongePowered/Mixin) debug flags · ready-made Fabric server Docker images.

## License

[GPL-3.0](./LICENSE) © Rémi Asselin
