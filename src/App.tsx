import { useEffect, useState } from "react";
import {
  AppHeader,
  ContentTabPanel,
  CoreTabPanel,
  ScanProgressOverlay,
  ScanTab,
  Sidebar,
} from "./AppChrome";
import { CurseForgeConnect } from "./CurseForgeConnect";
import { type CurseForgeStatus, getCurseForgeStatus } from "./lib/api";
import { useExternalLinks } from "./lib/external";
import { Settings } from "./Settings";
import { useScanSession } from "./useScanSession";

export default function App() {
  useExternalLinks(); // route <a target="_blank"> through the OS browser under Tauri

  // CurseForge connection status lives here so the connect prompt and the Settings
  // panel share one source of truth — a change in either updates both at once.
  const [cfStatus, setCfStatus] = useState<CurseForgeStatus | null>(null);
  useEffect(() => {
    let alive = true;
    getCurseForgeStatus()
      .then((s) => {
        if (alive) setCfStatus(s);
      })
      .catch(() => {
        // Backend not reachable yet — the backend-down toast already covers that.
      });
    return () => {
      alive = false;
    };
  }, []);

  const session = useScanSession();
  const {
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
  } = session;

  return (
    <main className="container">
      <Settings status={cfStatus} onChanged={setCfStatus} />

      <AppHeader
        instance={instance}
        result={result}
        version={version}
        scanning={scanning}
        versionOptions={versionOptions}
        onRescan={(pick) => {
          if (result) void runScan(result.modsPath, pick);
        }}
      />

      {/* Before the first scan there's nothing to navigate — show only the import
          panel; the sidebar appears once a scan produces a result. */}
      <div className={result ? "layout" : "layout layout-solo"}>
        {result && (
          <Sidebar
            tab={tab}
            setTab={setTab}
            conflictCount={conflictCount}
            contentTabs={contentTabs}
            testing={testing}
          />
        )}

        <div className="content">
          {tab === "scan" && (
            <ScanTab
              path={path}
              setPath={setPath}
              scanning={scanning}
              dragging={dragging}
              discovered={discovered}
              pendingDetection={pendingDetection}
              onScan={runScan}
            />
          )}

          {scanError && <p className="scan-error">scan failed: {scanError}</p>}

          {result && tab !== "scan" && (
            <div className="panel-content">
              <CoreTabPanel
                tab={tab}
                result={result}
                instance={instance}
                version={version}
                verdict={verdict}
                testing={testing}
                bisecting={bisecting}
                bisectResult={bisectResult}
                bisectProgress={bisectProgress}
                updatedJars={updatedJars}
                onUpdated={markUpdated}
                onTest={onTest}
                onBisect={onBisect}
                resolutionSub={resolutionSub}
                setResolutionSub={setResolutionSub}
                onResolveDeps={resolveMissingDeps}
                onShowRuntime={showRuntime}
              />
              <ContentTabPanel tab={tab} report={report} />
            </div>
          )}
        </div>
      </div>

      {/* Backend and Docker are independent health signals, so their toasts stack
          bottom-right and coexist (one above the other when both are down) rather
          than one replacing or hiding the other. */}
      <div className="toast-stack">
        {backendDown && (
          <div className="toast toast-error" role="alert">
            <span className="toast-title">Backend unreachable</span>
            <span className="toast-body">Please restart the app</span>
          </div>
        )}

        {dockerDown && (
          <div className="toast toast-warn" role="status">
            <span className="toast-title">Docker unreachable</span>
            <span className="toast-body">Runtime tests need Docker running</span>
          </div>
        )}
      </div>

      <CurseForgeConnect status={cfStatus} onChanged={setCfStatus} />

      {scanning && <ScanProgressOverlay percent={progress} label={progressLabel} />}
    </main>
  );
}
