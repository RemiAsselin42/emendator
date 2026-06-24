import { fireEvent, render } from "@testing-library/react";
import { type CSSProperties, useState } from "react";
import { afterEach, beforeAll, expect, test } from "vitest";
import { VirtualList } from "../components/VirtualList";
import { BOTTOM_GAP, useViewportFill } from "./useViewportFill";

beforeAll(() => {
  // jsdom ships no ResizeObserver; a no-op stub lets the hook and VirtualList
  // mount. Layout is faked via getBoundingClientRect below.
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  Object.defineProperty(window, "innerHeight", { configurable: true, value: 1000 });
  // jsdom has no layout, so getBoundingClientRect returns zeros. Read fake
  // dimensions off data-* attributes instead: `data-top` for the list's distance
  // from the viewport top, `data-h` for a sibling's height.
  Element.prototype.getBoundingClientRect = function () {
    const el = this as HTMLElement;
    return {
      top: Number(el.dataset.top ?? 0),
      height: Number(el.dataset.h ?? 0),
      bottom: 0,
      left: 0,
      right: 0,
      width: 0,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    } as DOMRect;
  };
});

afterEach(() => {
  Object.defineProperty(window, "innerHeight", { configurable: true, value: 1000 });
});

function Plain({ top = 0 }: { top?: number }) {
  const fill = useViewportFill();
  return <div ref={fill} className="conflict-groups" data-testid="plain" data-top={top} />;
}

test("caps a plain scroll container at viewport minus its top offset", () => {
  const { getByTestId } = render(<Plain top={300} />);
  expect(getByTestId("plain").style.maxHeight).toBe(`${1000 - 300 - BOTTOM_GAP}px`);
});

function Gated() {
  const fill = useViewportFill();
  const [show, setShow] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setShow(true)}>
        show
      </button>
      {show && <div ref={fill} className="conflict-groups" data-testid="late" data-top="200" />}
    </>
  );
}

// The original bug: the list is conditionally rendered, so it isn't in the DOM at
// the parent's first mount. A ref-object effect would run once, find nothing, and
// give up; the callback ref fires when the node finally appears.
test("caps a list that appears after the initial mount", () => {
  const { getByText, getByTestId } = render(<Gated />);
  fireEvent.click(getByText("show"));
  expect(getByTestId("late").style.maxHeight).toBe(`${1000 - 200 - BOTTOM_GAP}px`);
});

function WithSiblingBelow() {
  const fill = useViewportFill();
  return (
    <div>
      <div ref={fill} className="conflict-groups" data-testid="list" data-top="100" />
      <div data-testid="below" data-h="250" />
    </div>
  );
}

// The reported bug: a sibling below the list was pushed off-screen because the cap
// reserved no room for it. The cap must subtract the following sibling's height.
test("reserves room for siblings below the list", () => {
  const { getByTestId } = render(<WithSiblingBelow />);
  expect(getByTestId("list").style.maxHeight).toBe(`${1000 - 100 - 250 - BOTTOM_GAP}px`);
});

function NestedWithUncleBelow() {
  const fill = useViewportFill(true); // climb past the <details> panel
  return (
    <div>
      <details open>
        <summary>head</summary>
        {/* The list's only DOM sibling here is none; the uncle below is an ancestor's
            sibling, reachable only by climbing. */}
        <div ref={fill} className="conflict-groups" data-testid="nested" data-top="100" />
      </details>
      <div data-testid="uncle" data-h="80" />
    </div>
  );
}

// A list nested in a collapsible panel must still reserve room for the panels that
// follow that panel (its ancestor's siblings), not just its own.
test("climb reserves room for ancestors' following siblings", () => {
  const { getByTestId } = render(<NestedWithUncleBelow />);
  expect(getByTestId("nested").style.maxHeight).toBe(`${1000 - 100 - 80 - BOTTOM_GAP}px`);
});

function WithTrim() {
  const fill = useViewportFill();
  return (
    <div
      ref={fill}
      className="conflict-groups"
      data-testid="trimmed"
      data-top="100"
      style={{ "--vfill-trim": "16px" } as CSSProperties}
    />
  );
}

// A `--vfill-trim` on the list shortens the computed height (no layout box, so it
// can't grow a section when lists are chained).
test("subtracts a --vfill-trim set on the list", () => {
  const { getByTestId } = render(<WithTrim />);
  expect(getByTestId("trimmed").style.maxHeight).toBe(`${1000 - 100 - 16 - BOTTOM_GAP}px`);
});

test("never caps below the minimum height", () => {
  // top alone exceeds the viewport — clamp instead of going negative.
  const { getByTestId } = render(<Plain top={2000} />);
  expect(getByTestId("plain").style.maxHeight).toBe("120px");
});

function Virtual() {
  const fill = useViewportFill();
  return (
    <VirtualList
      items={[{ k: "a" }, { k: "b" }]}
      keyOf={(i) => i.k}
      estimate={20}
      className="conflict-groups"
      scrollRef={fill}
      renderItem={(i) => <div>{i.k}</div>}
    />
  );
}

test("caps a VirtualList scroll container via scrollRef", () => {
  const { container } = render(<Virtual />);
  const el = container.querySelector(".conflict-groups") as HTMLElement;
  expect(el.style.maxHeight).toBe(`${1000 - BOTTOM_GAP}px`);
});
