import { useState } from "react";
import { CurseForgeKeyForm } from "./CurseForgeKeyForm";
import type { CurseForgeStatus } from "./lib/api";

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
          </div>
        </div>
      )}
    </>
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
