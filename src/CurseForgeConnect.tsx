import { useState } from "react";
import { CurseForgeKeyForm } from "./CurseForgeKeyForm";
import type { CurseForgeStatus } from "./lib/api";

// Remembers a permanent dismissal of the connect prompt ("Don't show this again").
const DISMISS_KEY = "emendator.curseforgeBannerDismissed";

// Fixed corner prompt shown when no CurseForge key is set (and the user hasn't
// dismissed it for good). Clicking opens the connect modal; the key itself can
// always be changed later from Settings. Status is owned by the host (App) so the
// prompt and Settings stay in sync — saving a key anywhere hides this at once.
export function CurseForgeConnect({
  status,
  onChanged,
}: {
  status: CurseForgeStatus | null;
  onChanged: (status: CurseForgeStatus) => void;
}) {
  const [dismissed, setDismissed] = useState(() => localStorage.getItem(DISMISS_KEY) === "1");
  const [open, setOpen] = useState(false);

  const needsKey = status != null && !status.configured;

  function dontShowAgain() {
    localStorage.setItem(DISMISS_KEY, "1");
    setDismissed(true);
    setOpen(false);
  }

  return (
    <>
      {needsKey && !dismissed && !open && (
        <button type="button" className="toast toast-cta" onClick={() => setOpen(true)}>
          <span className="toast-title toast-title-cta">Connect CurseForge</span>
          <span className="toast-body">
            Add a free API key so missing mods can install from CurseForge when Modrinth has no
            match. Click to set it up.
          </span>
        </button>
      )}
      {open && (
        <div
          className="modal-overlay"
          role="dialog"
          aria-modal="true"
          aria-label="Connect CurseForge"
        >
          <div className="modal">
            <h2 className="modal-title">Connect CurseForge</h2>
            <p className="modal-body">
              When a missing dependency isn't on Modrinth, Emendator can fetch it from CurseForge
              instead. That needs a personal API key — it's free:
            </p>
            <CurseForgeKeyForm status={status} onChanged={onChanged} />
            <div className="modal-actions">
              <button type="button" className="btn-secondary" onClick={() => setOpen(false)}>
                {status?.configured ? "Done" : "Maybe later"}
              </button>
            </div>
            <button type="button" className="modal-dismiss" onClick={dontShowAgain}>
              Don't show this again
            </button>
          </div>
        </div>
      )}
    </>
  );
}
