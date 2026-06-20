import { useCallback, useEffect, useState } from "react";
import {
  AmbiguousVersionError,
  type BisectResult,
  bisectSet,
  fetchHealth,
  type HealthResponse,
  listProfiles,
  type RunVerdict,
  type ScanResult,
  scanMods,
  testSet,
  type VersionCandidate,
  type VersionDetection,
} from "./lib/api";
import { ConflictsView, ModsView, Overview, ResolutionView, RuntimeView } from "./views";

type Tab = "scan" | "overview" | "conflicts" | "mods" | "runtime" | "resolution";

const TABS: { id: Tab; label: string }[] = [
  { id: "scan", label: "Scan" },
  { id: "overview", label: "Overview" },
  { id: "conflicts", label: "Conflicts" },
  { id: "mods", label: "Mods" },
  { id: "runtime", label: "Runtime" },
  { id: "resolution", label: "Resolution" },
];

export default function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [path, setPath] = useState("");
  const [result, setResult] = useState<ScanResult | null>(null);
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

  useEffect(() => {
    fetchHealth()
      .then(setHealth)
      .catch(() => setHealth(null));
    listProfiles()
      .then((p) => setProfiles(Array.isArray(p) ? p : []))
      .catch(() => setProfiles([]));
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
    try {
      const scan = await scanMods(trimmed, pick);
      setResult(scan);
      setVersion(scan.profile);
      setTab("overview");
    } catch (e) {
      setResult(null);
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
    versionOptions.unshift({ value: version, label: block ? `${version} · ${block}` : version });
  }

  return (
    <main className="container">
      <header className="header">
        <h1>Emendator</h1>
        <p className="tagline">Fabric modpack conflict analyzer</p>
        <p className="health">
          {health ? (
            <span className="up">backend up</span>
          ) : (
            <span className="down">backend unreachable — start the sidecar</span>
          )}
        </p>

        {result && (
          <div className="version-bar">
            <label className="mc-version">
              Minecraft version
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

      <div className="layout">
        <nav className="sidebar" aria-label="panels">
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              className={tab === t.id ? "nav-item nav-item-active" : "nav-item"}
              onClick={() => setTab(t.id)}
              disabled={t.id !== "scan" && !result}
            >
              {t.label}
              {result && t.id === "conflicts" && ` (${result.counts.conflicts})`}
              {result && t.id === "mods" && ` (${result.counts.mods})`}
            </button>
          ))}
        </nav>

        <div className="content">
          {tab === "scan" && (
            <section
              className={dragging ? "dropzone dragging" : "dropzone"}
              aria-label="mods folder drop target"
            >
              <p>
                Drop your modpack's <code>mods/</code> folder here, or paste its path.
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

          {tab === "scan" && pendingDetection && (
            <section className="version-picker" aria-label="pick Minecraft version">
              <p className="scan-error">
                Couldn't pin the Minecraft version automatically
                {pendingDetection.candidates.length > 0 ? " — these mods don't agree on one." : "."}{" "}
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
                    {c.block} · {c.version} ({c.modCount} mod{c.modCount === 1 ? "" : "s"})
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
                <Overview result={result} verdict={verdict} onTest={onTest} testing={testing} />
              )}
              {tab === "conflicts" && (
                <ConflictsView conflicts={result.conflicts} verdict={verdict} />
              )}
              {tab === "mods" && <ModsView result={result} />}
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
                />
              )}
              {tab === "resolution" && (
                <ResolutionView modsPath={result.modsPath} version={version ?? undefined} />
              )}
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
