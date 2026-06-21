# Emendator — Fabric Conflict Analyzer (MVP project brief)

> Context document for Claude Code. It defines the problem, the architectural bets, the known
> walls and the MVP breakdown. To be treated as the source of truth: each phase is shippable
> independently and builds on the previous one.
>
> **Project name: Emendator** — from Latin _emendator_, "the one who removes flaws"
> (_emendare_: to remove defects). The app detects and resolves conflicts in a Fabric modpack.

---

## 1. Problem

Building large Fabric modpacks (200–400 mods) produces conflicts that are hard to diagnose.
Since 1.13, registries are namespaced (`modid:item`): the historical **numeric ID** collisions
are gone. The remaining conflicts are of a different nature:

- **Content duplication**: several mods add the same resource (copper, tin…).
- **Recipe conflicts**: crafting recipes overlapping on the same grid.
- **Mixin conflicts**: two mods patch the same vanilla method incompatibly
  (failed application = crash on load). This is the most painful case.
- **Dependencies / versions**: incompatibilities, duplicate jars.

Existing tooling is **fragmented and reactive** (post-crash): Almost Unified (content
unification), YARCF (recipes), Crash Assistant / MCDoctor.ai (log analysis after a crash),
no-code launchers to _install_. Nobody does **aggregated pre-launch analysis** or **automated
bisection** of conflicts.

## 2. Goal

A **desktop application** that takes a modpack — a launcher instance (CurseForge,
Modrinth, Prism/MultiMC) or a bare `mods/` folder, any loader (Fabric, Quilt, Forge,
NeoForge) — and:

1. produces a **conflict map** through static analysis (fast, offline);
2. **confirms with certainty** load-time conflicts by booting a real headless Fabric server in
   an isolated container;
3. **isolates the guilty pairs** through automated bisection when a boot crashes;
4. **generates no-code resolution configs** (Almost Unified's unify.json, recipe overrides as a
   datapack).

## 3. Fundamental architectural bet

**A conflict is not a property of a jar, it is a property of a SET.**
Sandboxing each jar in isolation reveals no cross-mod conflict: a mixin only breaks when both
mods are present and the loader applies both transformers to the same class.
The unit of test is therefore **the full set (or a subset) booted together**, never a lone jar.

**Hybrid strategy:**

- **Static** to triage fast and for free (tags, recipes, declared mixin targets).
- **Headless runtime** to decide with certainty on load-time conflicts, and **bisection**
  to locate the pairs.

Static only triggers a boot on ambiguous cases → the number of boots (expensive) is minimized.

## 4. Stack

| Layer            | Choice                                 | Notes                                                                                                                                                                                            |
| ---------------- | -------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Desktop shell    | **Tauri + React/Vite (TS)**            | Lightweight; TS front as usual. Rust surface limited to config + commands that spawn the Python orchestrator. Alternative: Electron (100% TS+Python) if the Rust becomes a burden.               |
| Local backend    | **FastAPI (Python)**                   | Same shape as `papers-helper`. Exposes the API the front consumes; drives Docker and parsing.                                                                                                    |
| Static analyzer  | Python (`zipfile` + JSON parsing)      | Unzips jars, reads metadata / mixins / recipes / tags. Consumes the **version profile** (§6).                                                                                                    |
| Runtime runner   | **Docker** (1 container per boot)      | Headless Fabric server image, mods injected, logs captured. JDK and artifacts driven by the version profile (§6).                                                                                |
| Log parsing      | Reuse MCLA / mclo.gs patterns          | Do not reinvent error classification.                                                                                                                                                           |

**Default decision: Tauri.** It is also an explicit learning goal. Electron remains the fallback
plan if the weight of the Rust ⇄ Python sidecar coupling becomes a drag.

## 5. MVP scope

**Target version: `1.21.1`** (block 1.21–1.21.1). Locked for the MVP because it is consistent with
the modern conventions already adopted in this doc: Java 21, items as **components**, datapack
folders **singular** (`recipe/`, `advancement/`), `c:` tags. Every version-dependent constant goes
through the **version profile** (§6) — never hardcoded.

**In scope:**

- **All four loaders**: Fabric, Quilt, Forge, NeoForge. Each ships different metadata
  (`fabric.mod.json`, `quilt.mod.json`, `(neoforge.)mods.toml`) parsed by a per-loader adapter
  into one common `Mod`; the MC-version constraint is normalised so detection stays
  loader-agnostic (`app/analyzer/metadata/`).
- **Launcher-native ingestion**: point at a CurseForge / Modrinth / Prism / MultiMC instance (or a
  bare `mods/` folder) and the content sub-folders are located automatically (`app/sources/`).
- **Beyond mods**: inventory of resource packs / datapacks / shaders, override detection
  (assets/data shipped by ≥2 packs), and a global index of the items/blocks the pack adds
  (`app/analyzer/packs.py`, `registry_index.py`).
- **Online enrichment** (best-effort, offline-first): Modrinth (hash lookup + update check) and
  CurseForge (offline manifest + optional API key) attach project links and update status
  (`app/enrich/`).
- Headless **server** boot (no headless client in the MVP).
- Detection: content duplication (tags), recipe collisions, load-time mixin conflicts,
  dependencies/versions, duplicate jars.
- Generation: `unify.json` (Almost Unified), recipe-override datapack.

**Out of scope (assumed, to be documented in the UI):**

- **Client-only** mods (`environment: client`): not loaded by a server boot → visual conflicts
  (render, shaders, HUD) not testable in the MVP. Read the `environment` field and display
  "N mods not testable in server mode".
- **Silent** conflicts: two mixins that coexist without crashing but break behavior.
  Not detectable without gameplay assertions (a gametest model like PackTest). Out of MVP.
- The **item index is approximate**: built from `lang`/`model` assets, so items registered purely
  in code (no lang key, no item model) aren't listed.
- A **headless client** (Xvfb / offscreen GL) is out of scope; the runner does server boots only.
  Server boots cover all four loaders (the itzg image `TYPE` is set from the detected loader), but
  client-only visual conflicts remain untestable.

## 6. Version profile (contract — Phases 1 and 2)

Version-dependent constants are **never hardcoded**. They live in a profile that both the static
analyzer (Phase 1) and the runner (Phase 2) consume. MVP = profile `1.21.1`.

```jsonc
{
  "profile": "1.21.1",
  "jdk": "21", // runner Docker image
  "itemFormat": "components", // components | nbt
  "datapackFolders": "singular", // singular | plural
  "recipePath": "data/{mod}/recipe", // pre-1.21: data/{mod}/recipes
  "tagPath": "data/{mod}/tags/items", // tags stay plural across all versions
  "tagNamespace": "c", // c (1.21+) | forge (old)
  "fabricApi": "<exact version>", // exact-version artifact required by the runner
}
```

**Adding a block later = adding a profile, not rewriting the logic.** E.g. 1.20.1:
`jdk:17`, `itemFormat:nbt`, `datapackFolders:plural`, `recipePath:data/{mod}/recipes`,
`tagNamespace:forge`.

Block landmarks (the breaks that change the profile):

| Block             | jdk    | itemFormat     | datapackFolders | Modding state                                    |
| ----------------- | ------ | -------------- | --------------- | ------------------------------------------------ |
| 1.18 → 1.20.4     | 17     | nbt            | plural          | Heavily modded; 1.20.1 = reigning base           |
| 1.20.5 → 1.20.6   | 21     | components     | plural          | Transitional, lightly modded                     |
| **1.21 → 1.21.1** | **21** | **components** | **singular**    | **MVP target**                                   |
| 1.21.2+           | 21     | components     | singular        | Current, minor per-version format churn          |
| 26.1+             | 25     | components     | singular        | Recent (end of the "1." prefix), young ecosystem |

> Reminder: a block shares the **parsing constants** and the **JDK image**, not jar
> substitutability. The runner needs the **exact** Fabric server jar + Fabric API of the precise
> targeted version (e.g. 1.21.1), even within the block.

## 7. Conflict categories — detection

| Category             | Static source                                                  | Runtime confirmation                                  |
| -------------------- | -------------------------------------------------------------- | ----------------------------------------------------- |
| Content duplication  | `tagPath` → tag overlaps                                       | — (resolved by config)                                |
| Recipe collisions    | `recipePath` → same entries/grid                               | Deserialization failure on load                       |
| Mixin conflicts      | `*.mixins.json` → common class/method targets (heuristic)     | **Post-transformation mixin export** = ground truth   |
| Dependencies / vers. | loader metadata (depends, target version)                     | Resolution error at boot                              |
| Duplicate jars       | duplicated hash / modid                                        | Loader refuses to start                               |

**Mixins — from estimation to observation** via JVM flags at boot:

- `-Dmixin.debug.export=true` → exports classes **after transformation** (who patched what).
- `-Dmixin.debug.verbose=true` and `-Dmixin.checks=true` → details of applications/conflicts.

We build the overlap map from what the loader _actually did_, not from declared targets.

## 8. The runtime runner (heart of the project)

Proven pattern: a modded server runs headless via `java -Xmx<N>G -jar <server>.jar nogui`. The
ready-made `itzg/minecraft-server` image boots any loader behind one mechanism — the loader is
detected from the jars and passed as the image `TYPE` (FABRIC/QUILT/FORGE/NEOFORGE), with the
exact MC version + JDK from the profile (`jdk`); the loader build is auto-resolved per version.

**Boot loop (Python orchestrator):**

1. Prepare a container: itzg image at the profile's jdk, image `TYPE` = the detected loader,
   exact MC version, + injected subset of mods.
2. Launch the boot, mixin debug flags enabled, timeout.
3. The server loads: mixins → registry freeze → datapacks/recipes. We don't need to go further
   (no gameplay); cut off after the registry freeze / world load.
4. Capture `latest.log`, `crash-reports/`, mixin export → **classify**: OK / crash + cause.

**Security:** running jars = arbitrary code. Isolation via container (restricted filesystem +
network), never directly on the host.

**Bisection:** when a set crashes, binary search → ~log2(N) boots to isolate the **guilty pair**
(~9 boots for 400 mods). This is the differentiating feature: automating what pack devs do by
hand.

**Cost to accept:** each boot of a large pack = minutes + significant RAM. Bisection limits the
_number_ of boots, not their unit weight.

## 9. Data model — conflict map

Pivot output of both the static analyzer AND the runner (unified format, consumed by the front and
by the resolution generator). Sketch:

```jsonc
{
  "profile": "1.21.1", // version profile used for this analysis
  "mods": [
    {
      "id": "examplemod",
      "version": "1.2.0",
      "mcVersion": "1.21.1",
      "environment": "server" /* server | client | "*" */,
      "depends": { "fabric-api": "*" },
      "jar": "examplemod-1.2.0.jar",
    },
  ],
  "conflicts": [
    {
      "type": "tag_overlap", // tag_overlap | recipe_collision | mixin_overlap | dependency | duplicate_jar
      "severity": "info", // info | warning | error
      "detectedBy": "static", // static | runtime
      "members": ["modA", "modB"], // mods involved
      "detail": {
        "tag": "c:tin_ingots",
        "items": ["modA:tin_ingot", "modB:tin_ingot"],
      },
      "resolution": {
        "strategy": "almost_unified", // almost_unified | recipe_override | manual | remove_duplicate
        "generated": "config/almostunified/unify.json",
      },
    },
  ],
  "untestable": [
    {
      "id": "shadermod",
      "reason": "environment:client not loaded by server boot",
    },
  ],
}
```

## 10. MVP breakdown (to be driven by Claude Code)

Each phase is **shippable** and has a clear acceptance criterion.

**Phase 0 — Foundation**
Tauri + React/Vite (TS) scaffolding; local FastAPI; ingestion of a `mods/` folder;
parsing of `fabric.mod.json` → list of mods + versions + `environment` displayed in the UI.
_DoD:_ drop a folder, see the mod list and the count of non-testable mods.

**Phase 1 — Static analyzer**
Loads the **version profile** (§6, profile `1.21.1` in the MVP) — no path/format constant
hardcoded. Unzipping jars; detection of tag_overlap, recipe_collision, mixin_overlap (declared),
dependency, duplicate_jar; production of the **conflict map** (§9); sortable UI rendering.
_DoD:_ on a real 1.21.1 set, a coherent conflict map, 100% offline, in a few seconds;
changing profile would require no logic change.

**Phase 2 — Headless runner**
Docker Fabric server container whose JDK and Fabric API come from the profile; boot of a given set
with mixin debug flags; capture + classification of the log (OK / crash + cause). No bisection
yet.
_DoD:_ a "test this set" button → reliable verdict with the cause extracted from the log, on the
1.21.1 target.

**Phase 3 — Automated bisection**
When a boot crashes: orchestrated binary search down to the guilty pair(s);
report in the conflict map (`detectedBy: runtime`).
_DoD:_ on a known injected conflict, the pair is isolated automatically in ~log2(N) boots.

**Phase 4 — No-code resolution**
Generation of `unify.json` (tag_overlap) and an override datapack (recipe_collision); preview
and export from the UI.
_DoD:_ a duplication conflict is resolved by a generated file, without writing code.

## 11. Working conventions

- Strictly incremental phases; do not start the next one until the DoD is met.
- The **conflict map (§9)** is the contract between layers; the **version profile (§6)** is the
  contract between versions. Static, runtime and the resolution generator all conform to them.
- Tests: at minimum a set of mod fixtures (real or fake) targeting **1.21.1**, reproducing each
  conflict category, to validate static + runtime deterministically.
- Runtime boots always in an isolated container, never on the host.
- Explicitly document in the UI everything that is out of scope (client-only mods, silent
  conflicts) so as not to give a false impression of exhaustiveness.

## 12. References / prior art

- **Almost Unified** — content unification by dominant tag + recipe rewriting; generation target
  of the MVP. Config `config/almostunified/unify.json`, `tagOwnerships`.
- **PackTest** — proof of the headless Fabric server pattern in CI (gametests via datapack).
- **Crash Assistant / MCDoctor.ai / MCLA (mclo.gs)** — log error classification to reuse.
- **Fabric server Docker images** — base of the runner (OpenJDK + configurable loader, `nogui`).
- **SpongePowered Mixin** — flags `mixin.debug.export`, `mixin.debug.verbose`, `mixin.checks`.

## 13. Glossary

- **Mixin**: mechanism for injecting bytecode into vanilla/mod classes at load time.
- **Tag**: grouping of items/blocks (`c:tin_ingots`) used by recipes; key to unification.
- **Item components**: item data format since 1.20.5 (replaces the old NBT).
- **Version profile**: an object of constants (jdk, item format, datapack folders, tag namespace,
  Fabric API) that decouples the tool's logic from the targeted Minecraft version.
- **Registry freeze**: the load-time moment when registries become immutable; most load-time
  conflicts manifest before/at this point.
- **Bisection**: binary search over the mod set to isolate a guilty pair.
