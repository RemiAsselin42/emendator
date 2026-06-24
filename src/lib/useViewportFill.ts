import { type RefCallback, useCallback, useRef } from "react";

// Never collapse the list to nothing, even when little vertical room is left.
const MIN_HEIGHT = 120;
// Breathing room between the list's bottom and the viewport edge.
export const BOTTOM_GAP = 50;

// A scroll container's available height is "the viewport, minus everything that
// must stay visible around it" — the header and any sub-tabs/filters *above* it,
// and any siblings *below* it (a "broad co-patches" section, a notes line). CSS
// `calc()` can't read those sibling heights, so a static `100vh - <magic>` offset
// is always wrong: too small and the list overflows the viewport (hiding whatever
// sits below it), too large and it wastes space.
//
// So measure it live: cap `max-height` at `innerHeight - top - below - gap`, where
// `top` is the element's distance from the top of the viewport (covers the header
// + sub-tabs + filters) and `below` is the total height of the following siblings
// (keeps them on screen). Both depend only on layout *outside* the list, never on
// its own capped height, so writing the cap back can't loop.
//
// The cap is written as an inline pixel `max-height` (not a CSS custom property):
// it's directly inspectable, overrides the stylesheet, and avoids any dependency
// on `dvh`/`calc()` support.
//
// Returns a 'callback ref' rather than taking a RefObject: these lists are
// conditionally rendered (a filter or a tab can mount them after the parent), and
// a callback ref fires exactly when the node attaches — an effect keyed on a ref
// object would run once at mount, find it empty, and never retry. Measuring inside
// the ref callback (commit phase) also sets the height before first paint, so the
// list never flashes unbounded.
//
// `climb`: also reserve room for the following siblings of every *ancestor*, not
// just the list's own. Needed when the list is nested inside a collapsible panel
// (an accordion `<details>`): the panels below it are siblings of the panel, not of
// the list, so without climbing they'd be pushed under the fold.
export function useViewportFill(climb = false): RefCallback<HTMLDivElement> {
  // Holds the live element and its teardown so a detach (or a swap to a different
  // node) tears down the previous observers before wiring up the new one.
  const active = useRef<{ el: HTMLDivElement; cleanup: () => void } | null>(null);

  return useCallback(
    (el: HTMLDivElement | null) => {
      const prev = active.current;
      if (prev?.el === el) return; // same node — nothing to do
      if (prev) {
        prev.cleanup();
        active.current = null;
      }
      if (!el) return;

      let frame = 0;
      const measure = () => {
        frame = 0;
        const top = el.getBoundingClientRect().top;

        // Reserve room for whatever follows the list on screen, plus the flex gap
        // before each of those siblings, so they stay visible instead of being pushed
        // under the fold. With `climb`, walk up the ancestors too (each level's
        // following siblings), so a list nested in a collapsible panel still leaves
        // room for the panels below it. Sibling heights don't depend on the list's own
        // height, so this stays stable once the cap is applied.
        let below = 0;
        for (let node: Element | null = el; node && node !== document.body; ) {
          const parent: HTMLElement | null = node.parentElement;
          const gap = parent ? Number.parseFloat(getComputedStyle(parent).rowGap) || 0 : 0;
          for (let s = node.nextElementSibling; s; s = s.nextElementSibling) {
            below += (s as HTMLElement).getBoundingClientRect().height + gap;
          }
          node = climb ? parent : null;
        }

        // Optional per-list trim: a stylesheet can shave a fixed amount off the
        // computed height by setting `--vfill-trim` on the list (e.g. .conflict-groups
        // trims one space-md). Unlike a margin it adds no layout box, so it only
        // shortens this list — it can't grow a section when two lists are chained.
        const trim = Number.parseFloat(getComputedStyle(el).getPropertyValue("--vfill-trim")) || 0;

        const avail = window.innerHeight - top - below - trim - BOTTOM_GAP;
        const next = `${Math.max(MIN_HEIGHT, Math.round(avail))}px`;
        // Skip redundant writes so the ResizeObserver below can't ping-pong off our
        // own style mutation.
        if (el.style.maxHeight !== next) el.style.maxHeight = next;
      };
      // Coalesce bursts (a resize that triggers several reflows) into one measure.
      const schedule = () => {
        if (frame === 0) frame = requestAnimationFrame(measure);
      };

      measure();
      window.addEventListener("resize", schedule);
      // Any reflow that moves the list or resizes a sibling — header changing height,
      // sub-tabs/filters appearing or wrapping, the section below expanding — shifts
      // the document's size, so observing the root catches every case without
      // enumerating the specific elements.
      const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(schedule) : null;
      ro?.observe(document.documentElement);

      active.current = {
        el,
        cleanup: () => {
          if (frame) cancelAnimationFrame(frame);
          window.removeEventListener("resize", schedule);
          ro?.disconnect();
        },
      };
    },
    [climb],
  );
}
