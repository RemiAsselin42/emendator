import { useState } from "react";
import type { Conflict, RunVerdict, ScanResult, Severity } from "./lib/api";
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

function TestButton({ onTest, testing }: TestProps) {
  return (
    <button className="btn-primary" type="button" onClick={onTest} disabled={testing}>
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
                    {isRuntimeConfirmed(c, verdict) && (
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

export function RuntimeView({
  verdict,
  onTest,
  testing,
}: { verdict: RunVerdict | null } & TestProps) {
  return (
    <div className="view">
      <section className="runner">
        <TestButton onTest={onTest} testing={testing} />
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

      <p className="note">
        Bisection (Phase 3) will isolate the guilty pair here when a boot crashes.
      </p>
    </div>
  );
}
