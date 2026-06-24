import { invoke, isTauri } from "@tauri-apps/api/core";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { openExternal } from "./external";

vi.mock("@tauri-apps/api/core", () => ({
  isTauri: vi.fn(),
  invoke: vi.fn(),
}));

describe("openExternal", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.restoreAllMocks());

  it("routes through the shell plugin inside Tauri", async () => {
    vi.mocked(isTauri).mockReturnValue(true);
    const openSpy = vi.spyOn(window, "open").mockReturnValue(null);
    await openExternal("https://example.com");
    expect(invoke).toHaveBeenCalledWith("plugin:shell|open", { path: "https://example.com" });
    expect(openSpy).not.toHaveBeenCalled();
  });

  it("falls back to window.open in a browser", async () => {
    vi.mocked(isTauri).mockReturnValue(false);
    const openSpy = vi.spyOn(window, "open").mockReturnValue(null);
    await openExternal("https://example.com");
    expect(openSpy).toHaveBeenCalledWith("https://example.com", "_blank", "noopener,noreferrer");
    expect(invoke).not.toHaveBeenCalled();
  });
});
