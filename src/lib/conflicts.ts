// Pure helpers for presenting the conflict map (PROJECT.md §9).
import type { Conflict, RunVerdict, Severity } from "./api";

export const CONFLICT_LABEL: Record<Conflict["type"], string> = {
  duplicate_jar: "duplicate jar",
  dependency: "dependency",
  tag_overlap: "tag overlap",
  recipe_collision: "recipe collision",
  mixin_overlap: "mixin overlap",
};

export const SEVERITY_ORDER: Severity[] = ["error", "warning", "info"];

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
export function isRuntimeConfirmed(conflict: Conflict, verdict: RunVerdict | null): boolean {
  if (!verdict || conflict.type !== "mixin_overlap") return false;
  const target = conflict.detail.target;
  return typeof target === "string" && verdict.mixinExports.includes(target);
}

// Stable React key for a conflict row.
export function conflictKey(c: Conflict): string {
  return `${c.type}-${conflictSubject(c)}-${c.members.join(",")}`;
}
