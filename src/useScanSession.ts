import { useCallback, useEffect, useReducer, useState } from "react";
import {
  AmbiguousVersionError,
  type BisectResult,
  bisectSet,
  detectInstance,
  discoverInstances,
  fetchHealth,
  type Instance,
  type InstanceReport,
  listProfiles,
  type RunVerdict,
  type ScanResult,
  scanInstance,
  testSet,
  type VersionCandidate,
  type VersionDetection,
} from "./lib/api";
import { isRecipeCollision } from "./lib/conflicts";

export type Tab =
  | "scan"
  | "overview"
  | "conflicts"
  | "recipes"
  | "runtime"
  | "resolution"
  | "resourcepacks"
  | "datapacks"
  | "shaders"
  | "items";

export const TABS: { id: Tab; label: string }[] = [
  { id: "scan", label: "Scan" },
  { id: "overview", label: "Overview" },
  { id: "conflicts", label: "Conflicts" },
  { id: "recipes", label: "Recipes" },
  { id: "runtime", label: "Runtime" },
  { id: "resolution", label: "Resolution" },
];

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
  const options = profiles.map((p) => ({ value: p.version, label: `${p.version} · ${p.block}` }));
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
    tabs.push({ id: "resourcepacks", label: "Resource Packs", count: report.resourcepacks.length });
  if (report.datapacks.length > 0)
    tabs.push({ id: "datapacks", label: "Datapacks", count: report.datapacks.length });
  if (report.shaderpacks.length > 0)
    tabs.push({ id: "shaders", label: "Shaders", count: report.shaderpacks.length });
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
  // The exact version used for the current scan (auto-detected or user-picked).
  version: string | null;
  // Set when a scan is rejected as ambiguous (§6): drives the version picker.
  pendingDetection: VersionDetection | null;
}

type ScanAction =
  | { type: "start" }
  | { type: "instance"; instance: Instance | null }
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
  version: null,
  pendingDetection: null,
};

function scanReducer(state: ScanState, action: ScanAction): ScanState {
  switch (action.type) {
    case "start":
      return { ...state, scanning: true, scanError: null, pendingDetection: null };
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
      return { ...state, result: null, report: null, pendingDetection: action.detection };
    case "failed":
      return { ...state, result: null, report: null, scanError: action.message };
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

// Best-effort startup fetches: the version blocks offered in the manual override
// and the modpacks auto-discovered from installed launchers (quick-select).
function useStartupData(): { profiles: VersionCandidate[]; discovered: Instance[] } {
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
  onTest: () => void;
  onBisect: () => void;
  resetRunner: () => void;
}

// The headless runner: a boot verdict and a bisection result, both for the current
// `modsPath`/`version`. `resetRunner` is called at scan start to drop stale runs.
function useRunner(version: string | null, modsPath: string | null): Runner {
  const [verdict, setVerdict] = useState<RunVerdict | null>(null);
  const [testing, setTesting] = useState(false);
  const [bisectResult, setBisectResult] = useState<BisectResult | null>(null);
  const [bisecting, setBisecting] = useState(false);

  const runTest = useCallback(
    async (target: string) => {
      setTesting(true);
      setVerdict(null);
      try {
        setVerdict(await testSet(target, version ?? undefined));
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
      try {
        setBisectResult(await bisectSet(target, version ?? undefined));
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
  }, []);

  return { verdict, testing, bisectResult, bisecting, onTest, onBisect, resetRunner };
}

// The whole scan session: backend health, the resolved instance and its report,
// version detection, and the runner verdicts — plus the handlers that drive them.
// Composed from focused sub-hooks and lifted out of App so the component is just
// composition.
export function useScanSession() {
  const backendDown = useBackendHealth();
  const { profiles, discovered } = useStartupData();

  const [path, setPath] = useState("");
  const [dragging, setDragging] = useState(false);
  const [tab, setTab] = useState<Tab>("scan");
  // Jars updated in place this session. Lives here (not in the mods panel) so the
  // "to update" count survives leaving and re-entering that panel; every scan
  // replaces result.mods with fresh updateAvailable flags, so we clear it then.
  const [updatedJars, setUpdatedJars] = useState<Set<string>>(new Set());
  const markUpdated = useCallback(
    (jar: string) => setUpdatedJars((prev) => (prev.has(jar) ? prev : new Set(prev).add(jar))),
    [],
  );

  const [scan, dispatch] = useReducer(scanReducer, initialScan);
  const { result, report, instance, scanning, scanError, version, pendingDetection } = scan;

  const { verdict, testing, bisectResult, bisecting, onTest, onBisect, resetRunner } = useRunner(
    version,
    result?.modsPath ?? null,
  );

  // `pick` is the user's manual version choice from the ambiguity picker; when
  // absent the backend auto-detects (and rejects an ambiguous set with 409).
  const runScan = useCallback(
    async (target: string, pick?: string) => {
      const trimmed = target.trim();
      if (!trimmed) return;
      dispatch({ type: "start" });
      resetRunner();
      // Best-effort, in parallel: never blocks or fails the scan, just feeds the
      // header badge (pack name, source, loader, content counts).
      void detectInstance(trimmed)
        .then((inst) => dispatch({ type: "instance", instance: inst }))
        .catch(() => dispatch({ type: "instance", instance: null }));
      try {
        const scanReport = await scanInstance(trimmed, pick);
        dispatch({ type: "success", report: scanReport });
        setUpdatedJars(new Set());
        setTab("overview");
      } catch (e) {
        setTab("scan");
        if (e instanceof AmbiguousVersionError) {
          dispatch({ type: "ambiguous", detection: e.detection });
        } else {
          dispatch({ type: "failed", message: e instanceof Error ? e.message : String(e) });
        }
      } finally {
        dispatch({ type: "settled" });
      }
    },
    [resetRunner],
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

  return {
    backendDown,
    path,
    setPath,
    result,
    report,
    instance,
    scanning,
    scanError,
    dragging,
    verdict,
    testing,
    bisectResult,
    bisecting,
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
    recipeCount,
    conflictCount,
    contentTabs,
  };
}
