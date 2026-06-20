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

// --- Version detection (PROJECT.md §6) -----------------------------------

export type DetectionStatus = "confident" | "ambiguous";

export interface VersionCandidate {
  version: string; // representative exact version of the block
  block: string; // block id, e.g. "1.21–1.21.1"
  modCount: number;
}

export interface VersionDetection {
  detectedVersion: string | null;
  block: string | null;
  jdk: string | null;
  status: DetectionStatus;
  confidence: number; // 0..1 share of constraining mods compatible with the pick
  candidates: VersionCandidate[];
  outliers: string[];
  runnerSupported: boolean;
}

export interface ScanResult {
  profile: string; // exact version actually used for this scan
  modsPath: string;
  mods: Mod[];
  untestable: UntestableMod[];
  conflicts: Conflict[];
  errors: ScanError[];
  counts: ScanCounts;
  detection: VersionDetection | null;
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

export function bisectSet(path: string, version?: string): Promise<BisectResult> {
  return postJson<BisectResult>("/runner/bisect", { path, version });
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

/** Raised when /mods/scan returns 409: the set spans incompatible version
 *  blocks and the user must pick one before scanning. */
export class AmbiguousVersionError extends Error {
  detection: VersionDetection;
  constructor(detection: VersionDetection) {
    super("Ambiguous Minecraft version — pick one to continue");
    this.name = "AmbiguousVersionError";
    this.detection = detection;
  }
}

async function httpError(res: Response): Promise<Error> {
  let detail = `Backend returned ${res.status}`;
  try {
    const errBody = (await res.json()) as { detail?: string };
    if (typeof errBody.detail === "string") detail = errBody.detail;
  } catch {
    // non-JSON error body; keep the status-based message
  }
  return new Error(detail);
}

async function postJson<T>(endpoint: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${endpoint}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw await httpError(res);
  return res.json() as Promise<T>;
}

export function resolvePreview(path: string, version?: string): Promise<ResolutionPlan> {
  return postJson<ResolutionPlan>("/resolve/preview", { path, version });
}

export function resolveExport(
  path: string,
  outDir: string,
  version?: string,
): Promise<ExportResult> {
  return postJson<ExportResult>("/resolve/export", { path, outDir, version });
}

export function testSet(path: string, version?: string): Promise<RunVerdict> {
  return postJson<RunVerdict>("/runner/test", { path, version });
}

export async function listProfiles(): Promise<VersionCandidate[]> {
  const res = await fetch(`${BASE}/profiles`);
  if (!res.ok) throw await httpError(res);
  return res.json() as Promise<VersionCandidate[]>;
}

/** Scan a folder. With no `version` the backend auto-detects; an ambiguous set
 *  rejects with 409, surfaced here as {@link AmbiguousVersionError}. */
export async function scanMods(path: string, version?: string): Promise<ScanResult> {
  const res = await fetch(`${BASE}/mods/scan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path, version }),
  });
  if (res.status === 409) {
    const body = (await res.json()) as { detail: VersionDetection };
    throw new AmbiguousVersionError(body.detail);
  }
  if (!res.ok) throw await httpError(res);
  return res.json() as Promise<ScanResult>;
}
