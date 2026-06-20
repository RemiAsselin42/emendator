import { describe, expect, it } from "vitest";
import type { Conflict, RunVerdict } from "./api";
import { conflictKey, conflictSubject, countBySeverity, isRuntimeConfirmed } from "./conflicts";

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
    expect(isRuntimeConfirmed(hit, verdict)).toBe(true);
    expect(isRuntimeConfirmed(miss, verdict)).toBe(false);
    expect(isRuntimeConfirmed(mk({ type: "tag_overlap" }), verdict)).toBe(false);
    expect(isRuntimeConfirmed(hit, null)).toBe(false);
  });

  it("builds a stable key", () => {
    expect(conflictKey(mk({ type: "dependency", detail: { missing: "b" }, members: ["a"] }))).toBe(
      "dependency-missing b-a",
    );
  });
});
