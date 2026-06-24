import { act, renderHook } from "@testing-library/react";
import type { SyntheticEvent } from "react";
import { describe, expect, it } from "vitest";
import { useAccordion } from "./useAccordion";

// A minimal stand-in for the <details> toggle event the hook reads off currentTarget.
function toggle(open: boolean): SyntheticEvent<HTMLDetailsElement> {
  return { currentTarget: { open } } as unknown as SyntheticEvent<HTMLDetailsElement>;
}

describe("useAccordion", () => {
  it("starts on the initial key", () => {
    const { result } = renderHook(() => useAccordion("a"));
    expect(result.current.openKey).toBe("a");
    expect(result.current.item("a").open).toBe(true);
    expect(result.current.item("b").open).toBe(false);
  });

  it("defaults to all-closed without an initial key", () => {
    const { result } = renderHook(() => useAccordion());
    expect(result.current.openKey).toBeNull();
  });

  it("opening one closes the others", () => {
    const { result } = renderHook(() => useAccordion("a"));
    act(() => result.current.item("b").onToggle(toggle(true)));
    expect(result.current.openKey).toBe("b");
    expect(result.current.item("a").open).toBe(false);
  });

  it("collapsing the open one clears the group", () => {
    const { result } = renderHook(() => useAccordion("a"));
    act(() => result.current.item("a").onToggle(toggle(false)));
    expect(result.current.openKey).toBeNull();
  });

  it("a sibling closing doesn't clobber the freshly opened panel", () => {
    const { result } = renderHook(() => useAccordion("a"));
    act(() => result.current.item("b").onToggle(toggle(true))); // open b
    act(() => result.current.item("a").onToggle(toggle(false))); // React then closes a
    expect(result.current.openKey).toBe("b");
  });
});
