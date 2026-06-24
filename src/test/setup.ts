import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Vitest isn't run with `globals: true`, so Testing Library's automatic
// afterEach cleanup doesn't register itself — unmount between tests by hand,
// or successive renders pile up in the same document.body.
afterEach(cleanup);
