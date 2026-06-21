import {
  type ReactNode,
  type RefObject,
  useCallback,
  useLayoutEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
} from "react";
import type {
  BisectResult,
  Conflict,
  Datapack,
  ExportResult,
  ModEnvironment,
  RegistryIndex,
  ResolutionPlan,
  ResourcePack,
  RunVerdict,
  ScanResult,
  Severity,
  ShaderPack,
} from "./lib/api";
import { resolveExport, resolvePreview } from "./lib/api";
import {
  CONFLICT_LABEL,
  CONSEQUENCE_HINT,
  CONSEQUENCE_LABEL,
  CONSEQUENCE_ORDER,
  conflictByMod,
  conflictConsequence,
  conflictItems,
  conflictJars,
  conflictKey,
  conflictSharedMethods,
  conflictSubject,
  countBySeverity,
  dependencyRelation,
  groupRecipeCollisions,
  isRecipeCollision,
  isRuntimeConfirmed,
  resolutionNote,
  SEVERITY_ORDER,
} from "./lib/conflicts";

interface TestProps {
  onTest: () => void;
  testing: boolean;
}

function TestButton({ onTest, testing, disabled }: TestProps & { disabled?: boolean }) {
  return (
    <button className="btn-primary" type="button" onClick={onTest} disabled={testing || disabled}>
      {testing ? "booting…" : "Test this set (headless boot)"}
    </button>
  );
}

export function Overview({
  result,
  onNavigate,
}: {
  result: ScanResult;
  onNavigate: (tab: "conflicts" | "runtime") => void;
}) {
  const sev = countBySeverity(result.conflicts);
  // The mods list lives in this same view (below the stats); the mods/errors
  // stats jump back to its top, the others switch to their dedicated tab.
  const modsScrollRef = useRef<HTMLDivElement>(null);
  const scrollModsTop = () => modsScrollRef.current?.scrollTo({ top: 0, behavior: "smooth" });

  return (
    <div className="view view-mods">
      <div className="stats">
        <button type="button" className="stat" onClick={scrollModsTop}>
          <span className="stat-n">{result.counts.mods}</span>
          <span className="stat-l">mods</span>
        </button>
        <button type="button" className="stat" onClick={() => onNavigate("runtime")}>
          <span className="stat-n">{result.counts.untestable}</span>
          <span className="stat-l">not testable in server mode</span>
        </button>
        <button type="button" className="stat" onClick={() => onNavigate("conflicts")}>
          <span className="stat-n">{result.counts.conflicts}</span>
          <span className="stat-l">
            conflicts · {sev.error}E / {sev.warning}W / {sev.info}I
          </span>
        </button>
        <button type="button" className="stat" onClick={scrollModsTop}>
          <span className="stat-n">{result.counts.errors}</span>
          <span className="stat-l">unreadable jars</span>
        </button>
      </div>

      <ModsSection result={result} scrollRef={modsScrollRef} />
    </div>
  );
}

function Chevron({ className }: { className?: string }) {
  return (
    <svg
      className={className ? `chevron ${className}` : "chevron"}
      width="16"
      height="16"
      viewBox="0 0 12 12"
      aria-hidden="true"
    >
      <path d="M2.5 4.5 6 8 9.5 4.5" fill="none" stroke="currentColor" strokeWidth="2" />
    </svg>
  );
}

// The headline of a row: the *subject* of the conflict, type-specific so each
// row reads as a thing rather than a generic "subject" cell. Dependency reads
// as a relation (mod → missing) instead of the bare "missing X" phrase.
function ConflictHeadline({ c }: { c: Conflict }) {
  if (c.type === "dependency") {
    const { mod, missing } = dependencyRelation(c);
    return (
      <span className="conflict-subject">
        {mod}
        <span className="dep-arrow">needs</span>
        <span className="dep-missing">{missing}</span>
      </span>
    );
  }
  return <span className="conflict-subject">{conflictSubject(c)}</span>;
}

// Secondary line: the members involved plus a type-specific summary of the
// hidden `detail` payload (jars to delete, item count, shared methods).
function conflictContext(c: Conflict): ReactNode {
  switch (c.type) {
    case "duplicate_jar": {
      const jars = conflictJars(c);
      return (
        <div className="conflict-context">
          <span className="ctx-label">jars</span>
          {jars.join("  ·  ")}
        </div>
      );
    }
    case "dependency":
      return null;
    case "recipe_collision":
      return <div className="conflict-context">{c.members.join(", ")}</div>;
    case "tag_overlap": {
      const n = conflictItems(c).length;
      return (
        <div className="conflict-context">
          {c.members.join(", ")}
          <span className="ctx-meta">
            {" · "}
            {n} item{n > 1 ? "s" : ""}
          </span>
        </div>
      );
    }
    case "mixin_overlap": {
      const shared = conflictSharedMethods(c);
      return (
        <div className="conflict-context">
          {c.members.join(", ")}
          {shared.length > 0 && (
            <span className="ctx-meta">
              {" · shared: "}
              {shared.join(", ")}
            </span>
          )}
        </div>
      );
    }
  }
}

// Expandable heavy detail — only tag_overlap (per-mod item lists) or a filled
// resolution carries enough to justify the disclosure; everything else fits in
// the two visible lines. Returns null when there is nothing extra to show.
function conflictDetail(c: Conflict): ReactNode {
  const note = resolutionNote(c);
  const byMod = c.type === "tag_overlap" ? Object.entries(conflictByMod(c)) : [];
  if (byMod.length === 0 && !note) return null;
  return (
    <>
      {byMod.length > 0 && (
        <dl className="bymod">
          {byMod.map(([mod, items]) => (
            <div className="bymod-row" key={mod}>
              <dt>{mod}</dt>
              <dd>{items.join(", ")}</dd>
            </div>
          ))}
        </dl>
      )}
      {note && (
        <p className="resolution-note">
          <span className="ctx-label">fix</span>
          {note}
        </p>
      )}
    </>
  );
}

function ConflictRow({ c, mixinExports }: { c: Conflict; mixinExports: Set<string> | null }) {
  const confirmed = isRuntimeConfirmed(c, mixinExports);
  const detail = conflictDetail(c);
  const head = (
    <>
      <div className="conflict-head">
        <span className="conflict-type">{CONFLICT_LABEL[c.type]}</span>
        <ConflictHeadline c={c} />
        {confirmed && <span className="tag-confirmed">confirmed at runtime</span>}
        {detail && <Chevron className="row-chevron" />}
      </div>
      {conflictContext(c)}
    </>
  );
  return detail ? (
    <details className="conflict-row">
      <summary className="conflict-summary">{head}</summary>
      <div className="conflict-detail">{detail}</div>
    </details>
  ) : (
    <div className="conflict-row">{head}</div>
  );
}

export function ConflictsView({
  conflicts: allConflicts,
  verdict,
}: {
  conflicts: Conflict[];
  verdict: RunVerdict | null;
}) {
  // Recipe collisions live in their own Recipes tab (RecipesView); keep them out
  // of this view so the two never overlap.
  const conflicts = useMemo(
    () => allConflicts.filter((c) => !isRecipeCollision(c)),
    [allConflicts],
  );
  const counts = countBySeverity(conflicts);
  // Default hides the many info-level mixin candidates; errors/warnings first.
  const [visible, setVisible] = useState<Set<Severity>>(new Set(["error", "warning"]));

  const toggle = (s: Severity) =>
    setVisible((prev) => {
      const next = new Set(prev);
      if (next.has(s)) {
        next.delete(s);
      } else {
        next.add(s);
      }
      return next;
    });

  const rows = conflicts.filter((c) => visible.has(c.severity));
  const mixinExports = useMemo(() => (verdict ? new Set(verdict.mixinExports) : null), [verdict]);

  // Group by consequence (§9), not by the abstract severity word. Detectors
  // already emit error→warning→info order, so each bucket stays sorted.
  const groups = CONSEQUENCE_ORDER.map((cons) => ({
    cons,
    rows: rows.filter((c) => conflictConsequence(c) === cons),
  })).filter((g) => g.rows.length > 0);

  return (
    <div className="view">
      <div className="filters">
        {SEVERITY_ORDER.map((s) => (
          <button
            key={s}
            type="button"
            className={visible.has(s) ? `chip chip-on sev-${s}` : "chip"}
            onClick={() => toggle(s)}
          >
            {s} ({counts[s]})
          </button>
        ))}
      </div>

      {rows.length === 0 ? (
        <p className="note">No conflicts at the selected severities.</p>
      ) : (
        <div className="conflict-groups">
          {groups.map((g) => (
            // Benign noise starts collapsed; blocking/override stay open.
            <details key={g.cons} className="conflict-group" open={g.cons !== "benign"}>
              <summary className="group-head">
                <Chevron />
                <span className="group-name">{CONSEQUENCE_LABEL[g.cons]}</span>
                <span className="group-count">· {g.rows.length}</span>
                <span className="group-hint">{CONSEQUENCE_HINT[g.cons]}</span>
              </summary>
              <div className="conflict-list">
                {g.rows.map((c) => (
                  <ConflictRow key={conflictKey(c)} c={c} mixinExports={mixinExports} />
                ))}
              </div>
            </details>
          ))}
        </div>
      )}
    </div>
  );
}

// Recipe collisions get their own tab: same recipe id written by ≥2 mods, so the
// loader keeps one and silently drops the rest (detectors.py). Aggregated by the
// colliding mod set — the unit users act on — with the recipe ids behind expand.
export function RecipesView({ conflicts }: { conflicts: Conflict[] }) {
  const groups = useMemo(() => groupRecipeCollisions(conflicts), [conflicts]);
  const total = groups.reduce((n, g) => n + g.recipes.length, 0);

  if (groups.length === 0) {
    return (
      <div className="view">
        <p className="note">No recipe collisions — no two mods write the same recipe id.</p>
      </div>
    );
  }

  return (
    <div className="view">
      <p className="recipes-intro">
        {total} recipe{total > 1 ? "s" : ""} written by more than one mod — the loader keeps one and
        silently drops the rest.
      </p>
      <div className="conflict-groups">
        {groups.map((g) => (
          // A lone pair starts open; otherwise scan the pairs first, expand on demand.
          <details key={g.key} className="conflict-group" open={groups.length === 1}>
            <summary className="group-head">
              <Chevron />
              <span className="group-name recipe-pair">{g.members.join(" ↔ ")}</span>
              <span className="group-count">· {g.recipes.length}</span>
            </summary>
            <ul className="recipe-list">
              {g.recipes.map((r) => (
                <li className="recipe-id" key={r}>
                  {r}
                </li>
              ))}
            </ul>
          </details>
        ))}
      </div>
    </div>
  );
}

// `depends` values are a single version constraint or a list of them; flatten
// to one readable string. "*" (any version) is dropped to just the dep name.
function formatConstraint(v: string | string[]): string {
  const parts = (Array.isArray(v) ? v : [v]).filter((s) => s && s !== "*");
  return parts.join(", ");
}

function ModCard({ mod }: { mod: ScanResult["mods"][number] }) {
  const depends = Object.entries(mod.depends);
  return (
    <article className="mod-card">
      <header className="mod-card-head">
        <div className="mod-card-id">
          <h3 className="mod-name">
            {mod.homepage ? (
              <a href={mod.homepage} target="_blank" rel="noreferrer">
                {mod.name ?? mod.id}
              </a>
            ) : (
              (mod.name ?? mod.id)
            )}
          </h3>
          {mod.name && <span className="mod-slug">{mod.id}</span>}
          {mod.updateAvailable && (
            <span className="mod-update">
              update{mod.latestVersion ? ` → ${mod.latestVersion}` : ""}
            </span>
          )}
        </div>
        <div className="mod-card-tags">
          {mod.provider && (
            <span className={`mod-provider provider-${mod.provider}`}>{mod.provider}</span>
          )}
          {mod.loader !== "unknown" && (
            <span className={`mod-loader loader-${mod.loader}`}>{mod.loader}</span>
          )}
          <span className={`mod-env env-${mod.environment === "*" ? "any" : mod.environment}`}>
            {mod.environment === "*" ? "client+server" : mod.environment}
          </span>
        </div>
      </header>

      <dl className="mod-meta">
        <div className="mod-field">
          <dt>version</dt>
          <dd>{mod.version ?? "—"}</dd>
        </div>
        <div className="mod-field">
          <dt>minecraft</dt>
          <dd>{mod.mcVersion ?? "—"}</dd>
        </div>
        <div className="mod-field mod-field-wide">
          <dt>jar</dt>
          <dd className="mod-jar">{mod.jar}</dd>
        </div>
      </dl>

      {depends.length > 0 && (
        <div className="mod-rel">
          <span className="mod-rel-label">depends</span>
          <ul className="mod-tags">
            {depends.map(([dep, constraint]) => {
              const c = formatConstraint(constraint);
              return (
                <li className="mod-tag" key={dep}>
                  {dep}
                  {c && <span className="mod-tag-v">{c}</span>}
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {mod.provides.length > 0 && (
        <div className="mod-rel">
          <span className="mod-rel-label">provides</span>
          <ul className="mod-tags">
            {mod.provides.map((p) => (
              <li className="mod-tag" key={p}>
                {p}
              </li>
            ))}
          </ul>
        </div>
      )}
    </article>
  );
}

// Rough first-paint height of a card (px); real heights are measured on mount
// and replace this. Only off-screen estimates use it, so being a little off is
// harmless — it just nudges the initial scrollbar length.
const CARD_ESTIMATE = 120;
const CARD_GAP = 16; // matches --space-md, the old flex gap between cards
const OVERSCAN = 4; // cards rendered just outside the viewport, each side

// Windowed mod list: only the cards intersecting the viewport (plus a small
// overscan) live in the DOM. Heights are variable (depends/provides differ per
// mod), so each rendered card is measured and its height cached by jar; offsets
// are recomputed from the cache. Keeps the DOM tiny for large modpacks.
function VirtualModList({
  mods,
  scrollRef,
}: {
  mods: ScanResult["mods"];
  scrollRef: RefObject<HTMLDivElement | null>;
}) {
  // Internal ref drives the virtualization (scroll/measure); scrollRef mirrors
  // the same element so the parent (Overview stats) can scroll the list to top.
  const listRef = useRef<HTMLDivElement>(null);
  const heights = useRef<Map<string, number>>(new Map());
  const nodes = useRef<Map<string, HTMLDivElement>>(new Map());
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportH, setViewportH] = useState(0);
  const [, bump] = useReducer((n: number) => n + 1, 0);

  const setNode = useCallback(
    (jar: string) => (el: HTMLDivElement | null) => {
      if (el) nodes.current.set(jar, el);
      else nodes.current.delete(jar);
    },
    [],
  );

  // Track the scroll position and the visible height of the scroll container.
  useLayoutEffect(() => {
    const el = listRef.current;
    if (!el) return;
    const onScroll = () => setScrollTop(el.scrollTop);
    // A width change can reflow cards (tags wrap), so drop measurements and let
    // the layout effect below re-measure at the new width.
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

  // After each render, measure the cards currently in the DOM. If a real height
  // differs from the cache, store it and re-render so offsets settle (converges
  // in a pass or two; offsetHeight is integral, so it stops changing).
  useLayoutEffect(() => {
    let changed = false;
    for (const [jar, el] of nodes.current) {
      const h = el.offsetHeight;
      if (h > 0 && heights.current.get(jar) !== h) {
        heights.current.set(jar, h);
        changed = true;
      }
    }
    if (changed) bump();
  });

  // Cumulative top offset of every card from the measured/estimated heights.
  // Computed every render (not memoized): heights is a mutable ref, so a measure
  // pass that calls bump() must recompute offsets with the same `mods`.
  const tops = new Array<number>(mods.length);
  let acc = 0;
  for (let i = 0; i < mods.length; i++) {
    tops[i] = acc;
    acc += (heights.current.get(mods[i].jar) ?? CARD_ESTIMATE) + CARD_GAP;
  }
  const totalH = mods.length > 0 ? acc - CARD_GAP : 0;

  const top = scrollTop;
  const bottom = scrollTop + viewportH;
  let start = 0;
  while (start < mods.length) {
    const h = heights.current.get(mods[start].jar) ?? CARD_ESTIMATE;
    if (tops[start] + h >= top) break;
    start++;
  }
  let end = start;
  while (end < mods.length && tops[end] <= bottom) end++;
  start = Math.max(0, start - OVERSCAN);
  end = Math.min(mods.length, end + OVERSCAN);

  const window = mods.slice(start, end);

  return (
    <div
      ref={(el) => {
        listRef.current = el;
        scrollRef.current = el;
      }}
      className="mods-list"
    >
      <div className="mods-virt" style={{ height: totalH }}>
        {window.map((mod, i) => {
          const index = start + i;
          return (
            <div
              key={mod.jar}
              ref={setNode(mod.jar)}
              className="mods-virt-item"
              style={{ transform: `translateY(${tops[index]}px)` }}
            >
              <ModCard mod={mod} />
            </div>
          );
        })}
      </div>
    </div>
  );
}

const ENV_FILTERS: { id: ModEnvironment; label: string }[] = [
  { id: "server", label: "server" },
  { id: "client", label: "client" },
  { id: "*", label: "client+server" },
];

function ModsSection({
  result,
  scrollRef,
}: {
  result: ScanResult;
  scrollRef: RefObject<HTMLDivElement | null>;
}) {
  const [query, setQuery] = useState("");
  // Empty set = no env filter (show all); otherwise show only checked envs.
  const [envs, setEnvs] = useState<Set<ModEnvironment>>(new Set());

  const toggleEnv = (e: ModEnvironment) =>
    setEnvs((prev) => {
      const next = new Set(prev);
      if (next.has(e)) {
        next.delete(e);
      } else {
        next.add(e);
      }
      return next;
    });

  const envCounts = useMemo(() => {
    const c = new Map<ModEnvironment, number>();
    for (const m of result.mods) c.set(m.environment, (c.get(m.environment) ?? 0) + 1);
    return c;
  }, [result.mods]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return result.mods.filter((mod) => {
      if (envs.size > 0 && !envs.has(mod.environment)) return false;
      if (!q) return true;
      const haystack = [
        mod.id,
        mod.name ?? "",
        mod.version ?? "",
        mod.jar,
        mod.loader,
        ...mod.provides,
        ...Object.keys(mod.depends),
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(q);
    });
  }, [result.mods, query, envs]);

  return (
    <>
      <div className="mods-controls">
        <input
          className="path-input"
          type="search"
          placeholder="Search by name, id, jar, dependency…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          spellCheck={false}
        />
        <div className="filters">
          {ENV_FILTERS.filter((f) => envCounts.has(f.id)).map((f) => (
            <button
              key={f.id}
              type="button"
              className={envs.has(f.id) ? "chip chip-on" : "chip"}
              onClick={() => toggleEnv(f.id)}
            >
              {f.label} ({envCounts.get(f.id)})
            </button>
          ))}
        </div>
      </div>

      <p className="note mods-count">
        {filtered.length} of {result.mods.length} mods
      </p>

      {result.errors.length > 0 && (
        <ul className="errors">
          {result.errors.map((err) => (
            <li key={err.jar}>
              {err.jar}: {err.reason}
            </li>
          ))}
        </ul>
      )}

      {filtered.length === 0 ? (
        <p className="note">No mods match the current filters.</p>
      ) : (
        <VirtualModList mods={filtered} scrollRef={scrollRef} />
      )}
    </>
  );
}

function bisectStatusClass(status: BisectResult["status"]): string {
  if (status === "isolated") return "run-crash";
  if (status === "no_conflict") return "run-ok";
  return "run-error";
}

export function RuntimeView({
  verdict,
  onTest,
  testing,
  onBisect,
  bisecting,
  bisectResult,
  runnerSupported,
  block,
}: {
  verdict: RunVerdict | null;
  onBisect: () => void;
  bisecting: boolean;
  bisectResult: BisectResult | null;
  runnerSupported: boolean;
  block: string | null;
} & TestProps) {
  return (
    <div className="view">
      {!runnerSupported && (
        <p className="note">
          Runtime testing isn't available yet for {block ?? "this version"} — static analysis only.
          The headless runner needs server artifacts that aren't published for this block.
        </p>
      )}
      <section className="runner">
        <TestButton onTest={onTest} testing={testing} disabled={!runnerSupported} />
        {testing && <span className="note"> a real boot takes minutes; needs Docker running</span>}
      </section>

      {verdict ? (
        <div className="panel">
          <p>
            <span className={`run-${verdict.status}`}>{verdict.status.toUpperCase()}</span>
            {" · "}
            {(verdict.durationMs / 1000).toFixed(1)}s
            {verdict.mixinExports.length > 0 &&
              ` · ${verdict.mixinExports.length} mixin-transformed classes (ground truth)`}
          </p>
          {verdict.cause && (
            <>
              <p className="note">
                {verdict.cause.category}: {verdict.cause.summary}
                {verdict.cause.mods.length > 0 && ` — ${verdict.cause.mods.join(", ")}`}
              </p>
              {verdict.cause.excerpt && <pre className="log">{verdict.cause.excerpt}</pre>}
            </>
          )}
          {verdict.logTail && verdict.status !== "error" && (
            <details>
              <summary>log tail</summary>
              <pre className="log">{verdict.logTail}</pre>
            </details>
          )}
        </div>
      ) : (
        <p className="note">No boot yet. Run a test to get a runtime verdict.</p>
      )}

      <section className="runner">
        <button
          className="btn-primary"
          type="button"
          onClick={onBisect}
          disabled={bisecting || !runnerSupported}
        >
          {bisecting ? "bisecting…" : "Find guilty set (bisection)"}
        </button>
        {bisecting && (
          <span className="note"> each step is a real boot (~log2 N); takes minutes</span>
        )}
      </section>

      {bisectResult && (
        <div className="panel">
          <p>
            bisection{" "}
            <span className={bisectStatusClass(bisectResult.status)}>
              {bisectResult.status.toUpperCase()}
            </span>
            {" · "}
            {bisectResult.boots} boots · {(bisectResult.durationMs / 1000).toFixed(1)}s
          </p>
          {bisectResult.members.length > 0 && (
            <p className="members">guilty set: {bisectResult.members.join(", ")}</p>
          )}
          {bisectResult.cause && (
            <p className="note">
              {bisectResult.cause.category}: {bisectResult.cause.summary}
            </p>
          )}
          {bisectResult.note && <p className="note">{bisectResult.note}</p>}
        </div>
      )}
    </div>
  );
}

// Override groups (resource-pack assets / datapack data shared by ≥2 packs).
// Same shape as recipe collisions: a colliding set, its paths behind expand.
function OverrideList({ conflicts, unit }: { conflicts: Conflict[]; unit: string }) {
  if (conflicts.length === 0) return null;
  return (
    <div className="conflict-groups">
      {conflicts.map((c) => {
        const paths = (c.detail.paths as string[] | undefined) ?? [];
        const count = (c.detail.count as number | undefined) ?? paths.length;
        return (
          <details className="conflict-group" key={c.members.join("|")}>
            <summary className="group-head">
              <Chevron />
              <span className="group-name recipe-pair">{c.members.join("  ↔  ")}</span>
              <span className="group-count">
                · {count} {unit}
              </span>
            </summary>
            <ul className="recipe-list">
              {paths.map((p) => (
                <li className="recipe-id" key={p}>
                  {p}
                </li>
              ))}
              {count > paths.length && <li className="note">…and {count - paths.length} more</li>}
            </ul>
          </details>
        );
      })}
    </div>
  );
}

export function ResourcePacksView({
  packs,
  conflicts,
}: {
  packs: ResourcePack[];
  conflicts: Conflict[];
}) {
  return (
    <div className="view">
      {conflicts.length > 0 && (
        <p className="note">
          {conflicts.length} asset override{conflicts.length > 1 ? "s" : ""} — when packs share a
          file, load order decides which one wins.
        </p>
      )}
      <OverrideList conflicts={conflicts} unit="assets" />
      <div className="pack-list">
        {packs.map((p) => (
          <article className="pack-card" key={p.name}>
            <header className="pack-card-head">
              <h3 className="pack-name">{p.name}</h3>
              <span className="pack-source">{p.source}</span>
            </header>
            <p className="note">
              {p.assetCount} assets
              {p.packFormat != null && ` · format ${p.packFormat}`}
            </p>
            {p.description && <p className="pack-desc">{p.description}</p>}
          </article>
        ))}
      </div>
    </div>
  );
}

export function DatapacksView({ packs, conflicts }: { packs: Datapack[]; conflicts: Conflict[] }) {
  return (
    <div className="view">
      {conflicts.length > 0 && (
        <p className="note">
          {conflicts.length} datapack override{conflicts.length > 1 ? "s" : ""} — two datapacks ship
          the same recipe/loot/tag; load order decides.
        </p>
      )}
      <OverrideList conflicts={conflicts} unit="files" />
      <div className="pack-list">
        {packs.map((p) => (
          <article className="pack-card" key={`${p.location}/${p.name}`}>
            <header className="pack-card-head">
              <h3 className="pack-name">{p.name}</h3>
              <span className="pack-source">{p.location}</span>
            </header>
            <p className="note">
              {p.dataCount} files
              {p.packFormat != null && ` · format ${p.packFormat}`}
            </p>
            {p.description && <p className="pack-desc">{p.description}</p>}
          </article>
        ))}
      </div>
    </div>
  );
}

// Cap on rendered rows: a big pack has thousands of items; search narrows, and
// we render only the first slice to keep the DOM light (count shows the rest).
const ITEM_CAP = 500;

export function ItemsView({ index }: { index: RegistryIndex }) {
  const [query, setQuery] = useState("");
  const [kinds, setKinds] = useState<Set<"item" | "block">>(new Set());

  const toggleKind = (k: "item" | "block") =>
    setKinds((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return index.items.filter((it) => {
      if (kinds.size > 0 && !kinds.has(it.kind)) return false;
      if (!q) return true;
      return `${it.id} ${it.displayName ?? ""} ${it.mod}`.toLowerCase().includes(q);
    });
  }, [index.items, query, kinds]);
  const shown = filtered.slice(0, ITEM_CAP);

  return (
    <div className="view">
      <p className="note">
        {index.total} items & blocks ({index.itemCount} items · {index.blockCount} blocks).
        Approximate — built from lang/model assets, so code-only registrations aren't listed.
      </p>
      <div className="mods-controls">
        <input
          className="path-input"
          type="search"
          placeholder="Search items by name, id, mod…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          spellCheck={false}
        />
        <div className="filters">
          {(["item", "block"] as const).map((k) => (
            <button
              key={k}
              type="button"
              className={kinds.has(k) ? "chip chip-on" : "chip"}
              onClick={() => toggleKind(k)}
            >
              {k} ({k === "item" ? index.itemCount : index.blockCount})
            </button>
          ))}
        </div>
      </div>
      <p className="note mods-count">
        {filtered.length} of {index.total}
        {filtered.length > ITEM_CAP ? ` · showing first ${ITEM_CAP}` : ""}
      </p>
      {shown.length === 0 ? (
        <p className="note">No items match the current filters.</p>
      ) : (
        <ul className="item-list">
          {shown.map((it) => (
            <li className="item-row" key={it.id}>
              <span className={`item-kind kind-${it.kind}`}>{it.kind}</span>
              <span className="item-name">{it.displayName ?? it.id}</span>
              <span className="item-id">{it.id}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function ShadersView({ packs }: { packs: ShaderPack[] }) {
  return (
    <div className="view">
      <p className="note">
        Shader packs are opaque to static analysis — listed for inventory only.
      </p>
      <div className="pack-list">
        {packs.map((p) => (
          <article className="pack-card" key={p.name}>
            <header className="pack-card-head">
              <h3 className="pack-name">{p.name}</h3>
              <span className="pack-source">{p.source}</span>
            </header>
          </article>
        ))}
      </div>
    </div>
  );
}

export function ResolutionView({ modsPath, version }: { modsPath: string; version?: string }) {
  const [plan, setPlan] = useState<ResolutionPlan | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [outDir, setOutDir] = useState("");
  const [exporting, setExporting] = useState(false);
  const [exported, setExported] = useState<ExportResult | null>(null);

  const generate = async () => {
    setLoading(true);
    setError(null);
    setExported(null);
    try {
      setPlan(await resolvePreview(modsPath, version));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setPlan(null);
    } finally {
      setLoading(false);
    }
  };

  const doExport = async () => {
    const dir = outDir.trim();
    if (!dir) return;
    setExporting(true);
    setError(null);
    try {
      setExported(await resolveExport(modsPath, dir, version));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="view">
      <section className="runner">
        <button
          className="btn-primary"
          type="button"
          onClick={() => void generate()}
          disabled={loading}
        >
          {loading ? "generating…" : "Generate resolution"}
        </button>
      </section>

      {error && <p className="scan-error">{error}</p>}

      {plan && (
        <>
          <p className="note">{plan.summary}</p>
          {plan.files.map((file) => (
            <div className="panel" key={file.path}>
              <p className="note">{file.path}</p>
              <pre className="log">{file.content}</pre>
            </div>
          ))}

          {plan.files.length > 0 && (
            <>
              <section className="runner">
                <input
                  className="path-input"
                  type="text"
                  placeholder="output folder (e.g. your pack root)"
                  value={outDir}
                  onChange={(e) => setOutDir(e.target.value)}
                  spellCheck={false}
                />
                <button
                  className="btn-primary"
                  type="button"
                  onClick={() => void doExport()}
                  disabled={exporting || !outDir.trim()}
                >
                  {exporting ? "exporting…" : "Export files"}
                </button>
              </section>
              {exported && (
                <p className="note">
                  wrote {exported.written.length} file(s) to {exported.outDir}
                </p>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}
