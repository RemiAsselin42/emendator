// Client for the local FastAPI sidecar. Base URL is injected at build time
// (Vite env) so the same front works against a dev server or the bundled sidecar.
const BASE = import.meta.env.VITE_BACKEND_URL ?? "http://127.0.0.1:8008";

export interface HealthResponse {
  status: string;
  profile: string;
}

export async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetch(`${BASE}/health`);
  if (!res.ok) throw new Error(`Backend returned ${res.status}`);
  return res.json() as Promise<HealthResponse>;
}

// --- Mod ingestion (conflict map, PROJECT.md §9) -------------------------

export type ModEnvironment = "server" | "client" | "*";

export interface Mod {
  id: string;
  name: string | null;
  version: string | null;
  mcVersion: string | null;
  environment: ModEnvironment;
  depends: Record<string, string | string[]>;
  provides: string[];
  jar: string;
}

export type ConflictType =
  | "tag_overlap"
  | "recipe_collision"
  | "mixin_overlap"
  | "dependency"
  | "duplicate_jar";
export type Severity = "info" | "warning" | "error";

export interface Conflict {
  type: ConflictType;
  severity: Severity;
  detectedBy: "static" | "runtime";
  members: string[];
  // type-specific payload (tag/items, recipe, target, missing, modId/jars…)
  detail: Record<string, unknown>;
  resolution: Record<string, unknown> | null;
}

export interface UntestableMod {
  id: string;
  reason: string;
}

export interface ScanError {
  jar: string;
  reason: string;
}

export interface ScanCounts {
  total: number;
  mods: number;
  testable: number;
  untestable: number;
  errors: number;
  conflicts: number;
}

export interface ScanResult {
  profile: string;
  modsPath: string;
  mods: Mod[];
  untestable: UntestableMod[];
  conflicts: Conflict[];
  errors: ScanError[];
  counts: ScanCounts;
}

// --- Phase 2: headless runner (PROJECT.md §8) ----------------------------

export type RunStatus = "ok" | "crash" | "timeout" | "error";

export interface RunCause {
  category: string;
  summary: string;
  mods: string[];
  excerpt: string | null;
}

export interface RunVerdict {
  status: RunStatus;
  profile: string;
  durationMs: number;
  cause: RunCause | null;
  mixinExports: string[];
  logTail: string | null;
}

export type BisectStatus = "isolated" | "no_conflict" | "inconclusive" | "error";

export interface BisectResult {
  status: BisectStatus;
  profile: string;
  members: string[];
  cause: RunCause | null;
  boots: number;
  durationMs: number;
  note: string | null;
}

export function bisectSet(path: string): Promise<BisectResult> {
  return postJson<BisectResult>("/runner/bisect", { path });
}

// --- Phase 4: no-code resolution (PROJECT.md §10, §12) -------------------

export interface GeneratedFile {
  path: string;
  content: string;
}

export interface ResolutionPlan {
  profile: string;
  files: GeneratedFile[];
  summary: string;
  modPriorities: string[];
}

export interface ExportResult {
  outDir: string;
  written: string[];
}

async function postJson<T>(endpoint: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${endpoint}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = `Backend returned ${res.status}`;
    try {
      const errBody = (await res.json()) as { detail?: string };
      if (errBody.detail) detail = errBody.detail;
    } catch {
      // non-JSON error body; keep the status-based message
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export function resolvePreview(path: string): Promise<ResolutionPlan> {
  return postJson<ResolutionPlan>("/resolve/preview", { path });
}

export function resolveExport(path: string, outDir: string): Promise<ExportResult> {
  return postJson<ExportResult>("/resolve/export", { path, outDir });
}

export function testSet(path: string): Promise<RunVerdict> {
  return postJson<RunVerdict>("/runner/test", { path });
}

export function scanMods(path: string): Promise<ScanResult> {
  return postJson<ScanResult>("/mods/scan", { path });
}
