import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CurseForgeStatus } from "./lib/api";
import * as api from "./lib/api";
import { Settings } from "./Settings";

vi.mock("./lib/api", () => ({
  setCurseForgeKey: vi.fn(),
}));

const UNCONFIGURED: CurseForgeStatus = { configured: false, valid: null, detail: null };
const CONFIGURED: CurseForgeStatus = { configured: true, valid: true, detail: null };

beforeEach(() => {
  vi.mocked(api.setCurseForgeKey).mockResolvedValue(UNCONFIGURED);
});

afterEach(() => vi.clearAllMocks());

function openSettings() {
  fireEvent.click(screen.getByRole("button", { name: "Settings" }));
}

describe("Settings", () => {
  it("opens the panel from the gear button", async () => {
    render(<Settings status={UNCONFIGURED} onChanged={vi.fn()} />);
    openSettings();
    expect(await screen.findByRole("heading", { name: "Settings" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "CurseForge API key" })).toBeInTheDocument();
  });

  it("offers Remove only when a key is configured", () => {
    const { rerender } = render(<Settings status={UNCONFIGURED} onChanged={vi.fn()} />);
    openSettings();
    expect(screen.queryByText("Remove key")).not.toBeInTheDocument();
    rerender(<Settings status={CONFIGURED} onChanged={vi.fn()} />);
    expect(screen.getByText("Remove key")).toBeInTheDocument();
  });

  it("removes the key and reports it", async () => {
    const onChanged = vi.fn();
    render(<Settings status={CONFIGURED} onChanged={onChanged} />);
    openSettings();
    fireEvent.click(screen.getByText("Remove key"));
    await waitFor(() => expect(api.setCurseForgeKey).toHaveBeenCalledWith(""));
    expect(onChanged).toHaveBeenCalledWith(UNCONFIGURED);
    expect(await screen.findByText("Key removed.")).toBeInTheDocument();
  });

  it("replaces an existing key", async () => {
    vi.mocked(api.setCurseForgeKey).mockResolvedValue(CONFIGURED);
    render(<Settings status={CONFIGURED} onChanged={vi.fn()} />);
    openSettings();
    fireEvent.change(screen.getByPlaceholderText("Enter a new key to replace it"), {
      target: { value: "new-key" },
    });
    fireEvent.click(screen.getByText("Replace key"));
    await waitFor(() => expect(api.setCurseForgeKey).toHaveBeenCalledWith("new-key"));
  });
});
