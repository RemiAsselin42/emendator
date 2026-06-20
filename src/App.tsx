import { useCallback, useEffect, useState } from "react";
import {
  type BisectResult,
  bisectSet,
  fetchHealth,
  type HealthResponse,
  type RunVerdict,
  type ScanResult,
  scanMods,
  testSet,
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

  useEffect(() => {
    fetchHealth()
      .then(setHealth)
      .catch(() => setHealth(null));
  }, []);

  const runScan = useCallback(async (target: string) => {
    const trimmed = target.trim();
    if (!trimmed) return;
    setScanning(true);
    setScanError(null);
    setVerdict(null);
    setBisectResult(null);
    try {
      setResult(await scanMods(trimmed));
      setTab("overview");
    } catch (e) {
      setScanError(e instanceof Error ? e.message : String(e));
      setResult(null);
      setTab("scan");
    } finally {
      setScanning(false);
    }
  }, []);

  const runTest = useCallback(async (target: string) => {
    setTesting(true);
    setVerdict(null);
    try {
      setVerdict(await testSet(target));
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
  }, []);

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

  const runBisect = useCallback(async (target: string) => {
    setBisecting(true);
    setBisectResult(null);
    try {
      setBisectResult(await bisectSet(target));
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
  }, []);

  const onTest = useCallback(() => {
    if (result) void runTest(result.modsPath);
  }, [result, runTest]);

  const onBisect = useCallback(() => {
    if (result) void runBisect(result.modsPath);
  }, [result, runBisect]);

  return (
    <main className="container">
      <header className="header">
        <h1>Emendator</h1>
        <p className="tagline">Fabric modpack conflict analyzer</p>
        <p className="health">
          {health ? (
            <span className="up">backend up · profile {health.profile}</span>
          ) : (
            <span className="down">backend unreachable — start the sidecar</span>
          )}
        </p>
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
                />
              )}
              {tab === "resolution" && <ResolutionView modsPath={result.modsPath} />}
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
