import { type SyntheticEvent, useState } from "react";

// A mutually-exclusive group of native `<details>`: opening one closes the others.
// Spread `item(key)` onto each `<details>` — it returns the `open`/`onToggle` props
// that drive the disclosure from shared state, so the native summary still toggles
// it (no extra wiring). Pass the key to open initially, or omit for all-closed.
//
// Controlled, but the native toggle leads: clicking a summary flips that element's
// `open`, `onToggle` mirrors it into state, and the re-render closes the previous
// one. Collapsing the open panel clears the group. Programmatically closing a
// sibling (when another opens) fires its toggle with `open === false`, which must
// not clobber the freshly-selected key — hence the `k === key` guard.
export function useAccordion(initialOpen?: string) {
  const [openKey, setOpenKey] = useState<string | null>(initialOpen ?? null);

  function item(key: string) {
    return {
      open: openKey === key,
      onToggle: (event: SyntheticEvent<HTMLDetailsElement>) => {
        if (event.currentTarget.open) setOpenKey(key);
        else setOpenKey((k) => (k === key ? null : k));
      },
    };
  }

  return { openKey, item };
}
