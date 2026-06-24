import { useEffect, useState } from "react";
import { AppHeader, ContentTabPanel, CoreTabPanel, ScanTab, Sidebar } from "./AppChrome";
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

      {backendDown && (
        <div className="toast toast-error" role="alert">
          <span className="toast-title">Backend unreachable</span>
          <span className="toast-body">Retrying…</span>
        </div>
      )}

      <CurseForgeConnect status={cfStatus} onChanged={setCfStatus} />
    </main>
  );
}
