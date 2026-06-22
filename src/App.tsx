import { AppHeader, ContentTabPanel, CoreTabPanel, ScanTab, Sidebar } from "./AppChrome";
import { useScanSession } from "./useScanSession";

export default function App() {
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
    recipeCount,
    conflictCount,
    contentTabs,
  } = session;

  return (
    <main className="container">
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
            recipeCount={recipeCount}
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
              />
              <ContentTabPanel tab={tab} report={report} />
            </div>
          )}
        </div>
      </div>

      {backendDown && (
        <div className="toast toast-error" role="alert">
          <span className="toast-title">Backend unreachable</span>
          <span className="toast-body">start the sidecar — retrying…</span>
        </div>
      )}
    </main>
  );
}
