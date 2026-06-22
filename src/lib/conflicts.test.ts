import { describe, expect, it } from "vitest";
import type { Conflict, Mod, RunVerdict } from "./api";
import {
  conflictKey,
  conflictSubject,
  countBySeverity,
  groupMixinClusters,
  isRuntimeConfirmed,
} from "./conflicts";

function mk(partial: Partial<Conflict>): Conflict {
  return {
    type: "mixin_overlap",
    severity: "info",
    detectedBy: "static",
    members: [],
    detail: {},
    resolution: null,
    ...partial,
  };
}

function mkMod(partial: Partial<Mod> & { id: string }): Mod {
  return {
    name: null,
    version: null,
    mcVersion: null,
    environment: "*",
    loader: "fabric",
    depends: {},
    provides: [],
    jar: `${partial.id}.jar`,
    provider: null,
    homepage: null,
    latestVersion: null,
    updateAvailable: null,
    ...partial,
  };
}

const verdict: RunVerdict = {
  status: "ok",
  profile: "1.21.1",
  durationMs: 1,
  cause: null,
  mixinExports: ["net.minecraft.class_310"],
  logTail: null,
};

describe("conflicts helpers", () => {
  it("counts by severity", () => {
    const counts = countBySeverity([
      mk({ severity: "error" }),
      mk({ severity: "info" }),
      mk({ severity: "info" }),
    ]);
    expect(counts).toEqual({ error: 1, warning: 0, info: 2 });
  });

  it("builds a subject per type", () => {
    expect(conflictSubject(mk({ type: "dependency", detail: { missing: "fabric-api" } }))).toBe(
      "missing fabric-api",
    );
    expect(
      conflictSubject(mk({ type: "mixin_overlap", detail: { target: "net.minecraft.class_310" } })),
    ).toBe("net.minecraft.class_310");
  });

  it("confirms a mixin candidate against the runtime export", () => {
    const hit = mk({ type: "mixin_overlap", detail: { target: "net.minecraft.class_310" } });
    const miss = mk({ type: "mixin_overlap", detail: { target: "net.minecraft.class_999" } });
    const exports = new Set(verdict.mixinExports);
    expect(isRuntimeConfirmed(hit, exports)).toBe(true);
    expect(isRuntimeConfirmed(miss, exports)).toBe(false);
    expect(isRuntimeConfirmed(mk({ type: "tag_overlap" }), exports)).toBe(false);
    expect(isRuntimeConfirmed(hit, null)).toBe(false);
  });

  it("builds a stable key", () => {
    expect(conflictKey(mk({ type: "dependency", detail: { missing: "b" }, members: ["a"] }))).toBe(
      "dependency-missing b-a",
    );
  });
});

describe("groupMixinClusters", () => {
  it("keeps same-method overlaps and drops benign class-only ones", () => {
    const conflicts = [
      mk({
        type: "mixin_overlap",
        severity: "warning",
        members: ["spell_engine", "combatroll"],
        detail: { target: "net.minecraft.class_1309", sharedMethods: ["tick"] },
      }),
      mk({
        type: "mixin_overlap",
        severity: "info",
        members: ["a", "b"],
        detail: { target: "net.minecraft.class_310" },
      }),
    ];
    const mods = [
      mkMod({ id: "spell_engine", version: "1.0", updateAvailable: true, latestVersion: "2.0" }),
      mkMod({ id: "combatroll" }),
    ];
    const clusters = groupMixinClusters(conflicts, mods, null);

    expect(clusters).toHaveLength(1);
    expect(clusters[0].members.map((m) => m.modId)).toEqual(["spell_engine", "combatroll"]);
    expect(clusters[0].sharedMethods).toEqual(["tick"]);
    // The first member is enriched: its jar + version-match update are attached.
    expect(clusters[0].members[0].jar).toBe("spell_engine.jar");
    expect(clusters[0].members[0].updateAvailable).toBe(true);
    expect(clusters[0].members[0].latestVersion).toBe("2.0");
    // A nested/bundled id with no top-level jar stays listed but inert.
    expect(clusters[0].members[1].updateAvailable).toBe(false);
  });

  it("includes a runtime-confirmed class-only overlap and flags it", () => {
    const conflicts = [
      mk({
        type: "mixin_overlap",
        severity: "info",
        members: ["a", "b"],
        detail: { target: "net.minecraft.class_310" },
      }),
    ];
    const exports = new Set(["net.minecraft.class_310"]);
    const clusters = groupMixinClusters(conflicts, [], exports);

    expect(clusters).toHaveLength(1);
    expect(clusters[0].confirmedAtRuntime).toBe(true);
  });

  it("merges overlaps sharing the same member set into one cluster", () => {
    const conflicts = [
      mk({
        type: "mixin_overlap",
        severity: "warning",
        members: ["a", "b"],
        detail: { target: "t1", sharedMethods: ["m1"] },
      }),
      mk({
        type: "mixin_overlap",
        severity: "warning",
        members: ["a", "b"],
        detail: { target: "t2", sharedMethods: ["m2"] },
      }),
    ];
    const clusters = groupMixinClusters(conflicts, [], null);

    expect(clusters).toHaveLength(1);
    expect(clusters[0].targets).toEqual(["t1", "t2"]);
    expect(clusters[0].sharedMethods).toEqual(["m1", "m2"]);
  });
});
