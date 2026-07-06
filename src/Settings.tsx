import { useEffect, useState } from "react";
import { CurseForgeKeyForm } from "./CurseForgeKeyForm";
import type { CurseForgeStatus } from "./lib/api";
import { getAnthropicStatus, setAnthropicKey } from "./lib/api";

// Always-available settings, reached from the gear in the top-right corner. Today
// it manages the CurseForge API key (add / replace / remove); status is owned by
// the host (App) so changes here also update the connect prompt.
export function Settings({
  status,
  onChanged,
}: {
  status: CurseForgeStatus | null;
  onChanged: (status: CurseForgeStatus) => void;
}) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button
        type="button"
        className="settings-fab"
        aria-label="Settings"
        onClick={() => setOpen(true)}
      >
        <GearIcon />
      </button>
      {open && (
        <div className="modal-overlay" role="dialog" aria-modal="true" aria-label="Settings">
          <div className="modal">
            <button
              type="button"
              className="modal-close"
              aria-label="Close"
              onClick={() => setOpen(false)}
            >
              <CloseIcon />
            </button>
            <h2 className="modal-title">Settings</h2>
            <section className="settings-section">
              <h3 className="settings-heading">CurseForge API key</h3>
              <p className="modal-body">
                Lets Emendator install a missing mod from CurseForge when Modrinth has no match.
                Free, and stored locally on this machine.
              </p>
              <CurseForgeKeyForm status={status} onChanged={onChanged} allowRemove />
            </section>
            <section className="settings-section">
              <h3 className="settings-heading">Anthropic API key (AI fix)</h3>
              <p className="modal-body">
                Your own key from console.anthropic.com — enables the "Fix with AI" loop in the
                mixin resolver. Requests go directly to Anthropic and each fix loop typically costs
                well under a dollar; the key is stored locally on this machine.
              </p>
              <AnthropicKeyForm />
            </section>
          </div>
        </div>
      )}
    </>
  );
}

// Add / replace / remove the BYO Anthropic key; status is self-contained (the
// key gates only the AI fix loop, nothing else in the app watches it).
function AnthropicKeyForm() {
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getAnthropicStatus()
      .then((s) => setConfigured(s.configured))
      .catch(() => setConfigured(null));
  }, []);

  const save = async (key: string) => {
    setBusy(true);
    setError(null);
    try {
      const s = await setAnthropicKey(key);
      setConfigured(s.configured);
      setValue("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      className="key-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (value.trim()) void save(value);
      }}
    >
      <input
        type="password"
        className="key-input"
        placeholder={configured ? "Configured — paste to replace" : "sk-ant-…"}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        disabled={busy}
      />
      <button type="submit" className="btn-primary no-wrap" disabled={busy || !value.trim()}>
        {busy ? "Saving…" : "Save"}
      </button>
      {configured && (
        <button
          type="button"
          className="btn-secondary no-wrap"
          onClick={() => void save("")}
          disabled={busy}
        >
          Remove
        </button>
      )}
      {error && <span className="note run-error">{error}</span>}
    </form>
  );
}

// A sliders glyph, in the codebase's 16×16 stroke style — reads as "settings".
function GearIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 16 16" aria-hidden="true">
      <path
        d="M2 4.5h6M11.5 4.5h2.5M2 11.5h2.5M8 11.5h6"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
      />
      <circle cx="9.5" cy="4.5" r="1.7" fill="none" stroke="currentColor" strokeWidth="1.4" />
      <circle cx="6" cy="11.5" r="1.7" fill="none" stroke="currentColor" strokeWidth="1.4" />
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg width="26" height="26" viewBox="0 0 16 16" aria-hidden="true">
      <path
        d="M4 4l8 8M12 4l-8 8"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
      />
    </svg>
  );
}
