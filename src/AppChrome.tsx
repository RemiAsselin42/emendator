import type {
  BisectResult,
  Instance,
  InstanceReport,
  RunVerdict,
  ScanResult,
  VersionDetection,
} from "./lib/api";
import type { ContentTab, ResolutionSub, Tab, VersionOption } from "./useScanSession";
import { TABS } from "./useScanSession";
import {
  ConflictsView,
  DatapacksView,
  ItemsView,
  Mods,
  ResolutionView,
  ResourcePacksView,
  RuntimeView,
} from "./views";

// How each detected source reads in the badge; raw_mods is the bare folder input.
const SOURCE_LABEL: Record<Instance["source"], string> = {
  curseforge: "CurseForge",
  modrinth: "Modrinth",
  prism: "Prism",
  multimc: "MultiMC",
  vanilla: ".minecraft",
  raw_mods: "mods folder",
};

// Header chip summarising the resolved instance: source, name, loader, version
// and the content counts that hint at what's beyond the mods themselves.
function InstanceBadge({ instance }: { instance: Instance }) {
  const counts: string[] = [`${instance.modCount} mods`];
  if (instance.resourcepackCount > 0) counts.push(`${instance.resourcepackCount} resourcepacks`);
  if (instance.datapackCount > 0) counts.push(`${instance.datapackCount} datapacks`);
  return (
    <div className={`instance-badge source-${instance.source}`}>
      <span className="instance-source">{SOURCE_LABEL[instance.source]}</span>
      {instance.name && <span className="instance-name">{instance.name}</span>}
      {instance.loader !== "unknown" && <span className="instance-loader">{instance.loader}</span>}
      {instance.mcVersion && <span className="instance-mc">{instance.mcVersion}</span>}
      <span className="instance-counts">{counts.join(" · ")}</span>
    </div>
  );
}

// Title, the resolved-instance badge, and the version selector (a re-scan at the
// picked version). The version bar only appears once a scan has produced a result.
export function AppHeader({
  instance,
  result,
  version,
  scanning,
  versionOptions,
  onRescan,
}: {
  instance: Instance | null;
  result: ScanResult | null;
  version: string | null;
  scanning: boolean;
  versionOptions: VersionOption[];
  onRescan: (pick: string) => void;
}) {
  return (
    <header className="header">
      <h1>Emendator</h1>
      <p className="tagline">Minecraft modpack conflict analyzer</p>

      {instance && result && <InstanceBadge instance={instance} />}

      {result && (
        <div className="version-bar">
          <label className="mc-version">
            <select
              value={version ?? ""}
              disabled={scanning}
              onChange={(e) => {
                const pick = e.target.value;
                if (pick) onRescan(pick);
              }}
            >
              {versionOptions.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
          {result.detection && (
            <span className="note">
              {result.detection.status === "confident" ? "Version auto-detected" : "selected"}
              {!result.detection.runnerSupported && " · runtime not yet available"}
            </span>
          )}
        </div>
      )}
    </header>
  );
}

// The path input + drop target. The native folder drop is wired in the session
// hook; this is the manual fallback and the "scanning…" affordance.
function ScanForm({
  path,
  setPath,
  scanning,
  dragging,
  onScan,
}: {
  path: string;
  setPath: (value: string) => void;
  scanning: boolean;
  dragging: boolean;
  onScan: (target: string) => void;
}) {
  return (
    <section
      className={dragging ? "dropzone dragging" : "dropzone"}
      aria-label="modpack folder drop target"
    >
      <p>
        Drop a modpack instance (CurseForge, Modrinth, Prism…) or a bare <code>mods/</code> folder
        here, or paste its path.
      </p>
      <form
        className="dropzone-form"
        onSubmit={(e) => {
          e.preventDefault();
          void onScan(path);
        }}
      >
        <input
          className="path-input"
          type="text"
          placeholder="C:\\Users\\…\\mods"
          value={path}
          onChange={(e) => setPath(e.target.value)}
          spellCheck={false}
        />
        <button className="btn-primary" type="submit" disabled={scanning || !path.trim()}>
          {scanning ? "scanning…" : "Scan"}
        </button>
      </form>
    </section>
  );
}

// Modpacks auto-discovered from installed launchers — one-click scan targets.
function QuickSelect({
  discovered,
  scanning,
  setPath,
  onScan,
}: {
  discovered: Instance[];
  scanning: boolean;
  setPath: (value: string) => void;
  onScan: (target: string) => void;
}) {
  return (
    <section className="quick-select" aria-label="installed modpacks">
      <h2 className="quick-title">Quick select</h2>
      <p className="note">Modpacks found on this PC</p>
      <div className="quick-list">
        {discovered.map((inst) => (
          <button
            key={inst.root}
            type="button"
            className="quick-card"
            disabled={scanning}
            onClick={() => {
              setPath(inst.root);
              void onScan(inst.root);
            }}
          >
            <span className="quick-card-head">
              <span className="quick-name">{inst.name ?? inst.root}</span>
              <span className="quick-source">{SOURCE_LABEL[inst.source]}</span>
            </span>
            <span className="quick-meta">
              {inst.loader !== "unknown" && <span className="quick-loader">{inst.loader}</span>}
              {inst.mcVersion && <span>{inst.mcVersion}</span>}
              <span>{inst.modCount} mods</span>
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}

// Shown when a scan is rejected as ambiguous (§6): the mods don't agree on one
// Minecraft version, so pick the target block to re-scan against.
function VersionPicker({
  detection,
  path,
  scanning,
  onScan,
}: {
  detection: VersionDetection;
  path: string;
  scanning: boolean;
  onScan: (target: string, pick: string) => void;
}) {
  return (
    <section className="version-picker" aria-label="pick Minecraft version">
      <p className="scan-error">
        Couldn't pin the Minecraft version automatically
        {detection.candidates.length > 0 ? ", these mods don't agree on one." : "."} Pick the target
        to scan:
      </p>
      <div className="picker-options">
        {detection.candidates.map((c) => (
          <button
            key={c.block}
            type="button"
            className="btn-primary"
            disabled={scanning}
            onClick={() => void onScan(path, c.version)}
          >
            {c.block} · {c.version} ({c.modCount} mod
            {c.modCount === 1 ? "" : "s"})
          </button>
        ))}
      </div>
      {detection.outliers.length > 0 && (
        <p className="note">incompatible at the newest target: {detection.outliers.join(", ")}</p>
      )}
    </section>
  );
}

// The "scan" tab: the import form plus the optional quick-select and version
// picker. Composed here so App's content area stays a flat switch.
export function ScanTab({
  path,
  setPath,
  scanning,
  dragging,
  discovered,
  pendingDetection,
  onScan,
}: {
  path: string;
  setPath: (value: string) => void;
  scanning: boolean;
  dragging: boolean;
  discovered: Instance[];
  pendingDetection: VersionDetection | null;
  onScan: (target: string, pick?: string) => void;
}) {
  return (
    <>
      <ScanForm
        path={path}
        setPath={setPath}
        scanning={scanning}
        dragging={dragging}
        onScan={onScan}
      />
      {discovered.length > 0 && (
        <QuickSelect
          discovered={discovered}
          scanning={scanning}
          setPath={setPath}
          onScan={onScan}
        />
      )}
      {pendingDetection && (
        <VersionPicker
          detection={pendingDetection}
          path={path}
          scanning={scanning}
          onScan={onScan}
        />
      )}
    </>
  );
}

// Panel navigation: the fixed tabs (with conflict/recipe counts) plus the content
// tabs that only appear when the instance carries that content.
export function Sidebar({
  tab,
  setTab,
  conflictCount,
  contentTabs,
}: {
  tab: Tab;
  setTab: (tab: Tab) => void;
  conflictCount: number;
  contentTabs: ContentTab[];
}) {
  return (
    <nav className="sidebar" aria-label="panels">
      {TABS.map((t) => (
        <button
          key={t.id}
          type="button"
          className={tab === t.id ? "nav-item nav-item-active" : "nav-item"}
          onClick={() => setTab(t.id)}
        >
          {t.label}
          {t.id === "conflicts" && ` (${conflictCount})`}
        </button>
      ))}
      {contentTabs.map((t) => (
        <button
          key={t.id}
          type="button"
          className={tab === t.id ? "nav-item nav-item-active" : "nav-item"}
          onClick={() => setTab(t.id)}
        >
          {t.label} ({t.count})
        </button>
      ))}
    </nav>
  );
}

// The runtime tab's wiring: derives runner support and the resolved version/loader
// from the scan result, so CoreTabPanel stays a flat tab switch.
function RuntimeTab({
  result,
  verdict,
  testing,
  bisecting,
  bisectResult,
  onTest,
  onBisect,
  onResolve,
}: {
  result: ScanResult;
  verdict: RunVerdict | null;
  testing: boolean;
  bisecting: boolean;
  bisectResult: BisectResult | null;
  onTest: () => void;
  onBisect: () => void;
  onResolve: () => void;
}) {
  return (
    <RuntimeView
      verdict={verdict}
      onTest={onTest}
      testing={testing}
      onBisect={onBisect}
      bisecting={bisecting}
      bisectResult={bisectResult}
      runnerSupported={result.detection?.runnerSupported ?? true}
      block={result.detection?.block ?? null}
      onResolve={onResolve}
    />
  );
}

// The five core panels (mods + conflict map + runner). Rendered only once a scan
// has a result, so `result` is always present here.
export function CoreTabPanel({
  tab,
  result,
  instance,
  version,
  verdict,
  testing,
  bisecting,
  bisectResult,
  updatedJars,
  onUpdated,
  onTest,
  onBisect,
  resolutionSub,
  setResolutionSub,
  onResolveDeps,
  onShowRuntime,
}: {
  tab: Tab;
  result: ScanResult;
  instance: Instance | null;
  version: string | null;
  verdict: RunVerdict | null;
  testing: boolean;
  bisecting: boolean;
  bisectResult: BisectResult | null;
  updatedJars: Set<string>;
  onUpdated: (jar: string) => void;
  onTest: () => void;
  onBisect: () => void;
  resolutionSub: ResolutionSub;
  setResolutionSub: (sub: ResolutionSub) => void;
  onResolveDeps: () => void;
  onShowRuntime: () => void;
}) {
  return (
    <>
      {tab === "mods" && <Mods result={result} updatedJars={updatedJars} onUpdated={onUpdated} />}
      {tab === "conflicts" && <ConflictsView conflicts={result.conflicts} verdict={verdict} />}
      {tab === "runtime" && (
        <RuntimeTab
          result={result}
          verdict={verdict}
          testing={testing}
          bisecting={bisecting}
          bisectResult={bisectResult}
          onTest={onTest}
          onBisect={onBisect}
          onResolve={onResolveDeps}
        />
      )}
      {tab === "resolution" && (
        <ResolutionView
          modsPath={result.modsPath}
          instanceRoot={instance?.root ?? result.modsPath}
          version={version ?? result.profile}
          conflicts={result.conflicts}
          mods={result.mods}
          verdict={verdict}
          testing={testing}
          onTest={onTest}
          updatedJars={updatedJars}
          onUpdated={onUpdated}
          loader={instance?.loader}
          sub={resolutionSub}
          setSub={setResolutionSub}
          onShowRuntime={onShowRuntime}
        />
      )}
    </>
  );
}

// The content panels (resource packs / datapacks / items), present only
// when the report carries that content.
export function ContentTabPanel({ tab, report }: { tab: Tab; report: InstanceReport | null }) {
  if (!report) return null;
  return (
    <>
      {tab === "resourcepacks" && (
        <ResourcePacksView packs={report.resourcepacks} conflicts={report.resourcepackConflicts} />
      )}
      {tab === "datapacks" && (
        <DatapacksView packs={report.datapacks} conflicts={report.datapackConflicts} />
      )}
      {tab === "items" && <ItemsView index={report.items} />}
    </>
  );
}
