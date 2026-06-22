import {
  type ReactNode,
  type RefObject,
  useCallback,
  useEffect,
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
  Loader,
  Mod,
  ModEnvironment,
  RegistryIndex,
  ResolutionFamily,
  ResolutionPlan,
  ResourcePack,
  RunCause,
  RunVerdict,
  ScanResult,
  Severity,
  ShaderPack,
} from "./lib/api";
import {
  disableMod,
  enableMod,
  installMod,
  resolveExport,
  resolvePreview,
  updateMod,
} from "./lib/api";
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
  groupMixinClusters,
  groupRecipeCollisions,
  isRecipeCollision,
  isRuntimeConfirmed,
  type MixinCluster,
  type MixinClusterMember,
  resolutionNote,
  SEVERITY_ORDER,
} from "./lib/conflicts";
import type { ResolutionSub } from "./useScanSession";

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
  updatedJars,
  onUpdated,
}: {
  result: ScanResult;
  updatedJars: Set<string>;
  onUpdated: (jar: string) => void;
}) {
  const modsScrollRef = useRef<HTMLDivElement>(null);
  return (
    <div className="view view-mods">
      <ModsSection
        result={result}
        scrollRef={modsScrollRef}
        updatedJars={updatedJars}
        onUpdated={onUpdated}
      />
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

// Recipe-collision browse, shown in the Resolution › Recipes sub-tab: same recipe
// id written by ≥2 mods, so the loader keeps one and silently drops the rest
// (detectors.py). Aggregated by the colliding mod set — the unit users act on —
// with the recipe ids behind expand.
function RecipesView({ conflicts }: { conflicts: Conflict[] }) {
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

function DownloadIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
      <path
        d="M8 1.5v7.5M4.5 6 8 9.5 11.5 6M2.5 13.5h11"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
      <path
        d="M3 8.5 6.5 12 13 4.5"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function SpinnerIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" className="spin">
      <circle
        cx="8"
        cy="8"
        r="6"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeDasharray="28"
        strokeDashoffset="10"
      />
    </svg>
  );
}

function WarnIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
      <path
        d="M8 2 14.5 13.5H1.5L8 2Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <path d="M8 6.5v3" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      <circle cx="8" cy="11.4" r="0.6" fill="currentColor" />
    </svg>
  );
}

function ErrorIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
      <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <path
        d="M5.5 5.5 10.5 10.5M10.5 5.5 5.5 10.5"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  );
}

// The update and install buttons share one lifecycle glyph: a single mapping from
// a normalized phase to its icon, so neither has to repeat the five-way switch.
type StatusPhase = "busy" | "done" | "warn" | "error" | "idle";

function StatusIcon({ phase }: { phase: StatusPhase }) {
  switch (phase) {
    case "busy":
      return <SpinnerIcon />;
    case "done":
      return <CheckIcon />;
    case "warn":
      return <WarnIcon />;
    case "error":
      return <ErrorIcon />;
    default:
      return <DownloadIcon />;
  }
}

// idle -> download; updating -> spinner; done -> check (3s) then "gone" collapses
// the width to 0 and "removed" unmounts it. warn/error end the run in place with
// an alert icon (warn = nothing installed but no failure; error = update failed).
type UpdateState = "idle" | "updating" | "done" | "gone" | "removed" | "warn" | "error";

const DONE_HOLD_MS = 3000; // how long the check stays before collapsing
const COLLAPSE_MS = 350; // matches the width transition before unmounting

// The button is only actionable from a resting state; "updating"/"done"/"gone"
// lock it. Shared by the click guard and the disabled attribute.
function updateLocked(state: UpdateState): boolean {
  return state !== "idle" && state !== "error" && state !== "warn";
}

function updatePhase(state: UpdateState): StatusPhase {
  switch (state) {
    case "updating":
      return "busy";
    case "done":
    case "gone":
      return "done";
    case "warn":
      return "warn";
    case "error":
      return "error";
    default:
      return "idle";
  }
}

function updateButtonTitle(
  state: UpdateState,
  msg: string | null,
  latestVersion: string | null,
): string {
  const arrow = latestVersion ? ` → ${latestVersion}` : "";
  switch (state) {
    case "error":
      return msg ?? "update failed";
    case "warn":
      return msg ?? "no update installed";
    case "done":
    case "gone":
      return `updated${arrow} · rescan to refresh`;
    case "updating":
      return "updating…";
    default:
      return `update${arrow}`;
  }
}

// The update lifecycle: holds the state machine, the in-place swap call, and the
// done → gone → removed timer chain (cleared on unmount). Kept out of the button
// so the component is just render.
function useUpdateButton(
  mod: ScanResult["mods"][number],
  modsPath: string,
  version: string,
  alreadyUpdated: boolean,
  onUpdated: (jar: string) => void,
) {
  // A card remounted after its jar was already updated this session (e.g. on
  // returning to the panel) starts "removed" — the button is done, render nothing.
  const [state, setState] = useState<UpdateState>(alreadyUpdated ? "removed" : "idle");
  const [msg, setMsg] = useState<string | null>(null);
  const timers = useRef<number[]>([]);

  useEffect(() => {
    const ids = timers.current;
    return () => {
      for (const id of ids) window.clearTimeout(id);
    };
  }, []);

  const onClick = async () => {
    if (updateLocked(state)) return;
    setState("updating");
    setMsg(null);
    try {
      const r = await updateMod(modsPath, mod.jar, version, mod.loader);
      if (r.status === "updated") {
        setState("done");
        // The in-place swap doesn't re-scan, so tell the list this jar is no longer
        // pending — it drops out of the "to update" count/filter immediately.
        onUpdated(mod.jar);
        // Hold the check, then collapse the width, then unmount (no leftover box).
        timers.current.push(
          window.setTimeout(() => {
            setState("gone");
            timers.current.push(window.setTimeout(() => setState("removed"), COLLAPSE_MS));
          }, DONE_HOLD_MS),
        );
      } else {
        // A hard "error" status (jar gone, download/checksum/install) is the real
        // failure; not_found / no_update are soft — nothing installed, nothing broke.
        setState(r.status === "error" ? "error" : "warn");
        setMsg(r.message ?? r.status);
      }
    } catch (e) {
      setState("error");
      setMsg(e instanceof Error ? e.message : String(e));
    }
  };

  return { state, msg, onClick };
}

// The "update available" affordance: a download-icon button that downloads the
// latest Modrinth version and swaps the jar in place, then confirms and fades out.
function UpdateButton({
  mod,
  modsPath,
  version,
  alreadyUpdated,
  onUpdated,
}: {
  mod: ScanResult["mods"][number];
  modsPath: string;
  version: string;
  alreadyUpdated: boolean;
  onUpdated: (jar: string) => void;
}) {
  const { state, msg, onClick } = useUpdateButton(
    mod,
    modsPath,
    version,
    alreadyUpdated,
    onUpdated,
  );

  if (state === "removed") return null;

  const title = updateButtonTitle(state, msg, mod.latestVersion);

  return (
    <button
      type="button"
      className={`mod-update mod-update-${state}`}
      onClick={onClick}
      disabled={updateLocked(state)}
      title={title}
      aria-label={title}
    >
      <StatusIcon phase={updatePhase(state)} />
    </button>
  );
}

type ModEntry = ScanResult["mods"][number];

// Title block: linked name when an enrichment homepage is known, plus the slug
// (id) underneath whenever a human-readable name displaced it above.
function ModCardTitle({ mod }: { mod: ModEntry }) {
  return (
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
    </div>
  );
}

// Provider / loader / environment badges; loader is hidden when unknown.
function ModCardTags({ mod }: { mod: ModEntry }) {
  return (
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
  );
}

// The depends/provides tag lists, each shown only when non-empty. depends carries
// a flattened version constraint; provides is a bare id list.
function ModRelations({ mod }: { mod: ModEntry }) {
  const depends = Object.entries(mod.depends);
  return (
    <>
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
    </>
  );
}

function ModCard({
  mod,
  modsPath,
  version,
  alreadyUpdated,
  onUpdated,
}: {
  mod: ModEntry;
  modsPath: string;
  version: string;
  alreadyUpdated: boolean;
  onUpdated: (jar: string) => void;
}) {
  return (
    <article className="mod-card">
      <header className="mod-card-head">
        <ModCardTitle mod={mod} />
        <div className="mod-card-right">
          <ModCardTags mod={mod} />
          {mod.updateAvailable && (
            <UpdateButton
              mod={mod}
              modsPath={modsPath}
              version={version}
              alreadyUpdated={alreadyUpdated}
              onUpdated={onUpdated}
            />
          )}
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
        <div className="mod-field">
          <dt>jar</dt>
          <dd className="mod-jar">{mod.jar}</dd>
        </div>
      </dl>

      <ModRelations mod={mod} />
    </article>
  );
}

// Best-effort display name for a jar that failed metadata parsing: drop the
// extension and the trailing version/loader tail (a separator before a digit),
// then normalize the separators. Falls back to the raw filename.
function recoverModName(jar: string): string {
  const base = jar
    .replace(/\.jar$/i, "")
    .replace(/[-_+ ](?:v|mc)?\d.*$/i, "")
    .replace(/[-_]+/g, " ")
    .trim();
  return base || jar;
}

// A jar that couldn't be analyzed (corrupt zip, unrecognized loader metadata…).
// It still earns a card: the recovered name as the title, the filename as the
// slug, and the parse error shown inside.
function ErrorCard({ name, jar, reason }: { name: string; jar: string; reason: string }) {
  return (
    <article className="mod-card mod-card-error">
      <header className="mod-card-head">
        <div className="mod-card-id">
          <h3 className="mod-name">{name}</h3>
          <span className="mod-slug">{jar}</span>
        </div>
        <div className="mod-card-right">
          <div className="mod-card-tags">
            <span className="mod-error-badge">unreadable</span>
          </div>
        </div>
      </header>
      <p className="mod-error-reason">{reason}</p>
    </article>
  );
}

// The mod list renders a heterogeneous stream: a parsed mod, or a jar that
// failed analysis. Both carry a `jar` — the virtualizer's key + height-cache key.
type ModListEntry =
  | { kind: "mod"; jar: string; mod: ScanResult["mods"][number] }
  | { kind: "error"; jar: string; name: string; reason: string };

// Rough first-paint height of a card (px); real heights are measured on mount
// and replace this. Only off-screen estimates use it, so being a little off is
// harmless — it just nudges the initial scrollbar length.
const CARD_ESTIMATE = 120;
const CARD_GAP = 16; // matches --space-md, the old flex gap between cards
const OVERSCAN = 4; // cards rendered just outside the viewport, each side

interface ModWindow {
  tops: number[];
  totalH: number;
  start: number;
  end: number;
}

// Pure windowing math: the cumulative top offset of every card (from the measured
// or estimated heights), the total scroll height, and the [start, end) slice of
// entries intersecting the viewport plus overscan. Recomputed every render (heights
// is a mutable ref a measure pass mutates), so it's kept pure and out of the body.
function computeWindow(
  entries: ModListEntry[],
  heights: Map<string, number>,
  scrollTop: number,
  viewportH: number,
): ModWindow {
  const tops = new Array<number>(entries.length);
  let acc = 0;
  for (let i = 0; i < entries.length; i++) {
    tops[i] = acc;
    acc += (heights.get(entries[i].jar) ?? CARD_ESTIMATE) + CARD_GAP;
  }
  const totalH = entries.length > 0 ? acc - CARD_GAP : 0;

  const bottom = scrollTop + viewportH;
  let start = 0;
  while (start < entries.length) {
    const h = heights.get(entries[start].jar) ?? CARD_ESTIMATE;
    if (tops[start] + h >= scrollTop) break;
    start++;
  }
  let end = start;
  while (end < entries.length && tops[end] <= bottom) end++;
  start = Math.max(0, start - OVERSCAN);
  end = Math.min(entries.length, end + OVERSCAN);

  return { tops, totalH, start, end };
}

// Windowed mod list: only the cards intersecting the viewport (plus a small
// overscan) live in the DOM. Heights are variable (depends/provides differ per
// mod), so each rendered card is measured and its height cached by jar; offsets
// are recomputed from the cache. Keeps the DOM tiny for large modpacks.
function VirtualModList({
  entries,
  scrollRef,
  modsPath,
  version,
  updatedJars,
  onUpdated,
}: {
  entries: ModListEntry[];
  scrollRef: RefObject<HTMLDivElement | null>;
  modsPath: string;
  version: string;
  updatedJars: Set<string>;
  onUpdated: (jar: string) => void;
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

  // Recomputed every render (not memoized): heights is a mutable ref, so a measure
  // pass that calls bump() must recompute offsets with the same `entries`.
  const { tops, totalH, start, end } = computeWindow(
    entries,
    heights.current,
    scrollTop,
    viewportH,
  );

  const window = entries.slice(start, end);

  return (
    <div
      ref={(el) => {
        listRef.current = el;
        scrollRef.current = el;
      }}
      className="mods-list"
    >
      <div className="mods-virt" style={{ height: totalH }}>
        {window.map((entry, i) => {
          const index = start + i;
          return (
            <div
              key={entry.jar}
              ref={setNode(entry.jar)}
              className="mods-virt-item"
              style={{ transform: `translateY(${tops[index]}px)` }}
            >
              {entry.kind === "mod" ? (
                <ModCard
                  mod={entry.mod}
                  modsPath={modsPath}
                  version={version}
                  alreadyUpdated={updatedJars.has(entry.jar)}
                  onUpdated={onUpdated}
                />
              ) : (
                <ErrorCard name={entry.name} jar={entry.jar} reason={entry.reason} />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

const ENV_FILTERS: { id: ModEnvironment; label: string }[] = [
  { id: "server", label: "Server" },
  { id: "client", label: "Client" },
  { id: "*", label: "Client + Server" },
];

// The active mod-list filters, derived once per query/toggle change and shared by
// the per-entry predicates below.
interface ModFilters {
  q: string;
  envActive: boolean;
  envs: Set<ModEnvironment>;
  onlyUpdate: boolean;
  onlyErrors: boolean;
  updatedJars: Set<string>;
}

// Errors carry no env/update facet, so an env or update-only filter scopes the
// list to mods and drops them — unless the errors chip is also on.
function matchesErrorEntry(
  entry: Extract<ModListEntry, { kind: "error" }>,
  { q, envActive, onlyUpdate, onlyErrors }: ModFilters,
): boolean {
  if (envActive || (onlyUpdate && !onlyErrors)) return false;
  if (q) return `${entry.name} ${entry.jar} ${entry.reason}`.toLowerCase().includes(q);
  return true;
}

// Free-text search over a mod's identity, version, jar, and relations.
function modMatchesQuery(mod: ModEntry, q: string): boolean {
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
}

function matchesModEntry(mod: ModEntry, filters: ModFilters): boolean {
  const { q, envActive, envs, onlyUpdate, onlyErrors, updatedJars } = filters;
  if (onlyErrors && !onlyUpdate) return false;
  if (envActive && !envs.has(mod.environment)) return false;
  if (onlyUpdate && (!mod.updateAvailable || updatedJars.has(mod.jar))) return false;
  return !q || modMatchesQuery(mod, q);
}

function matchesFilters(entry: ModListEntry, filters: ModFilters): boolean {
  return entry.kind === "error"
    ? matchesErrorEntry(entry, filters)
    : matchesModEntry(entry.mod, filters);
}

function ModsSection({
  result,
  scrollRef,
  updatedJars,
  onUpdated,
}: {
  result: ScanResult;
  scrollRef: RefObject<HTMLDivElement | null>;
  updatedJars: Set<string>;
  onUpdated: (jar: string) => void;
}) {
  // The mods folder + resolved version, threaded to each card's update button.
  const modsPath = result.modsPath;
  const version = result.profile;
  const [query, setQuery] = useState("");
  // Empty set = no env filter (show all); otherwise show only checked envs.
  const [envs, setEnvs] = useState<Set<ModEnvironment>>(new Set());
  // Quick filters, off by default: isolate mods with an update / unreadable jars.
  const [onlyUpdate, setOnlyUpdate] = useState(false);
  const [onlyErrors, setOnlyErrors] = useState(false);
  // updatedJars (jars updated in place, no re-scan yet) is owned by App so this
  // count survives the panel unmounting; the backend's stale updateAvailable flag
  // for those jars is masked here.

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

  const updatableCount = useMemo(
    () => result.mods.filter((m) => m.updateAvailable && !updatedJars.has(m.jar)).length,
    [result.mods, updatedJars],
  );

  // Mods first, then the unreadable jars, as one card stream. Errors get a name
  // recovered from the filename — the metadata that would carry the real one is
  // exactly what failed to parse.
  const entries = useMemo<ModListEntry[]>(() => {
    const mods = result.mods.map((mod): ModListEntry => ({ kind: "mod", jar: mod.jar, mod }));
    const errors = result.errors.map(
      (err): ModListEntry => ({
        kind: "error",
        jar: err.jar,
        name: recoverModName(err.jar),
        reason: err.reason,
      }),
    );
    return [...mods, ...errors];
  }, [result.mods, result.errors]);

  const filtered = useMemo(() => {
    const filters: ModFilters = {
      q: query.trim().toLowerCase(),
      envActive: envs.size > 0,
      envs,
      onlyUpdate,
      onlyErrors,
      updatedJars,
    };
    return entries.filter((entry) => matchesFilters(entry, filters));
  }, [entries, query, envs, onlyUpdate, onlyErrors, updatedJars]);

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
          {updatableCount > 0 && (
            <button
              type="button"
              className={onlyUpdate ? "chip chip-on chip-update" : "chip chip-update"}
              onClick={() => setOnlyUpdate((v) => !v)}
            >
              To update ({updatableCount})
            </button>
          )}
          {result.errors.length > 0 && (
            <button
              type="button"
              className={onlyErrors ? "chip chip-on chip-error" : "chip chip-error"}
              onClick={() => setOnlyErrors((v) => !v)}
            >
              errors ({result.errors.length})
            </button>
          )}
        </div>
      </div>

      <p className="note mods-count">
        {filtered.length} of {entries.length}
      </p>

      {filtered.length === 0 ? (
        <p className="note">No mods match the current filters.</p>
      ) : (
        <VirtualModList
          entries={filtered}
          scrollRef={scrollRef}
          modsPath={modsPath}
          version={version}
          updatedJars={updatedJars}
          onUpdated={onUpdated}
        />
      )}
    </>
  );
}

function bisectStatusClass(status: BisectResult["status"]): string {
  if (status === "isolated") return "run-crash";
  if (status === "no_conflict") return "run-ok";
  return "run-error";
}

// Per-mod install lifecycle. idle -> installing -> installed (check) / warn (no
// Modrinth match) / error (download failed). "installing"/"installed" are locked;
// warn/error can be retried.
type InstallState = "idle" | "installing" | "installed" | "warn" | "error";

// A "settled" mod has been attempted and won't change without a retry — the
// trigger for the panel's auto re-test once every dep has been dealt with.
const SETTLED: ReadonlySet<InstallState> = new Set(["installed", "warn", "error"]);

// Install states map onto the shared button visuals: installing→busy/updating,
// installed→done, warn/error as-is.
function installPhase(state: InstallState): StatusPhase {
  switch (state) {
    case "installing":
      return "busy";
    case "installed":
      return "done";
    case "warn":
      return "warn";
    case "error":
      return "error";
    default:
      return "idle";
  }
}

function installRowTitle(state: InstallState, msg: string | null, modId: string): string {
  switch (state) {
    case "installed":
      return `installed ${msg}`;
    case "warn":
    case "error":
      return msg ?? "install failed";
    case "installing":
      return "installing…";
    default:
      return `install ${modId} from Modrinth`;
  }
}

// One missing dependency: its id and a download-icon button driven by the panel's
// state (so "Install all" and per-row clicks share one source of truth).
function InstallRow({
  modId,
  state,
  msg,
  disabled,
  onInstall,
}: {
  modId: string;
  state: InstallState;
  msg: string | null;
  disabled: boolean;
  onInstall: (modId: string) => void;
}) {
  // Reuse the mod-update button class names; only the icon set differs by phase.
  const btnState = state === "installing" ? "updating" : state === "installed" ? "done" : state;
  const title = installRowTitle(state, msg, modId);

  return (
    <li className="missing-row">
      <span className="missing-id">{modId}</span>
      <button
        type="button"
        className={`mod-update mod-update-${btnState}`}
        onClick={() => onInstall(modId)}
        disabled={disabled || state === "installing" || state === "installed"}
        title={title}
        aria-label={title}
      >
        <StatusIcon phase={installPhase(state)} />
      </button>
      {msg && <span className="note missing-msg">{msg}</span>}
    </li>
  );
}

// Shown under a runtime verdict whose cause is a missing dependency: install each
// flagged mod from Modrinth (one by one or all at once). Once every dep has been
// attempted and at least one was installed, it auto re-tests to confirm the fix.
function MissingDepsPanel({
  mods,
  modsPath,
  version,
  loader,
  onRetest,
  testing,
}: {
  mods: string[];
  modsPath: string;
  version: string;
  loader?: Loader;
  onRetest: () => void;
  testing: boolean;
}) {
  const [states, setStates] = useState<Record<string, InstallState>>({});
  const [msgs, setMsgs] = useState<Record<string, string | null>>({});
  const [installingAll, setInstallingAll] = useState(false);
  // One re-test per panel: it remounts on each new verdict (keyed in TestView).
  const retested = useRef(false);

  // Install one mod, recording its outcome. Returns whether the jar landed.
  const install = async (id: string): Promise<boolean> => {
    setStates((p) => ({ ...p, [id]: "installing" }));
    setMsgs((p) => ({ ...p, [id]: null }));
    try {
      const r = await installMod(modsPath, id, version, loader);
      const next: InstallState =
        r.status === "installed" ? "installed" : r.status === "error" ? "error" : "warn";
      const note =
        r.status === "installed"
          ? r.version
            ? `${r.jar} (${r.version})`
            : (r.jar ?? "installed")
          : (r.message ?? r.status);
      setStates((p) => ({ ...p, [id]: next }));
      setMsgs((p) => ({ ...p, [id]: note }));
      return r.status === "installed";
    } catch (e) {
      setStates((p) => ({ ...p, [id]: "error" }));
      setMsgs((p) => ({
        ...p,
        [id]: e instanceof Error ? e.message : String(e),
      }));
      return false;
    }
  };

  // Install every dep that isn't already installed or in flight, sequentially
  // (one shared mods folder; serial keeps writes and rate limits sane).
  const installAll = async () => {
    setInstallingAll(true);
    try {
      for (const id of mods) {
        const s = states[id] ?? "idle";
        if (s === "installed" || s === "installing") continue;
        await install(id);
      }
    } finally {
      setInstallingAll(false);
    }
  };

  // Auto re-test: fire once every dep has settled (installed/warn/error) and at
  // least one was actually installed — gated off mid-batch so it boots only once.
  useEffect(() => {
    if (retested.current || installingAll || testing) return;
    const allSettled = mods.every((id) => SETTLED.has(states[id] ?? "idle"));
    const anyInstalled = mods.some((id) => states[id] === "installed");
    if (allSettled && anyInstalled) {
      retested.current = true;
      onRetest();
    }
  }, [states, installingAll, testing, mods, onRetest]);

  const remaining = mods.filter((id) => (states[id] ?? "idle") !== "installed").length;
  const busy = installingAll || mods.some((id) => states[id] === "installing");

  return (
    <div className="panel missing-deps">
      <p className="note">
        {mods.length} missing {mods.length > 1 ? "dependencies" : "dependency"} — install from
        Modrinth; it re-tests automatically once they're in.
      </p>
      {remaining > 0 && (
        <button
          type="button"
          className="btn-primary install-all"
          onClick={installAll}
          disabled={busy}
        >
          {installingAll
            ? "installing…"
            : `Install all & re-test${remaining < mods.length ? ` (${remaining} left)` : ""}`}
        </button>
      )}
      <ul className="missing-list">
        {mods.map((id) => (
          <InstallRow
            key={id}
            modId={id}
            state={states[id] ?? "idle"}
            msg={msgs[id] ?? null}
            disabled={installingAll}
            onInstall={install}
          />
        ))}
      </ul>
    </div>
  );
}

// Shared "runner not available for this version" notice (both runtime tabs).
function RunnerUnsupported({ block }: { block: string | null }) {
  return (
    <p className="note">
      Runtime testing isn't available yet for {block ?? "this version"} — static analysis only. The
      headless runner needs server artifacts that aren't published for this block.
    </p>
  );
}

// The suspected cause of a verdict: summary, the mods that may be involved, an
// optional log excerpt, and — when the cause is a missing dependency — a handoff
// to the Resolution › Deps installer (the installer itself now lives there).
function VerdictCause({ cause, onResolve }: { cause: RunCause; onResolve: () => void }) {
  return (
    <>
      <p className="note">
        {cause.category}: {cause.summary}
      </p>
      <p>
        The runner detected {cause.mods.length} mod
        {cause.mods.length > 1 ? "s" : ""} that may be involved :
      </p>
      <ul>
        <li className="note cause-mods">{cause.mods.length > 0 && `${cause.mods.join(", ")}`}</li>
      </ul>
      {cause.excerpt && (
        <details className="cause-excerpt">
          <summary>Causes</summary>
          <pre className="log">{cause.excerpt}</pre>
        </details>
      )}
      {cause.category === "missing_dependency" && cause.mods.length > 0 && (
        <button type="button" className="btn-ghost resolve-handoff" onClick={onResolve}>
          Install in Resolution › Deps →
        </button>
      )}
    </>
  );
}

// The verdict readout: status line, the suspected cause (with the Deps handoff
// when that's the category), and the log tail.
function VerdictPanel({ verdict, onResolve }: { verdict: RunVerdict; onResolve: () => void }) {
  return (
    <div className="panel">
      <p>
        <span className={`run-${verdict.status}`}>{verdict.status.toUpperCase()}</span>
        {" · "}
        {(verdict.durationMs / 1000).toFixed(1)}s
        {verdict.mixinExports.length > 0 &&
          ` · ${verdict.mixinExports.length} mixin-transformed classes (ground truth)`}
      </p>
      {verdict.cause && <VerdictCause cause={verdict.cause} onResolve={onResolve} />}
      {verdict.logTail && verdict.status !== "error" && (
        <details className="log-tail">
          <summary>Log tail</summary>
          <pre className="log">{verdict.logTail}</pre>
        </details>
      )}
    </div>
  );
}

// "Test" sub-tab: boot the whole set headlessly and read the verdict; a missing
// dependency hands off to Resolution › Deps for the install.
function TestView({
  verdict,
  onTest,
  testing,
  runnerSupported,
  block,
  onResolve,
}: {
  verdict: RunVerdict | null;
  runnerSupported: boolean;
  block: string | null;
  onResolve: () => void;
} & TestProps) {
  return (
    <div className="view">
      {!runnerSupported && <RunnerUnsupported block={block} />}
      <section className="runner">
        <TestButton onTest={onTest} testing={testing} disabled={!runnerSupported} />
        {testing && <span className="note"> a real boot takes minutes; needs Docker running</span>}
      </section>

      {verdict ? (
        <VerdictPanel verdict={verdict} onResolve={onResolve} />
      ) : (
        <p className="note">No boot yet. Run a test to get a runtime verdict.</p>
      )}
    </div>
  );
}

// The bisection readout: status line, the isolated guilty set, the cause, and any
// inconclusive note.
function BisectPanel({ bisectResult }: { bisectResult: BisectResult }) {
  return (
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
        <>
          <p className="members">The guilty set that caused the issue: </p>
          <ul>
            <li className="note cause-mods">{bisectResult.members.join(", ")}</li>
          </ul>
        </>
      )}
      {bisectResult.cause && (
        <p className="note">
          {bisectResult.cause.category}: {bisectResult.cause.summary}
        </p>
      )}
      {bisectResult.note && <p className="note">{bisectResult.note}</p>}
    </div>
  );
}

// "Bisect" sub-tab: delta-debug a crashing set down to the minimal guilty subset.
function BisectView({
  onBisect,
  bisecting,
  bisectResult,
  runnerSupported,
  block,
}: {
  onBisect: () => void;
  bisecting: boolean;
  bisectResult: BisectResult | null;
  runnerSupported: boolean;
  block: string | null;
}) {
  return (
    <div className="view">
      {!runnerSupported && <RunnerUnsupported block={block} />}
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

      {bisectResult ? (
        <BisectPanel bisectResult={bisectResult} />
      ) : (
        <p className="note">No bisection yet. Run one to isolate the guilty subset.</p>
      )}
    </div>
  );
}

type RuntimeSub = "test" | "bisect";

// "Runtime" tab: a single panel split into two sub-tabs — Test (boot the set) and
// Bisect (isolate the guilty subset) — that share the same verdict/bisect state.
export function RuntimeView({
  verdict,
  onTest,
  testing,
  onBisect,
  bisecting,
  bisectResult,
  runnerSupported,
  block,
  onResolve,
}: {
  verdict: RunVerdict | null;
  onBisect: () => void;
  bisecting: boolean;
  bisectResult: BisectResult | null;
  runnerSupported: boolean;
  block: string | null;
  onResolve: () => void;
} & TestProps) {
  const [sub, setSub] = useState<RuntimeSub>("test");
  return (
    <div className="view">
      <div className="subtabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={sub === "test"}
          className={sub === "test" ? "chip chip-on" : "chip"}
          onClick={() => setSub("test")}
        >
          Test
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={sub === "bisect"}
          className={sub === "bisect" ? "chip chip-on" : "chip"}
          onClick={() => setSub("bisect")}
        >
          Bisect
        </button>
      </div>

      {sub === "test" ? (
        <TestView
          verdict={verdict}
          onTest={onTest}
          testing={testing}
          runnerSupported={runnerSupported}
          block={block}
          onResolve={onResolve}
        />
      ) : (
        <BisectView
          onBisect={onBisect}
          bisecting={bisecting}
          bisectResult={bisectResult}
          runnerSupported={runnerSupported}
          block={block}
        />
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
          {conflicts.length} datapack override{conflicts.length > 1 ? "s" : ""} - two datapacks ship
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

// --- Mixin resolver (PROJECT.md §7): version-match first, disable as fallback --

// Reversible sideline: moves a jar to `disabled/` (disable) and back (enable). A
// plain toggle — no download, no state machine beyond the in-flight guard.
function DisableButton({ modsPath, jar }: { modsPath: string; jar: string }) {
  const [state, setState] = useState<"idle" | "busy" | "disabled" | "error">("idle");
  const [msg, setMsg] = useState<string | null>(null);

  const toggle = async () => {
    if (state === "busy") return;
    const enabling = state === "disabled";
    setState("busy");
    setMsg(null);
    try {
      const r = enabling ? await enableMod(modsPath, jar) : await disableMod(modsPath, jar);
      if (r.status === "disabled") setState("disabled");
      else if (r.status === "enabled") setState("idle");
      else {
        setState("error");
        setMsg(r.message ?? r.status);
      }
    } catch (e) {
      setState("error");
      setMsg(e instanceof Error ? e.message : String(e));
    }
  };

  const label = state === "disabled" ? "enable" : state === "busy" ? "…" : "disable";
  return (
    <button
      type="button"
      className={`btn-ghost mixin-disable mixin-disable-${state}`}
      onClick={toggle}
      disabled={state === "busy"}
      title={msg ?? (state === "disabled" ? "restore this mod" : "sideline this mod (reversible)")}
    >
      {label}
    </button>
  );
}

// One member of a mixin cluster: its identity, the version-match update (when a
// compatible build exists) and the reversible disable fallback.
function MixinMemberRow({
  member,
  modsPath,
  version,
  updatedJars,
  onUpdated,
}: {
  member: MixinClusterMember;
  modsPath: string;
  version: string;
  updatedJars: Set<string>;
  onUpdated: (jar: string) => void;
}) {
  // Narrow to a concrete Mod so the version-match button only renders (and type-checks)
  // when this member is a top-level jar with a compatible update available.
  const updatableMod = member.mod?.updateAvailable && member.jar ? member.mod : null;
  return (
    <li className="mixin-member">
      <span className="mixin-member-id">
        {member.mod?.name ?? member.modId}
        {member.currentVersion && <span className="mixin-member-v">{member.currentVersion}</span>}
      </span>
      <div className="mixin-member-actions">
        {updatableMod && member.jar && (
          <UpdateButton
            mod={updatableMod}
            modsPath={modsPath}
            version={version}
            alreadyUpdated={updatedJars.has(member.jar)}
            onUpdated={onUpdated}
          />
        )}
        {member.jar && <DisableButton modsPath={modsPath} jar={member.jar} />}
      </div>
    </li>
  );
}

// One cluster: the co-patching mods, the shared target/methods, and a per-member
// action list. Version-match is the headline fix; disable is the safe fallback.
function MixinClusterCard({
  cluster,
  modsPath,
  version,
  updatedJars,
  onUpdated,
}: {
  cluster: MixinCluster;
  modsPath: string;
  version: string;
  updatedJars: Set<string>;
  onUpdated: (jar: string) => void;
}) {
  const canUpdate = cluster.members.some((m) => m.updateAvailable);
  const detail =
    cluster.sharedMethods.length > 0
      ? `same method${cluster.sharedMethods.length > 1 ? "s" : ""}: ${cluster.sharedMethods.join(", ")}`
      : cluster.targets.join(", ");
  return (
    <details className="conflict-group" open>
      <summary className="group-head">
        <Chevron />
        <span className="group-name recipe-pair">
          {cluster.members.map((m) => m.modId).join(" ↔ ")}
        </span>
        {cluster.confirmedAtRuntime && <span className="tag-confirmed">confirmed at runtime</span>}
      </summary>
      <div className="mixin-cluster-body">
        <p className="note">
          Both patch the {detail} —{" "}
          {canUpdate
            ? "update one to a compatible build, or disable one (reversible)."
            : "no compatible update found; disable one (reversible) to break the conflict."}
        </p>
        <ul className="mixin-members">
          {cluster.members.map((m) => (
            <MixinMemberRow
              key={m.modId}
              member={m}
              modsPath={modsPath}
              version={version}
              updatedJars={updatedJars}
              onUpdated={onUpdated}
            />
          ))}
        </ul>
      </div>
    </details>
  );
}

// The mixin-resolver block: the actionable clusters plus a headless re-test to
// confirm the fix actually boots — the verify loop the static map can't close.
function MixinResolver({
  clusters,
  modsPath,
  version,
  verdict,
  testing,
  onTest,
  updatedJars,
  onUpdated,
}: {
  clusters: MixinCluster[];
  modsPath: string;
  version: string;
  verdict: RunVerdict | null;
  testing: boolean;
  onTest: () => void;
  updatedJars: Set<string>;
  onUpdated: (jar: string) => void;
}) {
  if (clusters.length === 0) return null;
  return (
    <section className="mixin-resolver">
      <h2 className="resolution-section">Mixin conflicts</h2>
      <p className="note">
        {clusters.length} likely mixin conflict{clusters.length > 1 ? "s" : ""} — two mods patch the
        same target incompatibly. Try a compatible update first, disable as a fallback, then
        re-test.
      </p>
      <div className="conflict-groups">
        {clusters.map((c) => (
          <MixinClusterCard
            key={c.key}
            cluster={c}
            modsPath={modsPath}
            version={version}
            updatedJars={updatedJars}
            onUpdated={onUpdated}
          />
        ))}
      </div>
      <section className="runner">
        <button className="btn-primary" type="button" onClick={onTest} disabled={testing}>
          {testing ? "booting…" : "Re-test (headless boot)"}
        </button>
        {verdict && !testing && (
          <span className="note">
            last boot:{" "}
            <span className={`run-${verdict.status}`}>{verdict.status.toUpperCase()}</span>
            {verdict.cause && ` · ${verdict.cause.summary}`}
          </span>
        )}
      </section>
    </section>
  );
}

// Shared generate → preview → export flow for one conflict family (Tags emits
// unify.json; Recipes emits the override datapack). Parametrised so both sub-tabs
// drive the same /resolve endpoints with a `families` filter.
function ConfigGenerator({
  modsPath,
  version,
  family,
  generateLabel,
}: {
  modsPath: string;
  version?: string;
  family: ResolutionFamily;
  generateLabel: string;
}) {
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
      setPlan(await resolvePreview(modsPath, version, [family]));
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
      setExported(await resolveExport(modsPath, dir, version, [family]));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setExporting(false);
    }
  };

  return (
    <>
      <section className="runner">
        <button
          className="btn-primary"
          type="button"
          onClick={() => void generate()}
          disabled={loading}
        >
          {loading ? "generating…" : generateLabel}
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
    </>
  );
}

// Browse the conventional-tag overlaps (≥2 mods feeding the same `c:`/`forge:`
// tag), each expanding to the per-mod item contributions.
function TagsBrowse({ conflicts }: { conflicts: Conflict[] }) {
  if (conflicts.length === 0) {
    return (
      <p className="note">No tag overlaps — no conventional tag is fed by more than one mod.</p>
    );
  }
  return (
    <>
      <p className="note">
        {conflicts.length} conventional tag{conflicts.length > 1 ? "s" : ""} fed by more than one
        mod — duplicate content; unify picks one canonical item per tag.
      </p>
      <div className="conflict-groups">
        {conflicts.map((c) => {
          const n = conflictItems(c).length;
          return (
            <details key={conflictKey(c)} className="conflict-group">
              <summary className="group-head">
                <Chevron />
                <span className="group-name recipe-pair">{conflictSubject(c)}</span>
                <span className="group-count">
                  · {c.members.length} mods · {n} item{n > 1 ? "s" : ""}
                </span>
              </summary>
              <dl className="bymod">
                {Object.entries(conflictByMod(c)).map(([mod, items]) => (
                  <div className="bymod-row" key={mod}>
                    <dt>{mod}</dt>
                    <dd>{items.join(", ")}</dd>
                  </div>
                ))}
              </dl>
            </details>
          );
        })}
      </div>
    </>
  );
}

// Recipes sub-tab: browse the collisions, then generate the override datapack.
function RecipesResolution({
  conflicts,
  modsPath,
  version,
}: {
  conflicts: Conflict[];
  modsPath: string;
  version?: string;
}) {
  return (
    <>
      <RecipesView conflicts={conflicts} />
      <h2 className="resolution-section">Override datapack</h2>
      <ConfigGenerator
        modsPath={modsPath}
        version={version}
        family="recipes"
        generateLabel="Generate recipe datapack"
      />
    </>
  );
}

// Tags sub-tab: browse the tag overlaps, then generate the Almost Unified config.
function TagsResolution({
  conflicts,
  modsPath,
  version,
}: {
  conflicts: Conflict[];
  modsPath: string;
  version?: string;
}) {
  const tagOverlaps = conflicts.filter((c) => c.type === "tag_overlap");
  return (
    <>
      <TagsBrowse conflicts={tagOverlaps} />
      <h2 className="resolution-section">unify.json</h2>
      <ConfigGenerator
        modsPath={modsPath}
        version={version}
        family="tags"
        generateLabel="Generate unify.json"
      />
    </>
  );
}

// Deps sub-tab: install the mods a boot flagged as missing. Reuses the verdict's
// missing-dependency cause when present; otherwise offers an in-place boot.
function DepsResolution({
  verdict,
  modsPath,
  version,
  loader,
  onTest,
  testing,
}: {
  verdict: RunVerdict | null;
  modsPath: string;
  version: string;
  loader?: Loader;
  onTest: () => void;
  testing: boolean;
}) {
  const cause = verdict?.cause;
  const missing = cause?.category === "missing_dependency" ? cause.mods : [];
  if (missing.length > 0) {
    return (
      <MissingDepsPanel
        key={`${verdict?.durationMs}:${missing.join(",")}`}
        mods={missing}
        modsPath={modsPath}
        version={version}
        loader={loader}
        onRetest={onTest}
        testing={testing}
      />
    );
  }
  return (
    <>
      <p className="note">
        No missing-dependency verdict yet. A headless boot detects which dependencies the set is
        missing; they can then be installed here.
      </p>
      <section className="runner">
        <button className="btn-primary" type="button" onClick={onTest} disabled={testing}>
          {testing ? "booting…" : "Run headless boot"}
        </button>
      </section>
    </>
  );
}

const RESOLUTION_SUBS: { id: ResolutionSub; label: string }[] = [
  { id: "mixins", label: "Mixins" },
  { id: "recipes", label: "Recipes" },
  { id: "tags", label: "Tags" },
  { id: "deps", label: "Deps" },
];

// The Resolution hub: one sub-tab per conflict family, each the single place to
// act on it. Fed by the static scan and refined by the runtime verdict (mixin
// confirmation, the missing-dependency list) when a boot has run.
export function ResolutionView({
  modsPath,
  version,
  conflicts,
  mods,
  verdict,
  testing,
  onTest,
  updatedJars,
  onUpdated,
  loader,
  sub,
  setSub,
}: {
  modsPath: string;
  version?: string;
  conflicts: Conflict[];
  mods: Mod[];
  verdict: RunVerdict | null;
  testing: boolean;
  onTest: () => void;
  updatedJars: Set<string>;
  onUpdated: (jar: string) => void;
  loader?: Loader;
  sub: ResolutionSub;
  setSub: (sub: ResolutionSub) => void;
}) {
  const mixinExports = useMemo(() => (verdict ? new Set(verdict.mixinExports) : null), [verdict]);
  const clusters = useMemo(
    () => groupMixinClusters(conflicts, mods, mixinExports),
    [conflicts, mods, mixinExports],
  );

  return (
    <div className="view">
      <div className="subtabs" role="tablist">
        {RESOLUTION_SUBS.map((s) => (
          <button
            key={s.id}
            type="button"
            role="tab"
            aria-selected={sub === s.id}
            className={sub === s.id ? "chip chip-on" : "chip"}
            onClick={() => setSub(s.id)}
          >
            {s.label}
          </button>
        ))}
      </div>

      {sub === "mixins" &&
        (clusters.length > 0 ? (
          <MixinResolver
            clusters={clusters}
            modsPath={modsPath}
            version={version ?? ""}
            verdict={verdict}
            testing={testing}
            onTest={onTest}
            updatedJars={updatedJars}
            onUpdated={onUpdated}
          />
        ) : (
          <p className="note">
            No likely mixin conflicts — no two mods patch the same target incompatibly.
          </p>
        ))}

      {sub === "recipes" && (
        <RecipesResolution conflicts={conflicts} modsPath={modsPath} version={version} />
      )}

      {sub === "tags" && (
        <TagsResolution conflicts={conflicts} modsPath={modsPath} version={version} />
      )}

      {sub === "deps" && (
        <DepsResolution
          verdict={verdict}
          modsPath={modsPath}
          version={version ?? ""}
          loader={loader}
          onTest={onTest}
          testing={testing}
        />
      )}
    </div>
  );
}
