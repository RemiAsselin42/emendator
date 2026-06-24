import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CurseForgeConnect } from "./CurseForgeConnect";
import type { CurseForgeStatus } from "./lib/api";
import * as api from "./lib/api";

vi.mock("./lib/api", () => ({
  setCurseForgeKey: vi.fn(),
}));

const UNCONFIGURED: CurseForgeStatus = { configured: false, valid: null, detail: null };
const CONFIGURED: CurseForgeStatus = { configured: true, valid: true, detail: null };

beforeEach(() => {
  localStorage.clear();
  vi.mocked(api.setCurseForgeKey).mockResolvedValue(CONFIGURED);
});

afterEach(() => vi.clearAllMocks());

describe("CurseForgeConnect", () => {
  it("shows the connect prompt when no key is configured", () => {
    render(<CurseForgeConnect status={UNCONFIGURED} onChanged={vi.fn()} />);
    expect(screen.getByText("Connect CurseForge")).toBeInTheDocument();
  });

  it("stays hidden when a key is already configured", () => {
    render(<CurseForgeConnect status={CONFIGURED} onChanged={vi.fn()} />);
    expect(screen.queryByText("Connect CurseForge")).not.toBeInTheDocument();
  });

  it("opens the modal and saves the entered key", async () => {
    render(<CurseForgeConnect status={UNCONFIGURED} onChanged={vi.fn()} />);
    fireEvent.click(screen.getByText("Connect CurseForge"));
    fireEvent.change(screen.getByPlaceholderText("CurseForge API key"), {
      target: { value: "my-key" },
    });
    fireEvent.click(screen.getByText("Save key"));
    await waitFor(() => expect(api.setCurseForgeKey).toHaveBeenCalledWith("my-key"));
    expect(await screen.findByText(/CurseForge is connected/)).toBeInTheDocument();
  });

  it("hides for good after 'Don't show this again'", async () => {
    render(<CurseForgeConnect status={UNCONFIGURED} onChanged={vi.fn()} />);
    fireEvent.click(screen.getByText("Connect CurseForge"));
    fireEvent.click(screen.getByText("Don't show this again"));
    await waitFor(() => expect(screen.queryByText("Connect CurseForge")).not.toBeInTheDocument());
    expect(localStorage.getItem("emendator.curseforgeBannerDismissed")).toBe("1");
  });
});
