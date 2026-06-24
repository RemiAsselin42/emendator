import {
  type ReactNode,
  type Ref,
  useCallback,
  useEffect,
  useLayoutEffect,
  useReducer,
  useRef,
  useState,
} from "react";

// Assign a DOM node to either a callback ref or an object ref.
function setRef<T>(ref: Ref<T> | undefined, value: T | null): void {
  if (typeof ref === "function") ref(value);
  else if (ref) ref.current = value;
}

// Rows rendered just outside the viewport, each side, so a fast scroll doesn't
// flash blank space before the next measure pass catches up.
const OVERSCAN = 4;

interface VirtualWindow {
  tops: number[];
  totalH: number;
  start: number;
  end: number;
}

// Pure windowing math: the cumulative top offset of every row (from the measured
// or estimated heights, keyed), the total scroll height, and the [start, end) slice
// intersecting the viewport plus overscan. Recomputed every render (heights is a
// mutable ref a measure pass mutates), so it's kept pure and out of the body.
function computeWindow(
  keys: string[],
  heights: Map<string, number>,
  scrollTop: number,
  viewportH: number,
  estimate: number,
  gap: number,
): VirtualWindow {
  const tops = new Array<number>(keys.length);
  let acc = 0;
  for (let i = 0; i < keys.length; i++) {
    tops[i] = acc;
    acc += (heights.get(keys[i]) ?? estimate) + gap;
  }
  const totalH = keys.length > 0 ? acc - gap : 0;

  const bottom = scrollTop + viewportH;
  let start = 0;
  while (start < keys.length) {
    const h = heights.get(keys[start]) ?? estimate;
    if (tops[start] + h >= scrollTop) break;
    start++;
  }
  let end = start;
  while (end < keys.length && tops[end] <= bottom) end++;
  start = Math.max(0, start - OVERSCAN);
  end = Math.min(keys.length, end + OVERSCAN);

  return { tops, totalH, start, end };
}

// Generic windowed list: only the rows intersecting the viewport (plus a small
// overscan) live in the DOM, so a list of hundreds renders a handful of nodes.
// Heights are variable: each rendered row is measured and cached by key, and a
// per-row ResizeObserver re-measures on any later height change — a collapsible
// `<details>` toggling, late-loading content, a font swap — so offsets stay
// correct without the caller lifting the open/closed state. The scroll container
// is the element given `className`; set a bounded height + `overflow-y: auto`
// there. `estimate` seeds off-screen rows; `gap` is the vertical space between
// rows (px). Drives the mod list, the resolution selection cards, and the
// conflict-group lists.
export function VirtualList<T>({
  items,
  keyOf,
  estimate,
  gap = 16,
  renderItem,
  scrollRef,
  className,
}: {
  items: T[];
  keyOf: (item: T) => string;
  estimate: number;
  gap?: number;
  renderItem: (item: T) => ReactNode;
  scrollRef?: Ref<HTMLDivElement | null>;
  className?: string;
}) {
  // Internal ref drives the virtualization (scroll/measure); scrollRef mirrors the
  // same element so a parent can scroll the list to top — or attach a callback ref
  // (e.g. useViewportFill) to the scroll container. Stable across renders so the
  // forwarded callback ref isn't torn down and rebuilt on every scroll re-render.
  const listRef = useRef<HTMLDivElement>(null);
  const setRoot = useCallback(
    (el: HTMLDivElement | null) => {
      listRef.current = el;
      setRef(scrollRef, el);
    },
    [scrollRef],
  );
  const heights = useRef<Map<string, number>>(new Map());
  const nodes = useRef<Map<string, HTMLDivElement>>(new Map());
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportH, setViewportH] = useState(0);
  const [, bump] = useReducer((n: number) => n + 1, 0);

  // One observer for every rendered row: a height change bumps a re-render so the
  // measure pass below recomputes the offsets. Created lazily so it already exists
  // when the first row refs fire (layout effects run too late for that).
  const rowObserver = useRef<ResizeObserver | null>(null);
  if (rowObserver.current === null && typeof ResizeObserver !== "undefined") {
    rowObserver.current = new ResizeObserver(() => bump());
  }
  useEffect(() => () => rowObserver.current?.disconnect(), []);

  const setNode = useCallback(
    (key: string) => (el: HTMLDivElement | null) => {
      const prev = nodes.current.get(key);
      if (prev && prev !== el) rowObserver.current?.unobserve(prev);
      if (el) {
        nodes.current.set(key, el);
        rowObserver.current?.observe(el);
      } else {
        nodes.current.delete(key);
      }
    },
    [],
  );

  // Track the scroll position and the visible height of the scroll container.
  useLayoutEffect(() => {
    const el = listRef.current;
    if (!el) return;
    const onScroll = () => setScrollTop(el.scrollTop);
    // A width change can reflow rows, so drop measurements and let the layout
    // effect below re-measure at the new width.
    const ro = new ResizeObserver(() => {
      setViewportH(el.clientHeight);
      heights.current.clear();
      bump();
    });
    setViewportH(el.clientHeight);
    el.addEventListener("scroll", onScroll, { passive: true });
    ro.observe(el);
    return () => {
      el.removeEventListener("scroll", onScroll);
      ro.disconnect();
    };
  }, []);

  // After each render, measure the rows currently in the DOM. If a real height
  // differs from the cache, store it and re-render so offsets settle (converges in
  // a pass or two; offsetHeight is integral, so it stops changing).
  useLayoutEffect(() => {
    let changed = false;
    for (const [key, el] of nodes.current) {
      const h = el.offsetHeight;
      if (h > 0 && heights.current.get(key) !== h) {
        heights.current.set(key, h);
        changed = true;
      }
    }
    if (changed) bump();
  });

  // Recomputed every render (not memoized): heights is a mutable ref, so a measure
  // pass that calls bump() must recompute offsets with the same `items`.
  const keys = items.map(keyOf);
  const { tops, totalH, start, end } = computeWindow(
    keys,
    heights.current,
    scrollTop,
    viewportH,
    estimate,
    gap,
  );

  const windowItems = items.slice(start, end);

  return (
    <div ref={setRoot} className={className}>
      <div className="vlist-track" style={{ height: totalH }}>
        {windowItems.map((item, i) => {
          const index = start + i;
          const key = keys[index];
          return (
            <div
              key={key}
              ref={setNode(key)}
              className="vlist-item"
              style={{ transform: `translateY(${tops[index]}px)` }}
            >
              {renderItem(item)}
            </div>
          );
        })}
      </div>
    </div>
  );
}
