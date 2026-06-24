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

export type Loader = "fabric" | "quilt" | "forge" | "neoforge" | "unknown";

export interface Mod {
  id: string;
  name: string | null;
  version: string | null;
  mcVersion: string | null;
  environment: ModEnvironment;
  loader: Loader;
  depends: Record<string, string | string[]>;
  provides: string[];
  jar: string;
  // Online enrichment (null when not looked up / not found).
  provider: "modrinth" | "curseforge" | null;
  homepage: string | null;
  latestVersion: string | null;
  updateAvailable: boolean | null;
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

export type UpdateStatus = "updated" | "no_update" | "not_found" | "error";

export interface UpdateResult {
  status: UpdateStatus;
  oldJar: string | null;
  newJar: string | null;
  version: string | null;
  message: string | null;
}

/** Update one jar to its latest Modrinth version, in place (downloads + swaps). */
export function updateMod(
  path: string,
  jar: string,
  version?: string,
  loader?: Loader,
): Promise<UpdateResult> {
  return postJson<UpdateResult>("/mods/update", { path, jar, version, loader });
}

export type InstallStatus = "installed" | "not_found" | "error";

export interface ProviderLink {
  provider: "modrinth" | "curseforge";
  title: string;
  url: string | null;
}

export interface InstallResult {
  status: InstallStatus;
  modId: string;
  jar: string | null;
  version: string | null;
  message: string | null;
  // On not_found: direct project links for providers where the dep exists but has
  // no build for this loader + version. Empty → the dep was found nowhere.
  links: ProviderLink[];
}

/** Install a dependency the runner flagged as missing, by its mod id (downloads
 *  the matching Modrinth version into the mods folder). */
export function installMod(
  path: string,
  modId: string,
  version?: string,
  loader?: Loader,
): Promise<InstallResult> {
  return postJson<InstallResult>("/mods/install", { path, modId, version, loader });
}

// --- CurseForge connection (the install fallback's API key) ----------------

export interface CurseForgeStatus {
  configured: boolean;
  valid: boolean | null; // probe result right after a set; null when not probed
  detail: string | null; // why a probe failed (rejected key vs. unreachable API)
}

/** Whether a CurseForge API key is configured (drives the connect prompt). */
export async function getCurseForgeStatus(): Promise<CurseForgeStatus> {
  const res = await fetch(`${BASE}/config/curseforge`);
  if (!res.ok) throw await httpError(res);
  return res.json() as Promise<CurseForgeStatus>;
}

/** Save (or, with a blank string, clear) the CurseForge API key; probes validity. */
export function setCurseForgeKey(apiKey: string): Promise<CurseForgeStatus> {
  return postJson<CurseForgeStatus>("/config/curseforge", { apiKey });
}

export type DisableStatus = "disabled" | "enabled" | "not_found" | "error";

export interface DisableResult {
  status: DisableStatus;
  jar: string | null;
  message: string | null;
}

/** Disable a mod by sidelining its jar into `disabled/` — reversible, no download.
 *  Used to resolve an incompatible mixin pair when no compatible update exists. */
export function disableMod(path: string, jar: string): Promise<DisableResult> {
  return postJson<DisableResult>("/mods/disable", { path, jar });
}

/** Re-enable a previously disabled mod (restores its jar from `disabled/`). */
export function enableMod(path: string, jar: string): Promise<DisableResult> {
  return postJson<DisableResult>("/mods/enable", { path, jar });
}

/** Raised when /mods/scan returns 409: the set spans incompatible version
 *  blocks and the user must pick one before scanning. */
export class AmbiguousVersionError extends Error {
  detection: VersionDetection;
  constructor(detection: VersionDetection) {
    super("Ambiguous Minecraft version - pick one to continue");
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

// One mod's own version of a contested recipe id (for the selection cards).
export interface RecipeVariant {
  mod: string;
  content: string; // the recipe JSON, pretty-printed
}

export interface ResolutionVariants {
  // colliding recipe id -> each contributing mod's version
  recipes: Record<string, RecipeVariant[]>;
}

// Per-conflict winner picks from the selection cards (subject id -> mod id).
export interface ResolutionWinners {
  recipeWinners?: Record<string, string>;
  tagWinners?: Record<string, string>;
}

function resolveVariants(path: string, version?: string): Promise<ResolutionVariants> {
  return postJson<ResolutionVariants>("/resolve/variants", { path, version });
}

// Recipe variants are read from every jar, so memoise them per pack: switching
// sub-tabs / tabs then re-opens the Recipes cards instantly instead of re-reading.
const recipeVariantsCache = new Map<string, ResolutionVariants>();

function variantsKey(path: string, version?: string): string {
  return `${path}|${version ?? ""}`;
}

/** Synchronously read already-fetched recipe variants for a pack (no flash on remount). */
export function peekRecipeVariants(path: string, version?: string): ResolutionVariants | undefined {
  return recipeVariantsCache.get(variantsKey(path, version));
}

/** Fetch recipe variants, memoised per pack (path + version). */
export async function loadRecipeVariants(
  path: string,
  version?: string,
): Promise<ResolutionVariants> {
  const key = variantsKey(path, version);
  const hit = recipeVariantsCache.get(key);
  if (hit) return hit;
  const variants = await resolveVariants(path, version);
  recipeVariantsCache.set(key, variants);
  return variants;
}

/** Drop the resolution caches — called on a new scan, since the mod set changed. */
export function clearResolutionCache(): void {
  recipeVariantsCache.clear();
}

// --- Apply the resolution into the live instance (reversibly) -------------

export type ApplyTarget = "per_world" | "openloader";

export interface ResolutionTargets {
  almostUnified: boolean; // tags via unify.json (AU) instead of a re-tag datapack
  openLoader: boolean; // the global datapack target is available
  worlds: string[]; // existing datapack dirs (global + per-world)
}

export interface ApplyResult {
  status: "applied" | "nothing" | "error";
  written: string[];
  targets: string[];
  manifest: string | null;
  almostUnified: boolean;
  openLoader: boolean;
  message: string | null;
}

export interface RevertResult {
  status: "reverted" | "not_found" | "error";
  removed: string[];
  message: string | null;
}

/** What the pack supports for applying a resolution (AU / Open Loader / worlds). */
export function resolveTargets(path: string, version?: string): Promise<ResolutionTargets> {
  return postJson<ResolutionTargets>("/resolve/targets", { path, version });
}

/** Write the resolution into the instance (reversibly). `path` is the instance root. */
export function applyResolution(
  path: string,
  version: string | undefined,
  winners: ResolutionWinners,
  target: ApplyTarget,
): Promise<ApplyResult> {
  return postJson<ApplyResult>("/resolve/apply", {
    path,
    version,
    recipeWinners: winners.recipeWinners,
    tagWinners: winners.tagWinners,
    target,
  });
}

/** Undo a prior apply by its manifest path. */
export function revertResolution(manifest: string): Promise<RevertResult> {
  return postJson<RevertResult>("/resolve/revert", { manifest });
}

export function testSet(path: string, version?: string): Promise<RunVerdict> {
  return postJson<RunVerdict>("/runner/test", { path, version });
}

export async function listProfiles(): Promise<VersionCandidate[]> {
  const res = await fetch(`${BASE}/profiles`);
  if (!res.ok) throw await httpError(res);
  return res.json() as Promise<VersionCandidate[]>;
}

// --- Instances (launcher-native ingestion) -------------------------------

export type InstanceSource =
  | "curseforge"
  | "modrinth"
  | "prism"
  | "multimc"
  | "vanilla"
  | "raw_mods";

export interface InstanceFolders {
  mods: string | null;
  resourcepacks: string | null;
  config: string | null;
  datapacks: string[];
}

export interface Instance {
  root: string;
  source: InstanceSource;
  name: string | null;
  loader: Loader;
  mcVersion: string | null;
  folders: InstanceFolders;
  modCount: number;
  resourcepackCount: number;
  datapackCount: number;
}

export interface ResourcePack {
  name: string;
  packFormat: number | null;
  description: string | null;
  assetCount: number;
  source: "zip" | "dir";
}

export interface Datapack {
  name: string;
  location: string;
  packFormat: number | null;
  description: string | null;
  dataCount: number;
  source: "zip" | "dir";
}

export interface ItemEntry {
  id: string;
  displayName: string | null;
  kind: "item" | "block";
  mod: string;
}

export interface RegistryIndex {
  items: ItemEntry[];
  total: number;
  itemCount: number;
  blockCount: number;
}

export interface InstanceReport {
  instance: Instance;
  mods: ScanResult;
  resourcepacks: ResourcePack[];
  datapacks: Datapack[];
  resourcepackConflicts: Conflict[];
  datapackConflicts: Conflict[];
  items: RegistryIndex;
}

export function detectInstance(path: string): Promise<Instance> {
  return postJson<Instance>("/instance/detect", { path });
}

/** Modpack instances auto-discovered from known launcher install locations
 *  (CurseForge, Modrinth, Prism, MultiMC, vanilla) — for quick-select. */
export async function discoverInstances(): Promise<Instance[]> {
  const res = await fetch(`${BASE}/instances/discover`);
  if (!res.ok) throw await httpError(res);
  return res.json() as Promise<Instance[]>;
}

/** Scan an instance (launcher root or bare `mods/` folder) into a full report:
 *  the mod conflict map plus content-pack sections. Ambiguous version sets
 *  reject with 409 as {@link AmbiguousVersionError}; mods and content folders
 *  are located automatically. */
export function scanInstance(path: string, version?: string): Promise<InstanceReport> {
  return scanAt<InstanceReport>("/instance/scan", path, version);
}

/** Shared body of the scan endpoints: POST + 409 → AmbiguousVersionError. */
async function scanAt<T>(endpoint: string, path: string, version?: string): Promise<T> {
  const res = await fetch(`${BASE}${endpoint}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path, version }),
  });
  if (res.status === 409) {
    const body = (await res.json()) as { detail: VersionDetection };
    throw new AmbiguousVersionError(body.detail);
  }
  if (!res.ok) throw await httpError(res);
  return res.json() as Promise<T>;
}
