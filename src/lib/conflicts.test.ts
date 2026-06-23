import { describe, expect, it } from "vitest";
import subjectFixture from "./__fixtures__/conflict-subjects.json";
import type { Conflict, Mod, RunVerdict } from "./api";
import {
  conflictKey,
  conflictSubject,
  countBySeverity,
  groupMixinClusters,
  isRuntimeConfirmed,
  planMixinAutoFix,
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

  // Cross-stack contract (todo.md > Cross-cutting): the subject the front reads
  // from detail.recipe / detail.tag must equal the id the backend derives from the
  // jar path. The shared fixture is the single source of truth; the backend test
  // (test_subject_keys.py) pins its derivation to these same `subject` values.
  it("reads the same subject the backend derives (shared fixture)", () => {
    for (const { subject } of subjectFixture.recipe_collision) {
      expect(conflictSubject(mk({ type: "recipe_collision", detail: { recipe: subject } }))).toBe(
        subject,
      );
    }
    for (const { subject } of subjectFixture.tag_overlap) {
      expect(conflictSubject(mk({ type: "tag_overlap", detail: { tag: subject } }))).toBe(subject);
    }
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

  it("flags a many-mod co-patch as broad, a small one as actionable", () => {
    const small = mk({
      type: "mixin_overlap",
      severity: "warning",
      members: ["a", "b"],
      detail: { target: "t_small", sharedMethods: ["m"] },
    });
    const broad = mk({
      type: "mixin_overlap",
      severity: "warning",
      members: ["m1", "m2", "m3", "m4", "m5"], // > MIXIN_PAIRWISE_MAX
      detail: { target: "t_broad", sharedMethods: ["tick"] },
    });
    const clusters = groupMixinClusters([broad, small], [], null);

    const byTarget = Object.fromEntries(clusters.map((c) => [c.targets[0], c]));
    expect(byTarget.t_small.broad).toBe(false);
    expect(byTarget.t_broad.broad).toBe(true);
  });

  it("sorts actionable clusters before broad co-patches", () => {
    // A broad co-patch that is runtime-confirmed must still rank below an
    // unconfirmed pairwise pick — actionability wins over the confirmation flag.
    const broadConfirmed = mk({
      type: "mixin_overlap",
      severity: "info",
      members: ["a", "b", "c", "d", "e", "f"],
      detail: { target: "net.minecraft.class_310" },
    });
    const pair = mk({
      type: "mixin_overlap",
      severity: "warning",
      members: ["x", "y"],
      detail: { target: "t_pair", sharedMethods: ["m"] },
    });
    const exports = new Set(["net.minecraft.class_310"]);
    const clusters = groupMixinClusters([broadConfirmed, pair], [], exports);

    expect(clusters.map((c) => c.broad)).toEqual([false, true]);
    expect(clusters[0].targets).toEqual(["t_pair"]);
    expect(clusters[1].confirmedAtRuntime).toBe(true);
  });
});

describe("planMixinAutoFix", () => {
  // A warning-severity same-method overlap between two mods — one actionable cluster.
  const pair = (a: string, b: string) =>
    mk({
      type: "mixin_overlap",
      severity: "warning",
      members: [a, b].sort(),
      detail: { target: "t", sharedMethods: ["m"] },
    });

  it("counts dependents and disables the leaf, keeping the load-bearing mod", () => {
    const mods = [
      mkMod({ id: "lib", jar: "lib.jar" }),
      mkMod({ id: "consumer", jar: "consumer.jar", depends: { lib: "*" } }),
    ];
    const [cluster] = groupMixinClusters([pair("lib", "consumer")], mods, null);
    expect(cluster.members.find((m) => m.modId === "lib")?.dependents).toBe(1);
    expect(cluster.members.find((m) => m.modId === "consumer")?.dependents).toBe(0);
    expect(planMixinAutoFix(cluster)).toEqual({
      kind: "disable",
      keep: "lib",
      jars: ["consumer.jar"],
    });
  });

  it("prefers centrality over an available update", () => {
    const mods = [
      mkMod({ id: "lib", jar: "lib.jar" }),
      mkMod({
        id: "consumer",
        jar: "consumer.jar",
        depends: { lib: "*" },
        updateAvailable: true,
        latestVersion: "2.0",
      }),
    ];
    const [cluster] = groupMixinClusters([pair("lib", "consumer")], mods, null);
    expect(planMixinAutoFix(cluster)).toEqual({
      kind: "disable",
      keep: "lib",
      jars: ["consumer.jar"],
    });
  });

  it("updates when no mod is more central", () => {
    const mods = [
      mkMod({ id: "a", jar: "a.jar" }),
      mkMod({ id: "b", jar: "b.jar", updateAvailable: true, latestVersion: "2.0" }),
    ];
    const [cluster] = groupMixinClusters([pair("a", "b")], mods, null);
    expect(planMixinAutoFix(cluster)).toEqual({
      kind: "update",
      jars: [{ jar: "b.jar", loader: "fabric" }],
    });
  });

  it("falls back to the library role (most provides) when nothing else decides", () => {
    const mods = [
      mkMod({ id: "a", jar: "a.jar", provides: ["someapi"] }),
      mkMod({ id: "b", jar: "b.jar" }),
    ];
    const [cluster] = groupMixinClusters([pair("a", "b")], mods, null);
    expect(planMixinAutoFix(cluster)).toEqual({
      kind: "disable",
      keep: "a",
      jars: ["b.jar"],
    });
  });

  it("leaves an undecidable cluster to the user", () => {
    const mods = [mkMod({ id: "a", jar: "a.jar" }), mkMod({ id: "b", jar: "b.jar" })];
    const [cluster] = groupMixinClusters([pair("a", "b")], mods, null);
    expect(planMixinAutoFix(cluster)).toEqual({ kind: "none" });
  });

  it("never disables a loser that other mods depend on", () => {
    // a is more central (2 dependents) than b (1), but b is still load-bearing —
    // disabling it would break its dependent, so the cluster is left alone.
    const mods = [
      mkMod({ id: "a", jar: "a.jar" }),
      mkMod({ id: "b", jar: "b.jar" }),
      mkMod({ id: "c", jar: "c.jar", depends: { a: "*" } }),
      mkMod({ id: "d", jar: "d.jar", depends: { a: "*" } }),
      mkMod({ id: "e", jar: "e.jar", depends: { b: "*" } }),
    ];
    const [cluster] = groupMixinClusters([pair("a", "b")], mods, null);
    expect(cluster.members.find((m) => m.modId === "a")?.dependents).toBe(2);
    expect(cluster.members.find((m) => m.modId === "b")?.dependents).toBe(1);
    expect(planMixinAutoFix(cluster)).toEqual({ kind: "none" });
  });

  it("disables only the leaf loser, sparing a load-bearing one", () => {
    const mods = [
      mkMod({ id: "a", jar: "a.jar" }),
      mkMod({ id: "b", jar: "b.jar" }),
      mkMod({ id: "c", jar: "c.jar" }),
      mkMod({ id: "dep1", jar: "dep1.jar", depends: { a: "*" } }),
      mkMod({ id: "dep2", jar: "dep2.jar", depends: { a: "*" } }),
      mkMod({ id: "dep3", jar: "dep3.jar", depends: { b: "*" } }),
    ];
    const conflict = mk({
      type: "mixin_overlap",
      severity: "warning",
      members: ["a", "b", "c"],
      detail: { target: "t", sharedMethods: ["m"] },
    });
    const [cluster] = groupMixinClusters([conflict], mods, null);
    // a: 2 dependents (keeper), b: 1 (load-bearing, spared), c: 0 (leaf, disabled).
    expect(planMixinAutoFix(cluster)).toEqual({
      kind: "disable",
      keep: "a",
      jars: ["c.jar"],
    });
  });
});
