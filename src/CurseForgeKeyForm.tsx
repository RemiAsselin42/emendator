import { useState } from "react";
import { type CurseForgeStatus, setCurseForgeKey } from "./lib/api";

const UNVERIFIED_FALLBACK = "Check the key is correct and you're online.";

// Shared CurseForge key controls, used by both the first-run connect prompt and
// the Settings panel: how-to steps, the key input + Save, an optional Remove
// (Settings only), and a status note. Owns its save/remove network state and
// reports every change up via `onChanged` so the host can refresh its own view.
export function CurseForgeKeyForm({
  status,
  onChanged,
  allowRemove = false,
}: {
  status: CurseForgeStatus | null;
  onChanged: (status: CurseForgeStatus) => void;
  allowRemove?: boolean;
}) {
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState<"save" | "remove" | null>(null);
  const [result, setResult] = useState<CurseForgeStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  // The latest known state: a just-completed action wins over the passed-in status.
  const configured = (result ?? status)?.configured ?? false;

  async function submit(value: string, action: "save" | "remove") {
    if (busy) return;
    setBusy(action);
    setError(null);
    try {
      const next = await setCurseForgeKey(value);
      setResult(next);
      onChanged(next);
      if (action === "remove") setKey("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not update the key.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <ol className="modal-steps">
        <li>
          Open the{" "}
          <a href="https://console.curseforge.com/" target="_blank" rel="noreferrer">
            CurseForge developer console
          </a>{" "}
        </li>
        <li>Log in or sign up</li>
        <li>
          Open <strong>API Keys</strong> and copy your key.
        </li>
        <li>Paste it below and save.</li>
      </ol>
      <input
        className="path-input"
        type="password"
        placeholder={configured ? "Enter a new key to replace it" : "CurseForge API key"}
        value={key}
        onChange={(e) => setKey(e.target.value)}
        spellCheck={false}
      />
      <KeyNote result={result} error={error} configured={configured} />
      <div className="modal-actions">
        {allowRemove && configured && (
          <button
            type="button"
            className="btn-secondary btn-danger"
            onClick={() => void submit("", "remove")}
            disabled={busy !== null}
          >
            {busy === "remove" ? "Removing…" : "Remove key"}
          </button>
        )}
        <button
          type="button"
          className="btn-primary"
          onClick={() => void submit(key.trim(), "save")}
          disabled={busy !== null || !key.trim()}
        >
          {busy === "save" ? "Saving…" : configured ? "Replace key" : "Save key"}
        </button>
      </div>
    </>
  );
}

function KeyNote({
  result,
  error,
  configured,
}: {
  result: CurseForgeStatus | null;
  error: string | null;
  configured: boolean;
}) {
  if (error) return <p className="modal-note modal-note-warn">{error}</p>;
  if (result) {
    if (!result.configured) return <p className="modal-note note-ok">Key removed.</p>;
    if (result.valid) {
      return <p className="modal-note note-ok">CurseForge is connected.</p>;
    }
    return (
      <p className="modal-note modal-note-warn">
        {`Key saved, but it couldn't be verified. ${result.detail ?? UNVERIFIED_FALLBACK}`}
      </p>
    );
  }
  if (configured)
    return <p className="modal-note note-ok">A CurseForge key is already configured.</p>;
  return null;
}
