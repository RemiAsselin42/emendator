import { useCallback, useEffect, useState } from "react";
import {
  type Conflict,
  fetchHealth,
  type HealthResponse,
  type ScanResult,
  scanMods,
} from "./lib/api";

const CONFLICT_LABEL: Record<Conflict["type"], string> = {
  duplicate_jar: "duplicate jar",
  dependency: "dependency",
  tag_overlap: "tag overlap",
  recipe_collision: "recipe collision",
  mixin_overlap: "mixin overlap",
};

// One-line subject for a conflict row, by type.
function conflictSubject(c: Conflict): string {
  const d = c.detail;
  switch (c.type) {
    case "duplicate_jar":
      return String(d.modId ?? "");
    case "dependency":
      return `missing ${String(d.missing ?? "")}`;
    case "tag_overlap":
      return String(d.tag ?? "");
    case "recipe_collision":
      return String(d.recipe ?? "");
    case "mixin_overlap":
      return String(d.target ?? "");
  }
}

export default function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [path, setPath] = useState("");
  const [result, setResult] = useState<ScanResult | null>(null);
  const [scanning, setScanning] = useState(false);
  const [scanError, setScanError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

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
    try {
      setResult(await scanMods(trimmed));
    } catch (e) {
      setScanError(e instanceof Error ? e.message : String(e));
      setResult(null);
    } finally {
      setScanning(false);
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

  return (
    <main className="container">
      <header className="header">
        <h1>Emendator</h1>
        <p className="tagline">Fabric modpack conflict analyzer</p>
      </header>

      <p className="health">
        {health ? (
          <span className="up">backend up · profile {health.profile}</span>
        ) : (
          <span className="down">backend unreachable — start the sidecar</span>
        )}
      </p>

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
            placeholder="C:\Users\…\mods"
            value={path}
            onChange={(e) => setPath(e.target.value)}
            spellCheck={false}
          />
          <button className="btn-primary" type="submit" disabled={scanning || !path.trim()}>
            {scanning ? "scanning…" : "Scan"}
          </button>
        </form>
      </section>

      {scanError && <p className="scan-error">scan failed: {scanError}</p>}

      {result && (
        <>
          <div className="summary">
            <span>
              <span className="count">{result.counts.mods}</span> mods
            </span>
            <span className="untestable">
              <span className="count">{result.counts.untestable}</span> not testable in server mode
            </span>
            <span>
              <span className="count">{result.counts.conflicts}</span> conflicts
            </span>
            {result.counts.errors > 0 && (
              <span>
                <span className="count">{result.counts.errors}</span> unreadable jars
              </span>
            )}
          </div>

          {result.conflicts.length > 0 && (
            <div className="panel">
              <h2 className="panel-title">Conflicts</h2>
              <table className="conflicts-table">
                <thead>
                  <tr>
                    <th>severity</th>
                    <th>type</th>
                    <th>subject</th>
                    <th>mods</th>
                  </tr>
                </thead>
                <tbody>
                  {result.conflicts.map((c) => (
                    <tr key={`${c.type}-${conflictSubject(c)}-${c.members.join(",")}`}>
                      <td className={`sev-${c.severity}`}>{c.severity}</td>
                      <td>{CONFLICT_LABEL[c.type]}</td>
                      <td className="subject">{conflictSubject(c)}</td>
                      <td className="members">
                        {c.members.join(", ")}
                        {c.type === "mixin_overlap" && " · confirm at runtime"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {result.mods.length > 0 && (
            <div className="panel">
              <table className="mods-table">
                <thead>
                  <tr>
                    <th>id</th>
                    <th>version</th>
                    <th>mc</th>
                    <th>env</th>
                    <th>jar</th>
                  </tr>
                </thead>
                <tbody>
                  {result.mods.map((mod) => (
                    <tr key={mod.jar}>
                      <td>{mod.id}</td>
                      <td>{mod.version ?? "—"}</td>
                      <td>{mod.mcVersion ?? "—"}</td>
                      <td className={mod.environment === "client" ? "env-client" : undefined}>
                        {mod.environment}
                      </td>
                      <td>{mod.jar}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {result.counts.untestable > 0 && (
            <p className="note">
              {result.counts.untestable} client-only mod(s) are not loaded by a headless server and
              cannot be tested at runtime (see PROJECT.md §5).
            </p>
          )}

          {result.errors.length > 0 && (
            <ul className="errors">
              {result.errors.map((err) => (
                <li key={err.jar}>
                  {err.jar}: {err.reason}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </main>
  );
}
