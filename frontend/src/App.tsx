import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { Banner, Button, Icon, useToast } from "./ui";
import { Activity } from "./screens/Activity";
import { Home } from "./screens/Home";
import { Improvements } from "./screens/Improvements";
import { Settings } from "./screens/Settings";
import { Setup } from "./screens/Setup";
import { Welcome } from "./screens/Welcome";

type Tab = "home" | "improvements" | "activity" | "settings";
const TABS: [Tab, string][] = [["home", "Home"], ["improvements", "Improvements"], ["activity", "Activity"], ["settings", "Settings"]];

export default function App() {
  const [keys, setKeys] = useState<Record<string, boolean> | null>(null);
  const [projects, setProjects] = useState<any[] | null>(null);
  const [pid, setPid] = useState<number | null>(() => Number(localStorage.getItem("confiance.project")) || null);
  const [tab, setTab] = useState<Tab>("home");
  const [adding, setAdding] = useState(false);
  const [focusRun, setFocusRun] = useState<number | null>(null);
  const [alerts, setAlerts] = useState(0);
  const [down, setDown] = useState(false);
  const { toast, say } = useToast();

  const loadKeys = useCallback(() => api("/setup/status").then(k => { setKeys(k); setDown(false); }).catch(() => setDown(true)), []);
  const loadProjects = useCallback(() => api("/projects").then(setProjects).catch(() => setDown(true)), []);
  useEffect(() => { loadKeys(); loadProjects(); }, []);
  useEffect(() => { if (projects?.length && !projects.some(p => p.id === pid)) setPid(projects[0].id); }, [projects]);
  useEffect(() => { if (pid) localStorage.setItem("confiance.project", String(pid)); }, [pid]);
  useEffect(() => { const f = () => api("/alerts?unacknowledged=true").then(a => setAlerts(a.filter((x: any) => x.kind.startsWith("drift")).length)).catch(() => {}); f(); const t = setInterval(f, 30000); return () => clearInterval(t); }, []);

  const project = projects?.find(p => p.id === pid) ?? null;
  const ready = keys && keys.llm && keys.search;
  const setupDone = project && project.brief_version > 0;

  let body;
  if (down) body = <div className="narrow"><Banner kind="bad"><b>We can't reach the Confiance service.</b><br />Please make sure it is running, then reload this page.</Banner><Button onClick={() => location.reload()}>Reload</Button></div>;
  else if (!keys || !projects) body = <p className="muted center">Loading…</p>;
  else if (!ready) body = <Welcome status={keys} onReady={loadKeys} />;
  else if (adding || !setupDone) body = (<Setup key={adding ? "new" : project?.id ?? "first"} project={adding ? null : project}
    onCreated={id => setPid(id)} onDone={id => { setAdding(false); loadProjects().then(() => { setPid(id); setTab("home"); say("You're all set. Press “Find improvements” to begin."); }); }} />);
  else if (tab === "home") body = <Home project={project} alertsCount={alerts} goto={t => setTab(t as Tab)} onReview={id => { setFocusRun(id); setTab("improvements"); }} />;
  else if (tab === "improvements") body = <Improvements projectId={project.id} focusRun={focusRun} onFocusDone={() => setFocusRun(null)} />;
  else if (tab === "activity") body = <Activity projectId={project.id} />;
  else body = <Settings project={project} onChanged={loadProjects} />;

  const showNav = ready && setupDone && !adding && !down;
  return (<>
    <header className="top"><div className="top-in">
      <button className="brand" onClick={() => { setAdding(false); setTab("home"); }} aria-label="Confiance home"><Icon n="leaf" size={24} />CONFIANCE</button>
      {showNav && (<nav className="tabs" aria-label="Main">{TABS.map(([id, label]) => (
        <button key={id} className={`tab ${tab === id ? "on" : ""}`} onClick={() => setTab(id)} aria-current={tab === id ? "page" : undefined}>{label}{id === "settings" && alerts > 0 && <span className="dot" aria-label="needs attention" />}</button>))}</nav>)}
      {showNav && projects && (<div className="row" style={{ gap: ".5rem" }}>
        {projects.length > 1 && <select style={{ width: "auto" }} value={pid ?? ""} onChange={e => setPid(Number(e.target.value))} aria-label="Choose business">{projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select>}
        <Button kind="text" size="small" onClick={() => setAdding(true)}><Icon n="plus" size={16} />Add a business</Button></div>)}
    </div></header>
    <main>{body}</main>
    {toast}
  </>);
}
