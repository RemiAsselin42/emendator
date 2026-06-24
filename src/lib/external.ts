import { invoke, isTauri } from "@tauri-apps/api/core";
import { useEffect } from "react";

// Open a URL in the user's real browser. Inside the Tauri webview a plain
// `target="_blank"` (or any external navigation) is swallowed — the webview has no
// browser chrome and won't spawn an OS browser — so route it through the shell
// plugin's `open` instead. Outside Tauri (dev in a browser, tests) fall back to
// the native new-tab behaviour.
export async function openExternal(url: string): Promise<void> {
  if (isTauri()) {
    await invoke("plugin:shell|open", { path: url });
    return;
  }
  window.open(url, "_blank", "noopener,noreferrer");
}

// Delegate every external (http/https) link click to {@link openExternal} when
// running inside Tauri, so existing `<a target="_blank">` markup keeps working
// without each call site knowing about the webview. A no-op in a real browser,
// where anchors navigate natively.
export function useExternalLinks(): void {
  useEffect(() => {
    if (!isTauri()) return;
    function onClick(event: MouseEvent) {
      if (event.defaultPrevented || event.button !== 0) return;
      const anchor = (event.target as Element | null)?.closest?.(
        "a[href]",
      ) as HTMLAnchorElement | null;
      if (!anchor) return;
      if (!/^https?:\/\//i.test(anchor.getAttribute("href") ?? "")) return;
      event.preventDefault();
      void openExternal(anchor.href);
    }
    document.addEventListener("click", onClick);
    return () => document.removeEventListener("click", onClick);
  }, []);
}
