import { useMemo, useState } from "react";
import type {
  BisectResult,
  Conflict,
  ExportResult,
  ResolutionPlan,
  RunVerdict,
  ScanResult,
  Severity,
} from "./lib/api";
import { resolveExport, resolvePreview } from "./lib/api";
import {
  CONFLICT_LABEL,
  conflictKey,
  conflictSubject,
  countBySeverity,
  isRuntimeConfirmed,
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
  verdict,
  onTest,
  testing,
}: { result: ScanResult; verdict: RunVerdict | null } & TestProps) {
  const sev = countBySeverity(result.conflicts);
  return (
    <div className="view">
      {result.detection && (
        <p className="detected">
          Minecraft <strong>{result.profile}</strong>
          {result.detection.block && ` · ${result.detection.block}`}
          {result.detection.status === "confident" ? " · auto-detected" : " · selected"}
          {!result.detection.runnerSupported && " · static-only"}
        </p>
      )}
      <div className="stats">
        <div className="stat">
          <span className="stat-n">{result.counts.mods}</span>
          <span className="stat-l">mods</span>
        </div>
        <div className="stat">
          <span className="stat-n">{result.counts.untestable}</span>
          <span className="stat-l">not testable in server mode</span>
        </div>
        <div className="stat">
          <span className="stat-n">{result.counts.conflicts}</span>
          <span className="stat-l">
            conflicts · {sev.error}E / {sev.warning}W / {sev.info}I
          </span>
        </div>
        <div className="stat">
          <span className="stat-n">{result.counts.errors}</span>
          <span className="stat-l">unreadable jars</span>
        </div>
      </div>

      <section className="runner">
        <TestButton onTest={onTest} testing={testing} />
        {verdict ? (
          <span>
            last verdict{" "}
            <span className={`run-${verdict.status}`}>{verdict.status.toUpperCase()}</span>
          </span>
        ) : (
          <span className="note">
            profile {result.profile} · {result.modsPath}
          </span>
        )}
      </section>
    </div>
  );
}

export function ConflictsView({
  conflicts,
  verdict,
}: {
  conflicts: Conflict[];
  verdict: RunVerdict | null;
}) {
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
        <div className="panel">
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
              {rows.map((c) => (
                <tr key={conflictKey(c)}>
                  <td className={`sev-${c.severity}`}>{c.severity}</td>
                  <td>{CONFLICT_LABEL[c.type]}</td>
                  <td className="subject">
                    {conflictSubject(c)}
                    {isRuntimeConfirmed(c, mixinExports) && (
                      <span className="confirmed"> confirmed at runtime</span>
                    )}
                  </td>
                  <td className="members">{c.members.join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export function ModsView({ result }: { result: ScanResult }) {
  return (
    <div className="view">
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
    </div>
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
