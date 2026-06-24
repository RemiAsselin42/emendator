import { useCallback, useEffect, useReducer, useState } from "react";
import {
  AmbiguousVersionError,
  type BisectProgress,
  type BisectResult,
  bisectSetStream,
  clearResolutionCache,
  detectInstance,
  discoverInstances,
  fetchDockerStatus,
  fetchHealth,
  type Instance,
  type InstanceReport,
  listProfiles,
  type RunVerdict,
  type ScanResult,
  scanInstanceStream,
  testSet,
  type VersionCandidate,
  type VersionDetection,
} from "./lib/api";
import { isRecipeCollision } from "./lib/conflicts";

export type Tab =
  | "scan"
  | "mods"
  | "conflicts"
  | "runtime"
  | "resolution"
  | "resourcepacks"
  | "datapacks"
  | "items";

export const TABS: { id: Tab; label: string }[] = [
  { id: "scan", label: "Scan" },
  { id: "mods", label: "Mods" },
  { id: "conflicts", label: "Conflicts" },
  { id: "runtime", label: "Runtime" },
  { id: "resolution", label: "Resolution" },
];

// Sub-tabs of the Resolution hub: one conflict family each. Mirrors the
// Runtime view's Test/Bisect split.
export type ResolutionSub = "mixins" | "recipes" | "tags" | "apply" | "deps";

export interface VersionOption {
  value: string;
  label: string;
}

export interface ContentTab {
  id: Tab;
  label: string;
  count: number;
}

// Options for the version selector: every block's representative plus the exact
// detected/used version (which may sit between reps, e.g. 1.21.4), deduped — so
// the detected one always shows selected even when it isn't a block rep.
function buildVersionOptions(
  profiles: VersionCandidate[],
  version: string | null,
  detectionBlock: string | null,
): VersionOption[] {
  const options = profiles.map((p) => ({
    value: p.version,
    label: `${p.version} · ${p.block}`,
  }));
  if (version && !options.some((o) => o.value === version)) {
    options.unshift({
      value: version,
      label: detectionBlock ? `${version} · ${detectionBlock}` : version,
    });
  }
  return options;
}

// Content tabs appear only when the instance actually has that content, so a bare
// mods folder keeps the original layout.
function buildContentTabs(report: InstanceReport | null): ContentTab[] {
  const tabs: ContentTab[] = [];
  if (!report) return tabs;
  if (report.resourcepacks.length > 0)
    tabs.push({
      id: "resourcepacks",
      label: "Resource Packs",
      count: report.resourcepacks.length,
    });
  if (report.datapacks.length > 0)
    tabs.push({
      id: "datapacks",
      label: "Datapacks",
      count: report.datapacks.length,
    });
  if (report.items.total > 0) tabs.push({ id: "items", label: "Items", count: report.items.total });
  return tabs;
}

// The scan lifecycle as one atomic unit: the resolved instance/report, the version
// detection, and the in-flight/error flags all transition together per scan, so a
// reducer keeps every render internally consistent.
interface ScanState {
  result: ScanResult | null;
  // The full instance report (mods + content packs); `result` mirrors its `mods`
  // slice so the conflict-map views are unchanged.
  report: InstanceReport | null;
  // The launcher instance the path resolved to (CurseForge/Modrinth/…), shown as a
  // badge; best-effort, resolved independently of the scan (never blocks it).
  instance: Instance | null;
  scanning: boolean;
  scanError: string | null;
  // Live scan progress (0–100) and the phase label, streamed from the backend;
  // drives the centered spinner overlay while `scanning`.
  progress: number;
  progressLabel: string;
  // The exact version used for the current scan (auto-detected or user-picked).
  version: string | null;
  // Set when a scan is rejected as ambiguous (§6): drives the version picker.
  pendingDetection: VersionDetection | null;
}

type ScanAction =
  | { type: "start" }
  | { type: "instance"; instance: Instance | null }
  | { type: "progress"; percent: number; label: string }
  | { type: "success"; report: InstanceReport }
  | { type: "ambiguous"; detection: VersionDetection }
  | { type: "failed"; message: string }
  | { type: "settled" };

const initialScan: ScanState = {
  result: null,
  report: null,
  instance: null,
  scanning: false,
  scanError: null,
  progress: 0,
  progressLabel: "",
  version: null,
  pendingDetection: null,
};

function scanReducer(state: ScanState, action: ScanAction): ScanState {
  switch (action.type) {
    case "start":
      return {
        ...state,
        scanning: true,
        scanError: null,
        progress: 0,
        progressLabel: "",
        pendingDetection: null,
      };
    case "progress":
      return { ...state, progress: action.percent, progressLabel: action.label };
    case "instance":
      return { ...state, instance: action.instance };
    case "success":
      return {
        ...state,
        result: action.report.mods,
        report: action.report,
        instance: action.report.instance,
        version: action.report.mods.profile,
      };
    case "ambiguous":
      return {
        ...state,
        result: null,
        report: null,
        pendingDetection: action.detection,
      };
    case "failed":
      return {
        ...state,
        result: null,
        report: null,
        scanError: action.message,
      };
    case "settled":
      return { ...state, scanning: false };
  }
}

// Poll the sidecar so the toast reflects the live state: it stays false during the
// first in-flight check (no flash on boot), appears when a check fails, and clears
// itself when the backend comes back.
function useBackendHealth(): boolean {
  const [backendDown, setBackendDown] = useState(false);
  useEffect(() => {
    let active = true;
    const check = () => {
      fetchHealth()
        .then(() => active && setBackendDown(false))
        .catch(() => active && setBackendDown(true));
    };
    check();
    const id = window.setInterval(check, 5000);
    return () => {
      active = false;
      window.clearInterval(id);
    };
  }, []);
  return backendDown;
}

// Poll Docker availability so a warning toast can flag when the boot runner can't
// run. Mirrors useBackendHealth: stays false until a check completes (no boot
// flash), flips true only on a definitive "not available". A failed fetch means
// the backend is down — we keep the last known Docker state so the Docker warning
// persists alongside the backend toast (the two coexist) instead of vanishing.
// Polled slower than health: `docker info` itself can take seconds when it's down.
function useDockerHealth(): boolean {
  const [dockerDown, setDockerDown] = useState(false);
  useEffect(() => {
    let active = true;
    const check = () => {
      fetchDockerStatus()
        .then((available) => active && setDockerDown(!available))
        .catch(() => {});
    };
    check();
    const id = window.setInterval(check, 15000);
    return () => {
      active = false;
      window.clearInterval(id);
    };
  }, []);
  return dockerDown;
}

// Best-effort startup fetches: the version blocks offered in the manual override
// and the modpacks auto-discovered from installed launchers (quick-select).
function useStartupData(): {
  profiles: VersionCandidate[];
  discovered: Instance[];
} {
  const [profiles, setProfiles] = useState<VersionCandidate[]>([]);
  const [discovered, setDiscovered] = useState<Instance[]>([]);

  useEffect(() => {
    listProfiles()
      .then((p) => setProfiles(Array.isArray(p) ? p : []))
      .catch(() => setProfiles([]));
  }, []);

  useEffect(() => {
    discoverInstances()
      .then((list) => setDiscovered(Array.isArray(list) ? list : []))
      .catch(() => setDiscovered([]));
  }, []);

  return { profiles, discovered };
}

interface Runner {
  verdict: RunVerdict | null;
  testing: boolean;
  bisectResult: BisectResult | null;
  bisecting: boolean;
  // Live per-boot bisection status while `bisecting`; null when idle.
  bisectProgress: BisectProgress | null;
  onTest: () => void;
  onBisect: () => void;
  resetRunner: () => void;
  // Boot an explicit folder at an explicit version — used to auto-run the first
  // test straight after a scan, without waiting for `modsPath`/`version` state.
  testTarget: (target: string, version?: string) => Promise<void>;
}

// The headless runner: a boot verdict and a bisection result, both for the current
// `modsPath`/`version`. `resetRunner` is called at scan start to drop stale runs.
function useRunner(version: string | null, modsPath: string | null): Runner {
  const [verdict, setVerdict] = useState<RunVerdict | null>(null);
  const [testing, setTesting] = useState(false);
  const [bisectResult, setBisectResult] = useState<BisectResult | null>(null);
  const [bisecting, setBisecting] = useState(false);
  const [bisectProgress, setBisectProgress] = useState<BisectProgress | null>(null);

  const runTest = useCallback(
    async (target: string, ver?: string) => {
      setTesting(true);
      setVerdict(null);
      try {
        setVerdict(await testSet(target, ver ?? version ?? undefined));
      } catch (e) {
        setVerdict({
          status: "error",
          profile: "",
          durationMs: 0,
          cause: {
            category: "startup_error",
            summary: e instanceof Error ? e.message : String(e),
            mods: [],
            excerpt: null,
          },
          mixinExports: [],
          logTail: null,
        });
      } finally {
        setTesting(false);
      }
    },
    [version],
  );

  const runBisect = useCallback(
    async (target: string) => {
      setBisecting(true);
      setBisectResult(null);
      setBisectProgress(null);
      try {
        setBisectResult(await bisectSetStream(target, version ?? undefined, setBisectProgress));
      } catch (e) {
        setBisectResult({
          status: "error",
          profile: "",
          members: [],
          boots: 0,
          durationMs: 0,
          cause: null,
          note: e instanceof Error ? e.message : String(e),
        });
      } finally {
        setBisecting(false);
        setBisectProgress(null);
      }
    },
    [version],
  );

  const onTest = useCallback(() => {
    if (modsPath) void runTest(modsPath);
  }, [modsPath, runTest]);

  const onBisect = useCallback(() => {
    if (modsPath) void runBisect(modsPath);
  }, [modsPath, runBisect]);

  const resetRunner = useCallback(() => {
    setVerdict(null);
    setBisectResult(null);
    setBisectProgress(null);
  }, []);

  return {
    verdict,
    testing,
    bisectResult,
    bisecting,
    bisectProgress,
    onTest,
    onBisect,
    resetRunner,
    testTarget: runTest,
  };
}

// The whole scan session: backend health, the resolved instance and its report,
// version detection, and the runner verdicts — plus the handlers that drive them.
// Composed from focused sub-hooks and lifted out of App so the component is just
// composition.
export function useScanSession() {
  const backendDown = useBackendHealth();
  const dockerDown = useDockerHealth();
  const { profiles, discovered } = useStartupData();

  const [path, setPath] = useState("");
  const [dragging, setDragging] = useState(false);
  const [tab, setTab] = useState<Tab>("scan");
  // The active Resolution sub-tab, lifted here so the Runtime→Resolution handoff
  // can target one (e.g. send a missing-dependency verdict straight to Deps).
  const [resolutionSub, setResolutionSub] = useState<ResolutionSub>("mixins");
  // Jars updated in place this session. Lives here (not in the mods panel) so the
  // "to update" count survives leaving and re-entering that panel; every scan
  // replaces result.mods with fresh updateAvailable flags, so we clear it then.
  const [updatedJars, setUpdatedJars] = useState<Set<string>>(new Set());
  const markUpdated = useCallback(
    (jar: string) => setUpdatedJars((prev) => (prev.has(jar) ? prev : new Set(prev).add(jar))),
    [],
  );

  const [scan, dispatch] = useReducer(scanReducer, initialScan);
  const {
    result,
    report,
    instance,
    scanning,
    scanError,
    progress,
    progressLabel,
    version,
    pendingDetection,
  } = scan;

  const {
    verdict,
    testing,
    bisectResult,
    bisecting,
    bisectProgress,
    onTest,
    onBisect,
    resetRunner,
    testTarget,
  } = useRunner(version, result?.modsPath ?? null);

  // `pick` is the user's manual version choice from the ambiguity picker; when
  // absent the backend auto-detects (and rejects an ambiguous set with 409).
  const runScan = useCallback(
    async (target: string, pick?: string) => {
      const trimmed = target.trim();
      if (!trimmed) return;
      dispatch({ type: "start" });
      resetRunner();
      clearResolutionCache(); // the mod set is changing — drop cached recipe variants
      // Best-effort, in parallel: never blocks or fails the scan, just feeds the
      // header badge (pack name, source, loader, content counts).
      void detectInstance(trimmed)
        .then((inst) => dispatch({ type: "instance", instance: inst }))
        .catch(() => dispatch({ type: "instance", instance: null }));
      try {
        const scanReport = await scanInstanceStream(trimmed, pick, (percent, label) =>
          dispatch({ type: "progress", percent, label }),
        );
        dispatch({ type: "success", report: scanReport });
        setUpdatedJars(new Set());
        setTab("mods");
        // Auto-run a first boot test so the runtime verdict appears without a
        // manual launch. Fire-and-forget (not awaited): the scan loader closes
        // now, the Mods view shows, and the boot runs in the background (the
        // Runtime tab reflects its live "testing…" state). Gated on runner
        // support, exactly like the manual Test button. Uses the freshly
        // resolved path/version directly, sidestepping stale state.
        if (scanReport.mods.detection?.runnerSupported ?? true) {
          void testTarget(scanReport.mods.modsPath, scanReport.mods.profile);
        }
      } catch (e) {
        setTab("scan");
        if (e instanceof AmbiguousVersionError) {
          dispatch({ type: "ambiguous", detection: e.detection });
        } else {
          dispatch({
            type: "failed",
            message: e instanceof Error ? e.message : String(e),
          });
        }
      } finally {
        dispatch({ type: "settled" });
      }
    },
    [resetRunner, testTarget],
  );

  // Native folder drop, Tauri only. In plain browser dev the internals are
  // absent and we fall back to the path input below.
  useEffect(() => {
    if (typeof window === "undefined" || !("__TAURI_INTERNALS__" in window)) return;
    let unlisten: (() => void) | undefined;
    import("@tauri-apps/api/webview")
      .then(({ getCurrentWebview }) =>
        getCurrentWebview().onDragDropEvent((event) => {
          const p = event.payload;
          if (p.type === "enter" || p.type === "over") {
            setDragging(true);
          } else if (p.type === "leave") {
            setDragging(false);
          } else if (p.type === "drop") {
            setDragging(false);
            const dropped = p.paths[0];
            if (dropped) {
              setPath(dropped);
              void runScan(dropped);
            }
          }
        }),
      )
      .then((u) => {
        unlisten = u;
      })
      .catch(() => {});
    return () => unlisten?.();
  }, [runScan]);

  const versionOptions = buildVersionOptions(profiles, version, result?.detection?.block ?? null);

  // Recipe collisions moved to their own tab, so the Conflicts badge counts only
  // what that tab still shows.
  const recipeCount = result ? result.conflicts.filter(isRecipeCollision).length : 0;
  const conflictCount = result ? result.counts.conflicts - recipeCount : 0;

  const contentTabs = buildContentTabs(report);

  // Runtime → Resolution handoff: jump to the Deps sub-tab to install the mods a
  // boot flagged as missing (the installer now lives under Resolution).
  const resolveMissingDeps = useCallback(() => {
    setResolutionSub("deps");
    setTab("resolution");
  }, []);

  // The reverse handoff: from Deps back to the Runtime tab, where a non-dependency
  // crash cause is shown (Deps only installs missing deps).
  const showRuntime = useCallback(() => setTab("runtime"), []);

  return {
    backendDown,
    dockerDown,
    path,
    setPath,
    result,
    report,
    instance,
    scanning,
    scanError,
    progress,
    progressLabel,
    dragging,
    verdict,
    testing,
    bisectResult,
    bisecting,
    bisectProgress,
    tab,
    setTab,
    version,
    pendingDetection,
    discovered,
    updatedJars,
    markUpdated,
    runScan,
    onTest,
    onBisect,
    versionOptions,
    conflictCount,
    contentTabs,
    resolutionSub,
    setResolutionSub,
    resolveMissingDeps,
    showRuntime,
  };
}
