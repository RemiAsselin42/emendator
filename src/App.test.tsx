import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ status: "ok", profile: "1.21.1" }),
      }),
    ),
  );
});

describe("App", () => {
  it("renders the application title", () => {
    render(<App />);
    expect(screen.getByRole("heading", { name: "Emendator", level: 1 })).toBeInTheDocument();
  });
});
