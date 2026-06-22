import {
  type ReactNode,
  type RefObject,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { VirtualList } from "./components/VirtualList";
import type {
  ApplyResult,
  ApplyTarget,
  BisectResult,
  Conflict,
  Datapack,
  Loader,
  Mod,
  ModEnvironment,
  RegistryIndex,
  ResolutionTargets,
  ResolutionVariants,
  ResourcePack,
  RunCause,
  RunVerdict,
  ScanResult,
  Severity,
  ShaderPack,
} from "./lib/api";
import {
  applyResolution,
  disableMod,
  enableMod,
  installMod,
  loadRecipeVariants,
  peekRecipeVariants,
  resolveTargets,
  revertResolution,
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
  isRecipeCollision,
  isRuntimeConfirmed,
  type MixinAutoFix,
  type MixinCluster,
  type MixinClusterMember,
  planMixinAutoFix,
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
      {testing ? "Booting…" : "Test this set"}
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
  // Recipe collisions are resolved in Resolution › Recipes; keep them out of this
  // view so the two never overlap.
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

// Windowed mod list: a thin wrapper that renders a mod card or an unreadable-jar
// card per entry, keyed by jar name.
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
  return (
    <VirtualList
      items={entries}
      keyOf={(e) => e.jar}
      estimate={CARD_ESTIMATE}
      scrollRef={scrollRef}
      className="mods-list"
      renderItem={(entry) =>
        entry.kind === "mod" ? (
          <ModCard
            mod={entry.mod}
            modsPath={modsPath}
            version={version}
            alreadyUpdated={updatedJars.has(entry.jar)}
            onUpdated={onUpdated}
          />
        ) : (
          <ErrorCard name={entry.name} jar={entry.jar} reason={entry.reason} />
        )
      }
    />
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
        {busy && "Installing… "}
        {remaining} remaining to install.
      </p>
      <p className="note">
        The flagged dependencies can be installed from Modrinth. Click the download icon to install
        one, or "Install all" to batch the installation. The test will auto re-run after every dep
        installation attempt, and will confirm the fix.
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
        <button type="button" className="btn-secondary resolve-handoff" onClick={onResolve}>
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

// A collapsed override row is ~one summary line tall; opened rows re-measure.
const OVERRIDE_ESTIMATE = 48;

// One override group: the colliding set of packs and, behind a disclosure, the
// shared paths. Same shape as a recipe collision.
function OverrideRow({ c, unit }: { c: Conflict; unit: string }) {
  const paths = (c.detail.paths as string[] | undefined) ?? [];
  const count = (c.detail.count as number | undefined) ?? paths.length;
  return (
    <details className="conflict-group">
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
}

// Override groups (resource-pack assets / datapack data shared by ≥2 packs),
// windowed so a pack with many collisions doesn't flood the DOM.
function OverrideList({ conflicts, unit }: { conflicts: Conflict[]; unit: string }) {
  if (conflicts.length === 0) return null;
  return (
    <VirtualList
      items={conflicts}
      keyOf={(c) => c.members.join("|")}
      estimate={OVERRIDE_ESTIMATE}
      gap={8}
      className="conflict-groups"
      renderItem={(c) => <OverrideRow c={c} unit={unit} />}
    />
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
      className={`btn-secondary mixin-disable mixin-disable-${state}`}
      onClick={toggle}
      disabled={state === "busy"}
      title={msg ?? (state === "disabled" ? "restore this mod" : "sideline this mod (reversible)")}
    >
      {label}
    </button>
  );
}

// The last dotted segment of an intermediary class name, for a compact headline:
// `net.minecraft.class_310` -> `class_310`. The full name stays in the body.
function shortClass(name: string): string {
  const i = name.lastIndexOf(".");
  return i >= 0 ? name.slice(i + 1) : name;
}

// A member's identity line — display name (falling back to the id) and its current
// version. Shared by the actionable and broad-co-patch rows.
function MixinMemberIdentity({ member }: { member: MixinClusterMember }) {
  return (
    <span className="mixin-member-id">
      {member.mod?.name ?? member.modId}
      {member.currentVersion && <span className="mixin-member-v">{member.currentVersion}</span>}
    </span>
  );
}

// One member of a mixin cluster: a reversible disable toggle on the left (click to
// sideline the mod, click again to restore it) and, when a compatible build
// exists, the version-match update on the right. Shared by both card kinds.
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
      {member.jar && <DisableButton modsPath={modsPath} jar={member.jar} />}
      <MixinMemberIdentity member={member} />
      {updatableMod && member.jar && (
        <div className="mixin-member-actions">
          <UpdateButton
            mod={updatableMod}
            modsPath={modsPath}
            version={version}
            alreadyUpdated={updatedJars.has(member.jar)}
            onUpdated={onUpdated}
          />
        </div>
      )}
    </li>
  );
}

// One actionable cluster (a handful of mods patching the same target): each mod
// gets a reversible disable and, when offered, a version-match update. Open by
// default — these are the rows the user is meant to act on.
function MixinConflictCard({
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
      : cluster.targets.map(shortClass).join(", ");
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
          They patch the {detail} —{" "}
          {canUpdate
            ? "update one to a compatible build, or disable one (reversible)."
            : "disable one (reversible) to break the conflict."}
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

// Rows past this are hidden behind a "+N more" toggle so a broad co-patch (a dozen+
// mods on one class) can't flood the DOM. Only broad cards need it — actionable
// clusters are capped at MIXIN_PAIRWISE_MAX members upstream.
const MIXIN_MEMBER_CAP = 6;

// First-paint heights for the windowed cluster lists; real heights replace them.
const MIXIN_CARD_ESTIMATE = 150; // an open actionable card with a few members
const MIXIN_BROAD_ESTIMATE = 48; // a collapsed broad co-patch (summary only)

// One broad co-patch (many mods on a popular class): collapsed by default and
// framed as noise — disabling isn't the fix, a re-test is. Members are capped with
// a "+N more" reveal. No keep-pick: there's no single winner to choose.
function MixinBroadCard({
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
  const [showAll, setShowAll] = useState(false);
  const shown = showAll ? cluster.members : cluster.members.slice(0, MIXIN_MEMBER_CAP);
  const hidden = cluster.members.length - shown.length;
  const target = cluster.targets[0] ?? "a shared class";
  return (
    <details className="conflict-group mixin-broad">
      <summary className="group-head">
        <Chevron />
        <span className="group-name">{shortClass(target)}</span>
        <span className="group-count">· {cluster.members.length} mods</span>
        {cluster.confirmedAtRuntime && <span className="tag-confirmed">confirmed at runtime</span>}
      </summary>
      <div className="mixin-cluster-body">
        <p className="note">
          {cluster.members.length} mods co-patch {target}
          {cluster.sharedMethods.length > 0 && ` (methods: ${cluster.sharedMethods.join(", ")})`} —
          usually harmless. Disabling one rarely helps here; re-test to confirm the set boots.
        </p>
        <ul className="mixin-members">
          {shown.map((m) => (
            <MixinMemberRow
              key={m.modId}
              member={m}
              modsPath={modsPath}
              version={version}
              updatedJars={updatedJars}
              onUpdated={onUpdated}
            />
          ))}
          {hidden > 0 && (
            <li className="mixin-more">
              <button type="button" className="note-link" onClick={() => setShowAll(true)}>
                +{hidden} more
              </button>
            </li>
          )}
        </ul>
      </div>
    </details>
  );
}

// The mixin-resolver block: actionable pairwise picks first, the broad co-patches
// folded into a collapsed bucket below, then a headless re-test to confirm the fix
// actually boots — the verify loop the static map can't close.
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
  // Already sorted actionable-first by groupMixinClusters; partition for layout.
  const actionable = useMemo(() => clusters.filter((c) => !c.broad), [clusters]);
  const broad = useMemo(() => clusters.filter((c) => c.broad), [clusters]);
  // One deterministic action per conflict the planner can decide (centrality →
  // update → library role); conflicts it can't decide are left to the user.
  const plans = useMemo<MixinAutoFix[]>(
    () => actionable.map(planMixinAutoFix).filter((p) => p.kind !== "none"),
    [actionable],
  );
  const [fixing, setFixing] = useState(false);
  // Applied state + summary are keyed to the cluster signature, so a fresh scan
  // (new signature) auto-clears them — derived, no effect to keep in sync.
  const [fixState, setFixState] = useState<{
    sig: string;
    summary: string;
  } | null>(null);
  const sig = actionable.map((c) => c.key).join("|");
  const applied = fixState?.sig === sig;
  const summary = applied && fixState ? fixState.summary : null;

  // Apply every planned action in order (serial: one shared mods folder). Disables
  // are immediate; an update swaps the jar in place and needs a re-scan after, so
  // the summary says so. Whatever lands is reflected in the count.
  const autoFix = async () => {
    setFixing(true);
    let disabled = 0;
    let updated = 0;
    try {
      for (const p of plans) {
        if (p.kind === "disable") {
          for (const jar of p.jars) {
            try {
              const r = await disableMod(modsPath, jar);
              if (r.status === "disabled") disabled++;
            } catch {
              // best-effort: keep going, the summary reflects what landed
            }
          }
        } else if (p.kind === "update") {
          for (const u of p.jars) {
            try {
              const r = await updateMod(modsPath, u.jar, version, u.loader);
              if (r.status === "updated") {
                updated++;
                onUpdated(u.jar);
              }
            } catch {
              // best-effort: keep going
            }
          }
        }
      }
    } finally {
      const parts: string[] = [];
      if (disabled) parts.push(`disabled ${disabled}`);
      if (updated) parts.push(`updated ${updated}`);
      setFixState({
        sig,
        summary:
          parts.length > 0
            ? `Auto-fix: ${parts.join(", ")}`
            : "Auto-fix: nothing could be applied automatically.",
      });
      setFixing(false);
    }
  };

  if (clusters.length === 0) return null;
  const cardProps = { modsPath, version, updatedJars, onUpdated };
  return (
    <section className="mixin-resolver">
      <h2 className="resolution-section">Mixin conflicts</h2>
      {actionable.length > 0 ? (
        <>
          <p className="note">
            {actionable.length} likely mixin conflict
            {actionable.length > 1 ? "s" : ""}. For each conflict, either update one mod to a
            compatible build (if offered) or enable only one of the conflicting mods (reversible).
            Then re-test to confirm the fix.
          </p>
          <VirtualList
            items={actionable}
            keyOf={(c) => c.key}
            estimate={MIXIN_CARD_ESTIMATE}
            gap={8}
            className="conflict-groups"
            renderItem={(c) => <MixinConflictCard cluster={c} {...cardProps} />}
          />
        </>
      ) : (
        <p className="note">
          No likely pairwise mixin conflicts — only the broad co-patches below, which are usually
          harmless.
        </p>
      )}

      {broad.length > 0 && (
        <details className="mixin-broad-section">
          <summary className="group-head">
            <Chevron />
            <span className="group-name">Broad co-patches</span>
            <span className="group-count">· {broad.length}</span>
            <span className="group-hint">many mods share a hot class — usually harmless</span>
          </summary>
          <VirtualList
            items={broad}
            keyOf={(c) => c.key}
            estimate={MIXIN_BROAD_ESTIMATE}
            gap={8}
            className="conflict-groups"
            renderItem={(c) => <MixinBroadCard cluster={c} {...cardProps} />}
          />
        </details>
      )}

      <section className="runner">
        <button
          className="btn-secondary no-wrap"
          type="button"
          onClick={() => void autoFix()}
          disabled={fixing || applied || plans.length === 0}
          title="Apply every conflict the planner can decide — keep the load-bearing or library mod, or update — and leave the rest to you."
        >
          {fixing ? "Auto-fixing…" : "Auto-fix"}
        </button>
        <button className="btn-primary no-wrap" type="button" onClick={onTest} disabled={testing}>
          {testing ? "Booting…" : "Run the test again"}
        </button>
        {summary && <span className="note">{summary}</span>}
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
// The modpack's base folder, used to prefill the output path: strip a trailing
// `mods` segment from the scanned mods folder (the generated config/datapack live
// at the pack root). Falls back to the mods path when it isn't a `mods` folder.
// Apply sub-tab: write the winning recipes + tags into the instance, reversibly.
// Target is the user's choice — per-world (no dependency) or global via Open Loader.
function ApplyResolution({
  instanceRoot,
  modsPath,
  version,
  loader,
  recipeWinners,
  tagWinners,
}: {
  instanceRoot: string;
  modsPath: string;
  version?: string;
  loader?: Loader;
  recipeWinners: Record<string, string>;
  tagWinners: Record<string, string>;
}) {
  const [targets, setTargets] = useState<ResolutionTargets | null>(null);
  const [target, setTarget] = useState<ApplyTarget>("per_world");
  const [applying, setApplying] = useState(false);
  const [done, setDone] = useState(false);
  const [result, setResult] = useState<ApplyResult | null>(null);
  const [reverting, setReverting] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const doneTimer = useRef<number | undefined>(undefined);

  useEffect(() => () => window.clearTimeout(doneTimer.current), []);

  useEffect(() => {
    let active = true;
    resolveTargets(instanceRoot, version)
      .then((t) => active && setTargets(t))
      .catch(() => active && setTargets(null));
    return () => {
      active = false;
    };
  }, [instanceRoot, version]);

  const apply = async () => {
    setApplying(true);
    setError(null);
    try {
      const r = await applyResolution(instanceRoot, version, { recipeWinners, tagWinners }, target);
      setResult(r);
      if (r.status === "applied") {
        setDone(true);
        window.clearTimeout(doneTimer.current);
        doneTimer.current = window.setTimeout(() => setDone(false), 3000);
      } else if (r.status === "error") {
        setError(r.message ?? "Apply failed.");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setApplying(false);
    }
  };

  const revert = async () => {
    if (!result?.manifest) return;
    setReverting(true);
    setError(null);
    try {
      const r = await revertResolution(result.manifest);
      if (r.status === "reverted") setResult(null);
      else setError(r.message ?? "Revert failed.");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setReverting(false);
    }
  };

  // Install Open Loader from Modrinth so the global target becomes available
  // without leaving the app, then re-check the pack's capabilities.
  const installOpenLoader = async () => {
    setInstalling(true);
    setError(null);
    try {
      const r = await installMod(modsPath, "openloader", version, loader);
      if (r.status === "installed") {
        setTargets(await resolveTargets(instanceRoot, version));
      } else {
        setError(r.message ?? "Could not install Open Loader.");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setInstalling(false);
    }
  };

  const au = targets?.almostUnified ?? false;
  const openLoader = targets?.openLoader ?? false;
  const globalUnavailable = target === "openloader" && !openLoader;

  return (
    <div className="view">
      <p className="note">
        Writes the winning recipes and tags into the pack, reversibly. Tags use{" "}
        {au ? "Almost Unified (unify.json)" : "a re-tag datapack"}.
      </p>

      <div className="filters">
        <button
          type="button"
          aria-pressed={target === "per_world"}
          className={target === "per_world" ? "chip chip-on" : "chip"}
          onClick={() => setTarget("per_world")}
        >
          Per-world
        </button>
        <button
          type="button"
          aria-pressed={target === "openloader"}
          className={target === "openloader" ? "chip chip-on" : "chip"}
          onClick={() => setTarget("openloader")}
        >
          Global (Need Open Loader)
        </button>
      </div>

      <p className="note">
        {target === "per_world"
          ? "Copied into each datapacks/ folder (and a global datapacks/ if present). Existing worlds only, not future ones."
          : openLoader
            ? "Written under openloader/data/ so it loads globally like a mod, including future worlds."
            : "Global loading needs the Open Loader mod, which this pack doesn't have. Install it, or use per-world."}
      </p>

      {globalUnavailable && (
        <section className="runner">
          <button
            className="btn-primary"
            type="button"
            onClick={() => void installOpenLoader()}
            disabled={installing}
          >
            {installing ? "Installing…" : "Install Open Loader"}
          </button>
        </section>
      )}

      <section className="runner">
        <button
          className="btn-primary"
          type="button"
          onClick={() => void apply()}
          disabled={applying || done || globalUnavailable}
        >
          {applying ? "Applying…" : done ? "Done" : "Apply to pack"}
        </button>
        {result?.manifest && (
          <button
            className="btn-secondary"
            type="button"
            onClick={() => void revert()}
            disabled={reverting}
          >
            {reverting ? "Reverting…" : "Revert"}
          </button>
        )}
      </section>

      {result?.status === "nothing" && (
        <p className="note">Nothing to apply — no resolvable recipe/tag conflicts.</p>
      )}
      {result?.status === "applied" && (
        <p className="note">
          Wrote {result.written.length} file(s) into {result.targets.length} location(s).
        </p>
      )}
      {error && <p className="scan-error">{error}</p>}
    </div>
  );
}

// --- Selection cards: pick the winner per conflict (recipe / tag) -------------

interface SelectionVariant {
  mod: string;
  detail: string; // recipe: a short "type → result" summary; tag: the items it feeds
  content?: string; // recipe: the full JSON, behind an expand
}

interface SelectionConflict {
  id: string; // subject id — the selection key and React key
  defaultMod: string; // Emendator's default winner (first mod alphabetically)
  variants: SelectionVariant[];
}

// The default winner mirrors the backend: first mod id alphabetically among the
// conflict's contributors. Picking nothing keeps this.
function defaultWinner(mods: string[]): string {
  return [...mods].sort()[0] ?? "";
}

function capitalize(s: string): string {
  return s ? s[0].toUpperCase() + s.slice(1) : s;
}

// Humanise a recipe/tag id for display only (the raw id stays the selection key):
// `farmersdelight:cooking/fried_rice` -> `Farmersdelight: Cooking/Fried rice`.
function prettySubject(id: string): string {
  const [namespace, ...rest] = id.split(":");
  const path = rest.join(":");
  if (!path) return capitalize(namespace);
  const prettyPath = path
    .split("/")
    .map((seg) => capitalize(seg.replace(/_/g, " ")))
    .join("/");
  return `${capitalize(namespace)}: ${prettyPath}`;
}

// A compact "type → result" line from a recipe JSON, best-effort.
function summarizeRecipe(content: string): string {
  try {
    const json = JSON.parse(content) as Record<string, unknown>;
    const type = typeof json.type === "string" ? json.type.replace(/^minecraft:/, "") : "recipe";
    const result = json.result;
    let item = "";
    if (typeof result === "string") item = result;
    else if (result && typeof result === "object") {
      const r = result as Record<string, unknown>;
      item = String(r.id ?? r.item ?? "");
    }
    return item ? `${type} → ${item}` : type;
  } catch {
    return "recipe";
  }
}

function recipeSelections(variants: ResolutionVariants): SelectionConflict[] {
  return Object.entries(variants.recipes)
    .map(([id, vs]) => ({
      id,
      defaultMod: defaultWinner(vs.map((v) => v.mod)),
      variants: vs.map((v) => ({
        mod: v.mod,
        detail: summarizeRecipe(v.content),
        content: v.content,
      })),
    }))
    .sort((a, b) => a.id.localeCompare(b.id));
}

function tagSelections(conflicts: Conflict[]): SelectionConflict[] {
  return conflicts
    .filter((c) => c.type === "tag_overlap")
    .map((c) => {
      const byMod = conflictByMod(c);
      const mods = Object.keys(byMod).sort();
      return {
        id: conflictSubject(c),
        defaultMod: defaultWinner(mods),
        variants: mods.map((mod) => ({ mod, detail: byMod[mod].join(", ") })),
      };
    })
    .sort((a, b) => a.id.localeCompare(b.id));
}

function VariantButton({
  variant,
  selected,
  onPick,
}: {
  variant: SelectionVariant;
  selected: boolean;
  onPick: () => void;
}) {
  return (
    <div className={selected ? "sel-variant sel-variant-on" : "sel-variant"}>
      <button type="button" className="sel-variant-pick" onClick={onPick} aria-pressed={selected}>
        <span className="sel-variant-mod">{variant.mod}</span>
        {variant.detail && <span className="sel-variant-detail">{variant.detail}</span>}
      </button>
    </div>
  );
}

// One conflict, two columns: the default winner on the left, the other variants on
// the right. The selected variant (current winner, default until changed) is lit.
function SelectionCard({
  conflict,
  winner,
  onPick,
}: {
  conflict: SelectionConflict;
  winner: string;
  onPick: (mod: string) => void;
}) {
  const def = conflict.variants.find((v) => v.mod === conflict.defaultMod);
  const others = conflict.variants.filter((v) => v.mod !== conflict.defaultMod);
  return (
    <article className="sel-card">
      <header className="sel-card-head">
        <span className="sel-subject" title={conflict.id}>
          {prettySubject(conflict.id)}
        </span>
        <span className="sel-count">{conflict.variants.length} variants</span>
      </header>
      <div className="sel-cols">
        <div className="sel-col">
          <span className="sel-col-label">By default</span>
          {def && (
            <VariantButton
              variant={def}
              selected={winner === def.mod}
              onPick={() => onPick(def.mod)}
            />
          )}
        </div>
        <div className="sel-col">
          <span className="sel-col-label">Other</span>
          {others.length === 0 ? (
            <span className="note">—</span>
          ) : (
            others.map((v) => (
              <VariantButton
                key={v.mod}
                variant={v}
                selected={winner === v.mod}
                onPick={() => onPick(v.mod)}
              />
            ))
          )}
        </div>
      </div>
    </article>
  );
}

const SELECTION_CARD_ESTIMATE = 160;

// The virtualized stack of selection cards (DOM-limited, like the mod list).
function SelectionCards({
  conflicts,
  winners,
  onPick,
}: {
  conflicts: SelectionConflict[];
  winners: Record<string, string>;
  onPick: (id: string, mod: string) => void;
}) {
  return (
    <VirtualList
      items={conflicts}
      keyOf={(c) => c.id}
      estimate={SELECTION_CARD_ESTIMATE}
      className="sel-list"
      renderItem={(c) => (
        <SelectionCard
          conflict={c}
          winner={winners[c.id] ?? c.defaultMod}
          onPick={(mod) => onPick(c.id, mod)}
        />
      )}
    />
  );
}

// Recipes sub-tab: a selection card per colliding recipe id (each mod's version
// fetched from its jar), then the winner-driven override datapack.
function RecipesResolution({
  conflicts,
  modsPath,
  version,
  winners,
  onPick,
}: {
  conflicts: Conflict[];
  modsPath: string;
  version?: string;
  winners: Record<string, string>;
  onPick: (id: string, mod: string) => void;
}) {
  const hasCollisions = conflicts.some((c) => c.type === "recipe_collision");
  // Seed from the per-pack cache so re-opening the tab is instant (no "reading…").
  const [variants, setVariants] = useState<ResolutionVariants | null>(
    () => peekRecipeVariants(modsPath, version) ?? null,
  );
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!hasCollisions) return;
    const cached = peekRecipeVariants(modsPath, version);
    if (cached) {
      setVariants(cached);
      return;
    }
    let active = true;
    setVariants(null);
    setError(null);
    loadRecipeVariants(modsPath, version)
      .then((v) => active && setVariants(v))
      .catch((e) => active && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      active = false;
    };
  }, [modsPath, version, hasCollisions]);

  const selections = useMemo(() => (variants ? recipeSelections(variants) : []), [variants]);

  if (!hasCollisions) {
    return <p className="note">No recipe collisions — no two mods write the same recipe id.</p>;
  }

  return (
    <>
      <h2 className="resolution-section">Choose the correct recipe</h2>

      {error && <p className="scan-error">{error}</p>}
      {variants === null && !error && <p className="note">Reading recipes…</p>}
      {selections.length > 0 && (
        <SelectionCards conflicts={selections} winners={winners} onPick={onPick} />
      )}
    </>
  );
}

// Tags sub-tab: a selection card per conventional-tag overlap (each mod's items).
function TagsResolution({
  conflicts,
  winners,
  onPick,
}: {
  conflicts: Conflict[];
  winners: Record<string, string>;
  onPick: (id: string, mod: string) => void;
}) {
  const selections = useMemo(() => tagSelections(conflicts), [conflicts]);

  if (selections.length === 0) {
    return (
      <p className="note">No tag overlaps — no conventional tag is fed by more than one mod.</p>
    );
  }

  return (
    <>
      <h2 className="resolution-section">Choose the correct tag</h2>
      <SelectionCards conflicts={selections} winners={winners} onPick={onPick} />
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
  onShowRuntime,
}: {
  verdict: RunVerdict | null;
  modsPath: string;
  version: string;
  loader?: Loader;
  onTest: () => void;
  testing: boolean;
  onShowRuntime: () => void;
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
  // A boot that ran and flagged nothing is not the same as one that never ran —
  // the old single message read as "no test yet" even after a clean pass. Split
  // the three states: never booted, booted clean, booted with a non-dep cause.
  const message: ReactNode = !verdict ? (
    "No missing-dependency verdict yet. A headless boot test detects which dependencies the set is missing; they can then be installed here."
  ) : verdict.status === "ok" ? (
    "The last test ran clean, no missing dependencies to install."
  ) : (
    <>
      The last test flagged no missing dependency. If the set still crashed, its cause is shown
      under{" "}
      <button type="button" className="note-link" onClick={onShowRuntime}>
        Runtime
      </button>
      .
    </>
  );
  return (
    <>
      <p className="note">{message}</p>
      <section className="runner">
        <button className="btn-primary" type="button" onClick={onTest} disabled={testing}>
          {testing ? "Booting…" : verdict ? "Re-run the test" : "Run the test"}
        </button>
      </section>
    </>
  );
}

const RESOLUTION_SUBS: { id: ResolutionSub; label: string }[] = [
  { id: "mixins", label: "Mixins" },
  { id: "recipes", label: "Recipes" },
  { id: "tags", label: "Tags" },
  { id: "apply", label: "Apply" },
  { id: "deps", label: "Deps" },
];

// The Resolution hub: one sub-tab per conflict family, each the single place to
// act on it. Fed by the static scan and refined by the runtime verdict (mixin
// confirmation, the missing-dependency list) when a boot has run.
export function ResolutionView({
  modsPath,
  instanceRoot,
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
  onShowRuntime,
}: {
  modsPath: string;
  instanceRoot: string;
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
  onShowRuntime: () => void;
}) {
  const mixinExports = useMemo(() => (verdict ? new Set(verdict.mixinExports) : null), [verdict]);
  const clusters = useMemo(
    () => groupMixinClusters(conflicts, mods, mixinExports),
    [conflicts, mods, mixinExports],
  );
  // Per-conflict winner picks (subject id -> mod). Held here so they survive
  // sub-tab switches; seeded lazily (an absent pick means "the default").
  const [recipeWinners, setRecipeWinners] = useState<Record<string, string>>({});
  const [tagWinners, setTagWinners] = useState<Record<string, string>>({});
  const pickRecipe = useCallback(
    (id: string, mod: string) => setRecipeWinners((w) => ({ ...w, [id]: mod })),
    [],
  );
  const pickTag = useCallback(
    (id: string, mod: string) => setTagWinners((w) => ({ ...w, [id]: mod })),
    [],
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
        <RecipesResolution
          conflicts={conflicts}
          modsPath={modsPath}
          version={version}
          winners={recipeWinners}
          onPick={pickRecipe}
        />
      )}

      {sub === "tags" && (
        <TagsResolution conflicts={conflicts} winners={tagWinners} onPick={pickTag} />
      )}

      {sub === "apply" && (
        <ApplyResolution
          instanceRoot={instanceRoot}
          modsPath={modsPath}
          version={version}
          loader={loader}
          recipeWinners={recipeWinners}
          tagWinners={tagWinners}
        />
      )}

      {sub === "deps" && (
        <DepsResolution
          verdict={verdict}
          modsPath={modsPath}
          version={version ?? ""}
          loader={loader}
          onTest={onTest}
          testing={testing}
          onShowRuntime={onShowRuntime}
        />
      )}
    </div>
  );
}
