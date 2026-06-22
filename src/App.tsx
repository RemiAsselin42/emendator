import { useCallback, useEffect, useState } from "react";
import {
  AmbiguousVersionError,
  type BisectResult,
  bisectSet,
  detectInstance,
  discoverInstances,
  fetchHealth,
  type Instance,
  type InstanceReport,
  listProfiles,
  type RunVerdict,
  type ScanResult,
  scanInstance,
  testSet,
  type VersionCandidate,
  type VersionDetection,
} from "./lib/api";
import { isRecipeCollision } from "./lib/conflicts";
import {
  ConflictsView,
  DatapacksView,
  ItemsView,
  Overview,
  RecipesView,
  ResolutionView,
  ResourcePacksView,
  RuntimeView,
  ShadersView,
} from "./views";

type Tab =
  | "scan"
  | "overview"
  | "conflicts"
  | "recipes"
  | "runtime"
  | "resolution"
  | "resourcepacks"
  | "datapacks"
  | "shaders"
  | "items";

const TABS: { id: Tab; label: string }[] = [
  { id: "scan", label: "Scan" },
  { id: "overview", label: "Overview" },
  { id: "conflicts", label: "Conflicts" },
  { id: "recipes", label: "Recipes" },
  { id: "runtime", label: "Runtime" },
  { id: "resolution", label: "Resolution" },
];

// How each detected source reads in the badge; raw_mods is the bare folder input.
const SOURCE_LABEL: Record<Instance["source"], string> = {
  curseforge: "CurseForge",
  modrinth: "Modrinth",
  prism: "Prism",
  multimc: "MultiMC",
  vanilla: ".minecraft",
  raw_mods: "mods folder",
};

// Header chip summarising the resolved instance: source, name, loader, version
// and the content counts that hint at what's beyond the mods themselves.
function InstanceBadge({ instance }: { instance: Instance }) {
  const counts: string[] = [`${instance.modCount} mods`];
  if (instance.resourcepackCount > 0) counts.push(`${instance.resourcepackCount} resourcepacks`);
  if (instance.datapackCount > 0) counts.push(`${instance.datapackCount} datapacks`);
  if (instance.shaderpackCount > 0) counts.push(`${instance.shaderpackCount} shaders`);
  return (
    <div className={`instance-badge source-${instance.source}`}>
      <span className="instance-source">{SOURCE_LABEL[instance.source]}</span>
      {instance.name && <span className="instance-name">{instance.name}</span>}
      {instance.loader !== "unknown" && <span className="instance-loader">{instance.loader}</span>}
      {instance.mcVersion && <span className="instance-mc">{instance.mcVersion}</span>}
      <span className="instance-counts">{counts.join(" · ")}</span>
    </div>
  );
}

export default function App() {
  // Only true once a health check has actually failed — stays false during the
  // first in-flight check so the "unreachable" toast never flashes on boot.
  const [backendDown, setBackendDown] = useState(false);
  const [path, setPath] = useState("");
  const [result, setResult] = useState<ScanResult | null>(null);
  // The full instance report (mods + content packs); `result` mirrors its `mods`
  // slice so the conflict-map views are unchanged.
  const [report, setReport] = useState<InstanceReport | null>(null);
  // The launcher instance the dropped path resolved to (CurseForge/Modrinth/…),
  // shown as a badge; null until detected, best-effort (never blocks a scan).
  const [instance, setInstance] = useState<Instance | null>(null);
  const [scanning, setScanning] = useState(false);
  const [scanError, setScanError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [verdict, setVerdict] = useState<RunVerdict | null>(null);
  const [testing, setTesting] = useState(false);
  const [bisectResult, setBisectResult] = useState<BisectResult | null>(null);
  const [bisecting, setBisecting] = useState(false);
  const [tab, setTab] = useState<Tab>("scan");
  // The exact version used for the current scan (auto-detected or user-picked);
  // threaded into runtime/resolve so they boot/generate for the right version.
  const [version, setVersion] = useState<string | null>(null);
  // Set when a scan is rejected as ambiguous (§6): drives the version picker.
  const [pendingDetection, setPendingDetection] = useState<VersionDetection | null>(null);
  // Version blocks offered in the manual override (§6).
  const [profiles, setProfiles] = useState<VersionCandidate[]>([]);
  // Modpacks auto-discovered from installed launchers (quick-select).
  const [discovered, setDiscovered] = useState<Instance[]>([]);
  // Jars updated in place this session. Lives here (not in the mods panel) so the
  // "to update" count survives leaving and re-entering that panel; every scan
  // replaces result.mods with fresh updateAvailable flags, so we clear it then.
  const [updatedJars, setUpdatedJars] = useState<Set<string>>(new Set());
  const markUpdated = useCallback(
    (jar: string) => setUpdatedJars((prev) => (prev.has(jar) ? prev : new Set(prev).add(jar))),
    [],
  );

  // Poll the sidecar so the toast reflects the live state: it appears when a
  // check fails and clears itself when the backend comes back.
  useEffect(() => {
    let active = true;
    const check = () => {
      fetchHealth()
        .then(() => active && setBackendDown(false))
        .catch(() => active && setBackendDown(true));
    };
    check();
    const id = window.setInterval(check, 5000);
    return () => {
      active = false;
      window.clearInterval(id);
    };
  }, []);

  useEffect(() => {
    listProfiles()
      .then((p) => setProfiles(Array.isArray(p) ? p : []))
      .catch(() => setProfiles([]));
  }, []);

  // Discover installed modpacks once, for the quick-select list (best-effort).
  useEffect(() => {
    discoverInstances()
      .then((list) => setDiscovered(Array.isArray(list) ? list : []))
      .catch(() => setDiscovered([]));
  }, []);

  // `pick` is the user's manual version choice from the ambiguity picker; when
  // absent the backend auto-detects (and rejects an ambiguous set with 409).
  const runScan = useCallback(async (target: string, pick?: string) => {
    const trimmed = target.trim();
    if (!trimmed) return;
    setScanning(true);
    setScanError(null);
    setPendingDetection(null);
    setVerdict(null);
    setBisectResult(null);
    // Best-effort, in parallel: never blocks or fails the scan, just feeds the
    // header badge (pack name, source, loader, content counts).
    void detectInstance(trimmed)
      .then(setInstance)
      .catch(() => setInstance(null));
    try {
      const scanReport = await scanInstance(trimmed, pick);
      setReport(scanReport);
      setResult(scanReport.mods);
      setUpdatedJars(new Set());
      setInstance(scanReport.instance);
      setVersion(scanReport.mods.profile);
      setTab("overview");
    } catch (e) {
      setResult(null);
      setReport(null);
      setTab("scan");
      if (e instanceof AmbiguousVersionError) {
        setPendingDetection(e.detection);
      } else {
        setScanError(e instanceof Error ? e.message : String(e));
      }
    } finally {
      setScanning(false);
    }
  }, []);

  const runTest = useCallback(
    async (target: string) => {
      setTesting(true);
      setVerdict(null);
      try {
        setVerdict(await testSet(target, version ?? undefined));
      } catch (e) {
        setVerdict({
          status: "error",
          profile: "",
          durationMs: 0,
          cause: {
            category: "startup_error",
            summary: e instanceof Error ? e.message : String(e),
            mods: [],
            excerpt: null,
          },
          mixinExports: [],
          logTail: null,
        });
      } finally {
        setTesting(false);
      }
    },
    [version],
  );

  // Native folder drop, Tauri only. In plain browser dev the internals are
  // absent and we fall back to the path input below.
  useEffect(() => {
    if (typeof window === "undefined" || !("__TAURI_INTERNALS__" in window)) return;
    let unlisten: (() => void) | undefined;
    import("@tauri-apps/api/webview")
      .then(({ getCurrentWebview }) =>
        getCurrentWebview().onDragDropEvent((event) => {
          const p = event.payload;
          if (p.type === "enter" || p.type === "over") {
            setDragging(true);
          } else if (p.type === "leave") {
            setDragging(false);
          } else if (p.type === "drop") {
            setDragging(false);
            const dropped = p.paths[0];
            if (dropped) {
              setPath(dropped);
              void runScan(dropped);
            }
          }
        }),
      )
      .then((u) => {
        unlisten = u;
      })
      .catch(() => {});
    return () => unlisten?.();
  }, [runScan]);

  const runBisect = useCallback(
    async (target: string) => {
      setBisecting(true);
      setBisectResult(null);
      try {
        setBisectResult(await bisectSet(target, version ?? undefined));
      } catch (e) {
        setBisectResult({
          status: "error",
          profile: "",
          members: [],
          boots: 0,
          durationMs: 0,
          cause: null,
          note: e instanceof Error ? e.message : String(e),
        });
      } finally {
        setBisecting(false);
      }
    },
    [version],
  );

  const onTest = useCallback(() => {
    if (result) void runTest(result.modsPath);
  }, [result, runTest]);

  const onBisect = useCallback(() => {
    if (result) void runBisect(result.modsPath);
  }, [result, runBisect]);

  // Options for the version selector: every block's representative plus the
  // exact detected/used version (which may sit between reps, e.g. 1.21.4),
  // deduped. `version` drives the selection, so the detected one shows selected.
  const versionOptions = profiles.map((p) => ({
    value: p.version,
    label: `${p.version} · ${p.block}`,
  }));
  if (version && !versionOptions.some((o) => o.value === version)) {
    const block = result?.detection?.block;
    versionOptions.unshift({
      value: version,
      label: block ? `${version} · ${block}` : version,
    });
  }

  // Recipe collisions moved to their own tab, so the Conflicts badge counts only
  // what that tab still shows.
  const recipeCount = result ? result.conflicts.filter(isRecipeCollision).length : 0;
  const conflictCount = result ? result.counts.conflicts - recipeCount : 0;

  // Content tabs appear only when the instance actually has that content, so a
  // bare mods folder keeps the original layout.
  const contentTabs: { id: Tab; label: string; count: number }[] = [];
  if (report) {
    if (report.resourcepacks.length > 0)
      contentTabs.push({
        id: "resourcepacks",
        label: "Resource Packs",
        count: report.resourcepacks.length,
      });
    if (report.datapacks.length > 0)
      contentTabs.push({
        id: "datapacks",
        label: "Datapacks",
        count: report.datapacks.length,
      });
    if (report.shaderpacks.length > 0)
      contentTabs.push({
        id: "shaders",
        label: "Shaders",
        count: report.shaderpacks.length,
      });
    if (report.items.total > 0)
      contentTabs.push({
        id: "items",
        label: "Items",
        count: report.items.total,
      });
  }

  return (
    <main className="container">
      <header className="header">
        <h1>Emendator</h1>
        <p className="tagline">Minecraft modpack conflict analyzer</p>

        {instance && result && <InstanceBadge instance={instance} />}

        {result && (
          <div className="version-bar">
            <label className="mc-version">
              <select
                value={version ?? ""}
                disabled={scanning}
                onChange={(e) => {
                  const pick = e.target.value;
                  if (pick) void runScan(result.modsPath, pick);
                }}
              >
                {versionOptions.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
            {result.detection && (
              <span className="note">
                {result.detection.status === "confident" ? "auto-detected" : "selected"}
                {!result.detection.runnerSupported && " · runtime not yet available"}
              </span>
            )}
          </div>
        )}
      </header>

      {/* Before the first scan there's nothing to navigate — show only the import
          panel; the sidebar appears once a scan produces a result. */}
      <div className={result ? "layout" : "layout layout-solo"}>
        {result && (
          <nav className="sidebar" aria-label="panels">
            {TABS.map((t) => (
              <button
                key={t.id}
                type="button"
                className={tab === t.id ? "nav-item nav-item-active" : "nav-item"}
                onClick={() => setTab(t.id)}
              >
                {t.label}
                {t.id === "conflicts" && ` (${conflictCount})`}
                {t.id === "recipes" && ` (${recipeCount})`}
              </button>
            ))}
            {contentTabs.map((t) => (
              <button
                key={t.id}
                type="button"
                className={tab === t.id ? "nav-item nav-item-active" : "nav-item"}
                onClick={() => setTab(t.id)}
              >
                {t.label} ({t.count})
              </button>
            ))}
          </nav>
        )}

        <div className="content">
          {tab === "scan" && (
            <section
              className={dragging ? "dropzone dragging" : "dropzone"}
              aria-label="modpack folder drop target"
            >
              <p>
                Drop a modpack instance (CurseForge, Modrinth, Prism…) or a bare <code>mods/</code>{" "}
                folder here, or paste its path.
              </p>
              <form
                className="dropzone-form"
                onSubmit={(e) => {
                  e.preventDefault();
                  void runScan(path);
                }}
              >
                <input
                  className="path-input"
                  type="text"
                  placeholder="C:\\Users\\…\\mods"
                  value={path}
                  onChange={(e) => setPath(e.target.value)}
                  spellCheck={false}
                />
                <button className="btn-primary" type="submit" disabled={scanning || !path.trim()}>
                  {scanning ? "scanning…" : "Scan"}
                </button>
              </form>
            </section>
          )}

          {tab === "scan" && discovered.length > 0 && (
            <section className="quick-select" aria-label="installed modpacks">
              <h2 className="quick-title">Quick select</h2>
              <p className="note">Modpacks found on this PC</p>
              <div className="quick-list">
                {discovered.map((inst) => (
                  <button
                    key={inst.root}
                    type="button"
                    className="quick-card"
                    disabled={scanning}
                    onClick={() => {
                      setPath(inst.root);
                      void runScan(inst.root);
                    }}
                  >
                    <span className="quick-card-head">
                      <span className="quick-name">{inst.name ?? inst.root}</span>
                      <span className="quick-source">{SOURCE_LABEL[inst.source]}</span>
                    </span>
                    <span className="quick-meta">
                      {inst.loader !== "unknown" && (
                        <span className="quick-loader">{inst.loader}</span>
                      )}
                      {inst.mcVersion && <span>{inst.mcVersion}</span>}
                      <span>{inst.modCount} mods</span>
                    </span>
                  </button>
                ))}
              </div>
            </section>
          )}

          {tab === "scan" && pendingDetection && (
            <section className="version-picker" aria-label="pick Minecraft version">
              <p className="scan-error">
                Couldn't pin the Minecraft version automatically
                {pendingDetection.candidates.length > 0 ? ", these mods don't agree on one." : "."}{" "}
                Pick the target to scan:
              </p>
              <div className="picker-options">
                {pendingDetection.candidates.map((c) => (
                  <button
                    key={c.block}
                    type="button"
                    className="btn-primary"
                    disabled={scanning}
                    onClick={() => void runScan(path, c.version)}
                  >
                    {c.block} · {c.version} ({c.modCount} mod
                    {c.modCount === 1 ? "" : "s"})
                  </button>
                ))}
              </div>
              {pendingDetection.outliers.length > 0 && (
                <p className="note">
                  incompatible at the newest target: {pendingDetection.outliers.join(", ")}
                </p>
              )}
            </section>
          )}

          {scanError && <p className="scan-error">scan failed: {scanError}</p>}

          {result && tab !== "scan" && (
            <div className="panel-content">
              {tab === "overview" && (
                <Overview result={result} updatedJars={updatedJars} onUpdated={markUpdated} />
              )}
              {tab === "conflicts" && (
                <ConflictsView conflicts={result.conflicts} verdict={verdict} />
              )}
              {tab === "recipes" && <RecipesView conflicts={result.conflicts} />}
              {tab === "runtime" && (
                <RuntimeView
                  verdict={verdict}
                  onTest={onTest}
                  testing={testing}
                  onBisect={onBisect}
                  bisecting={bisecting}
                  bisectResult={bisectResult}
                  runnerSupported={result.detection?.runnerSupported ?? true}
                  block={result.detection?.block ?? null}
                  modsPath={result.modsPath}
                  version={version ?? result.profile}
                  loader={instance?.loader}
                />
              )}
              {tab === "resolution" && (
                <ResolutionView modsPath={result.modsPath} version={version ?? undefined} />
              )}
              {tab === "resourcepacks" && report && (
                <ResourcePacksView
                  packs={report.resourcepacks}
                  conflicts={report.resourcepackConflicts}
                />
              )}
              {tab === "datapacks" && report && (
                <DatapacksView packs={report.datapacks} conflicts={report.datapackConflicts} />
              )}
              {tab === "shaders" && report && <ShadersView packs={report.shaderpacks} />}
              {tab === "items" && report && <ItemsView index={report.items} />}
            </div>
          )}
        </div>
      </div>

      {backendDown && (
        <div className="toast toast-error" role="alert">
          <span className="toast-title">Backend unreachable</span>
          <span className="toast-body">start the sidecar — retrying…</span>
        </div>
      )}
    </main>
  );
}
