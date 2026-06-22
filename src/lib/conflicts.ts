// Pure helpers for presenting the conflict map (PROJECT.md §9).
import type { Conflict, Mod, Severity } from "./api";

export const CONFLICT_LABEL: Record<Conflict["type"], string> = {
  duplicate_jar: "duplicate jar",
  dependency: "dependency",
  tag_overlap: "tag overlap",
  recipe_collision: "recipe collision",
  mixin_overlap: "mixin overlap",
};

export const SEVERITY_ORDER: Severity[] = ["error", "warning", "info"];

// The axis users actually triage on (§9): what does this conflict *do*?
//   blocking        — the loader refuses to start (duplicate id, missing dep)
//   silent_override — one definition silently wins (recipe / same-method mixin)
//   benign          — expected coexistence, usually no effect (class mixin, tag)
// Severity already encodes this exact split (error/warning/info), so the map is
// a pure relabel; keeping it here keeps the consequence vocabulary in one place.
export type Consequence = "blocking" | "silent_override" | "benign";

export const CONSEQUENCE_ORDER: Consequence[] = ["blocking", "silent_override", "benign"];

export const CONSEQUENCE_LABEL: Record<Consequence, string> = {
  blocking: "Blocking",
  silent_override: "Silent override",
  benign: "Probably OK",
};

export const CONSEQUENCE_HINT: Record<Consequence, string> = {
  blocking: "the loader refuses to start",
  silent_override: "one definition overwrites another, without warning",
  benign: "expected coexistence, usually harmless",
};

export function conflictConsequence(c: Conflict): Consequence {
  if (c.severity === "error") return "blocking";
  if (c.severity === "warning") return "silent_override";
  return "benign";
}

// Type-specific `detail` payloads promoted into the row body (detectors.py).
// Each is defensive: the payload is `Record<string, unknown>` over the wire.
export function conflictJars(c: Conflict): string[] {
  return Array.isArray(c.detail.jars) ? c.detail.jars.map(String) : [];
}

export function conflictItems(c: Conflict): string[] {
  return Array.isArray(c.detail.items) ? c.detail.items.map(String) : [];
}

export function conflictSharedMethods(c: Conflict): string[] {
  return Array.isArray(c.detail.sharedMethods) ? c.detail.sharedMethods.map(String) : [];
}

// tag_overlap only: { mod id -> item ids it contributes to the shared tag }.
export function conflictByMod(c: Conflict): Record<string, string[]> {
  const raw = c.detail.byMod;
  if (!raw || typeof raw !== "object") return {};
  const out: Record<string, string[]> = {};
  for (const [mod, items] of Object.entries(raw as Record<string, unknown>)) {
    out[mod] = Array.isArray(items) ? items.map(String) : [];
  }
  return out;
}

// dependency only: the needy mod and the id it can't find.
export function dependencyRelation(c: Conflict): { mod: string; missing: string } {
  return {
    mod: String(c.detail.mod ?? c.members[0] ?? ""),
    missing: String(c.detail.missing ?? ""),
  };
}

// A human one-liner from `resolution` when the Phase 4 generator filled it.
export function resolutionNote(c: Conflict): string | null {
  if (!c.resolution) return null;
  for (const key of ["note", "reason", "summary"]) {
    const v = c.resolution[key];
    if (typeof v === "string" && v) return v;
  }
  return null;
}

export const isRecipeCollision = (c: Conflict): boolean => c.type === "recipe_collision";

// One-line subject for a conflict row, by type.
export function conflictSubject(c: Conflict): string {
  const d = c.detail;
  switch (c.type) {
    case "duplicate_jar":
      return String(d.modId ?? "");
    case "dependency":
      return `missing ${String(d.missing ?? "")}`;
    case "tag_overlap":
      return String(d.tag ?? "");
    case "recipe_collision":
      return String(d.recipe ?? "");
    case "mixin_overlap":
      return String(d.target ?? "");
  }
}

export function countBySeverity(conflicts: Conflict[]): Record<Severity, number> {
  const counts: Record<Severity, number> = { error: 0, warning: 0, info: 0 };
  for (const c of conflicts) counts[c.severity]++;
  return counts;
}

// A mixin_overlap candidate is confirmed when the loader actually transformed
// its target class (present in the runtime mixin export). This is the static →
// runtime link the analyzer promises (§7).
export function isRuntimeConfirmed(conflict: Conflict, mixinExports: Set<string> | null): boolean {
  if (!mixinExports || conflict.type !== "mixin_overlap") return false;
  const target = conflict.detail.target;
  return typeof target === "string" && mixinExports.has(target);
}

// Stable React key for a conflict row.
export function conflictKey(c: Conflict): string {
  return `${c.type}-${conflictSubject(c)}-${c.members.join(",")}`;
}

// --- Mixin resolver: actionable clusters from the static overlap map ---------
// The two-stage resolution the runner verdict can't do alone (PROJECT.md §7):
//   1. disambiguate — a "mixin apply failed" line names only the *reporting* mod;
//      the co-patchers are the other members sharing its target/method here.
//   2. version-match — each member carries its enrichment (updateAvailable +
//      latestVersion), so the front can offer "update to a compatible build"
//      first, and a reversible disable as the fallback.

export interface MixinClusterMember {
  modId: string;
  mod: Mod | null; // resolved top-level jar (null for a bundled/nested-only id)
  jar: string | null;
  currentVersion: string | null;
  latestVersion: string | null;
  updateAvailable: boolean;
}

export interface MixinCluster {
  key: string; // stable React key + headline ("modA ↔ modB")
  members: MixinClusterMember[];
  targets: string[]; // shared target classes across the cluster's overlaps
  sharedMethods: string[]; // shared *method* names — the strong-conflict signal
  confirmedAtRuntime: boolean; // a target was actually transformed at boot
}

// Build the actionable mixin clusters from the static `mixin_overlap` conflicts.
// Only strong candidates surface: same-method overlaps (severity `warning`), plus
// any class-level overlap the runtime actually transformed (`mixinExports`) — the
// many benign class-only co-patches (e.g. MinecraftClient) stay out as noise.
// Clusters group by the *set of mods* (a pair sharing several methods is one
// cluster), runtime-confirmed first.
export function groupMixinClusters(
  conflicts: Conflict[],
  mods: Mod[],
  mixinExports: Set<string> | null,
): MixinCluster[] {
  const byId = new Map(mods.map((m) => [m.id, m] as const));
  interface Acc {
    members: string[];
    targets: Set<string>;
    methods: Set<string>;
    confirmed: boolean;
  }
  const byMembers = new Map<string, Acc>();

  for (const c of conflicts) {
    if (c.type !== "mixin_overlap") continue;
    const shared = conflictSharedMethods(c);
    const confirmed = isRuntimeConfirmed(c, mixinExports);
    if (shared.length === 0 && !confirmed) continue; // benign class-only overlap
    const key = c.members.join(" ↔ ");
    let acc = byMembers.get(key);
    if (!acc) {
      acc = { members: c.members, targets: new Set(), methods: new Set(), confirmed: false };
      byMembers.set(key, acc);
    }
    const target = c.detail.target;
    if (typeof target === "string" && target) acc.targets.add(target);
    for (const m of shared) acc.methods.add(m);
    acc.confirmed = acc.confirmed || confirmed;
  }

  const clusters: MixinCluster[] = [];
  for (const [key, acc] of byMembers) {
    const members = acc.members.map((id): MixinClusterMember => {
      const mod = byId.get(id) ?? null;
      return {
        modId: id,
        mod,
        jar: mod?.jar ?? null,
        currentVersion: mod?.version ?? null,
        latestVersion: mod?.latestVersion ?? null,
        updateAvailable: Boolean(mod?.updateAvailable),
      };
    });
    clusters.push({
      key,
      members,
      targets: [...acc.targets].sort(),
      sharedMethods: [...acc.methods].sort(),
      confirmedAtRuntime: acc.confirmed,
    });
  }
  clusters.sort(
    (a, b) =>
      Number(b.confirmedAtRuntime) - Number(a.confirmedAtRuntime) || a.key.localeCompare(b.key),
  );
  return clusters;
}
