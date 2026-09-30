import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { useApi, useLocal } from "./hooks";
import { Badge, Banner, Button, Icon, IconName, Select, Skeleton, Toaster } from "./ui";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { useTheme } from "./landing/theme";
import Activity from "./pages/Activity";
import Optimize from "./pages/Optimize";
import Overview from "./pages/Overview";
import Plan from "./pages/Plan";
import Products from "./pages/Products";
import Reports from "./pages/Reports";
import Settings from "./pages/Settings";
import Setup from "./pages/Setup";
import Site from "./pages/Site";
import Visibility from "./pages/Visibility";
import { Welcome } from "./pages/Welcome";

export type View = "overview" | "visibility" | "optimize" | "plan" | "site" | "products" | "reports" | "activity" | "settings";
export type Go = (v: View, ctx?: any) => void;
const NAV: { group?: string; id: View; label: string; icon: IconName }[] = [
  { group: "Measure", id: "overview", label: "Overview", icon: "home" }, { id: "visibility", label: "Visibility", icon: "eye" }, { id: "products", label: "Products", icon: "tag" }, { id: "site", label: "Site health", icon: "globe" },
  { group: "Improve", id: "optimize", label: "Optimize", icon: "loop" }, { id: "plan", label: "Plan", icon: "list" }, { id: "reports", label: "Reports", icon: "file" },
  { group: "Manage", id: "activity", label: "Activity", icon: "clock" }, { id: "settings", label: "Settings", icon: "gear" },
];

export default function App() {
  const [keys, setKeys] = useState<Record<string, boolean> | null>(null);
  const [projects, setProjects] = useState<any[] | null>(null);
  const [pid, setPid] = useLocal<number | null>("confiance.project", null);
  const [view, setView] = useLocal<View>("confiance.view", "overview");
  const [ctx, setCtx] = useState<any>(null);
  const [adding, setAdding] = useState(false);
  const [down, setDown] = useState(false);
  const { wanted, toggle } = useTheme();
  const loadKeys = useCallback(() => api("/setup/status").then(k => { setKeys(k); setDown(false); }).catch(() => setDown(true)), []);
  const loadProjects = useCallback(() => api("/projects").then(setProjects).catch(() => setDown(true)), []);
  useEffect(() => { loadKeys(); loadProjects(); }, []);
  useEffect(() => { if (projects?.length && !projects.some(p => p.id === pid)) setPid(projects[0].id); }, [projects]);

  const project = projects?.find(p => p.id === pid) ?? null;
  const ready = !!keys && keys.llm && keys.search;
  const setupDone = !!project && project.brief_version > 0;
  const ov = useApi<any>(ready && setupDone ? `/projects/${pid}/overview` : null, { poll: 20000 });
  const alerts = useApi<any[]>(ready ? "/alerts?unacknowledged=true" : null, { poll: 30000 });
  const go: Go = (v, c) => { setAdding(false); setCtx(c ?? null); setView(v); window.scrollTo({ top: 0 }); };
  const open = ov.data?.plan_open?.P0 ?? 0;
  const driftAlerts = (alerts.data ?? []).filter((a: any) => a.kind?.startsWith("drift")).length;

  let body;
  if (down) body = <div className="page"><Banner kind="bad"><b>We can't reach the Confiance service.</b><br />Please make sure it is running, then reload this page.</Banner><div className="mt-4"><Button onClick={() => location.reload()}>Reload</Button></div></div>;
  else if (!keys || !projects) body = <div className="page"><Skeleton h={36} w={260} /><div className="mt-4"><Skeleton h={180} /></div></div>;
  else if (!ready) body = <div className="page"><Welcome status={keys} onReady={loadKeys} /></div>;
  else if (adding || !setupDone) body = <div className="page"><Setup key={adding ? "new" : project?.id ?? "first"} project={adding ? null : project} onCreated={id => setPid(id)}
    onDone={id => { setAdding(false); loadProjects().then(() => { setPid(id); go("overview"); }); }} /></div>;
  else {
    const P = { project, go, ctx, reload: loadProjects };
    body = view === "overview" ? <Overview {...P} /> : view === "visibility" ? <Visibility {...P} /> : view === "optimize" ? <Optimize {...P} /> : view === "plan" ? <Plan {...P} /> : view === "site" ? <Site {...P} />
      : view === "products" ? <Products {...P} /> : view === "reports" ? <Reports {...P} /> : view === "activity" ? <Activity {...P} /> : <Settings {...P} />;
  }
  const showNav = ready && setupDone && !adding && !down;
  // Welcome, setup and error screens stand alone: the sidebar only appears once there is a dashboard to move around.
  return (<TooltipProvider><div className={cn("min-h-screen", showNav && "grid max-[899px]:grid-rows-[auto_1fr] min-[900px]:grid-cols-[248px_minmax(0,1fr)]")}>
    {showNav && <aside aria-label="Main navigation" className="flex items-center max-[899px]:[scrollbar-width:none] gap-1 overflow-x-auto border-b bg-[color-mix(in_srgb,var(--card)_55%,var(--background))] px-2.5 py-2 min-[900px]:sticky min-[900px]:top-0 min-[900px]:h-screen min-[900px]:flex-col min-[900px]:items-stretch min-[900px]:overflow-y-auto min-[900px]:overflow-x-visible min-[900px]:border-r min-[900px]:border-b-0 min-[900px]:px-3 min-[900px]:pt-[18px] min-[900px]:pb-3.5">
      <a href="/" aria-label="Confiance home page" className="flex shrink-0 items-center rounded-md py-1 pr-2.5 pl-0.5 outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 min-[900px]:px-2.5 min-[900px]:pb-3.5">
        <img src="/logo-mark.png" alt="Confiance" width={323} height={229} className="h-8 w-auto min-[900px]:h-12" /></a>
      {projects && projects.length > 1 && <Select value={String(pid ?? "")} onChange={v => { setPid(Number(v)); go("overview"); }} label="Choose business" options={projects.map(p => ({ value: String(p.id), label: p.name }))} className="mb-2 max-[899px]:w-40" />}
        {NAV.map(n => (<div key={n.id} className="contents">{n.group && <div className="px-3 pt-3.5 pb-1 text-[0.7rem] tracking-[.09em] text-faint uppercase max-[899px]:hidden">{n.group}</div>}
          <Button kind="text" onClick={() => go(n.id)} aria-current={view === n.id ? "page" : undefined}
            className={cn("relative justify-start gap-2.5 px-3 max-[899px]:px-2.5 min-[900px]:w-full", view === n.id && "bg-card font-semibold text-foreground shadow-sm ring-1 ring-border hover:bg-card min-[900px]:before:absolute min-[900px]:before:inset-y-2 min-[900px]:before:left-0 min-[900px]:before:w-[3px] min-[900px]:before:rounded-full min-[900px]:before:bg-brand")}>
            <Icon n={n.icon} size={19} /><span className={cn(view !== n.id && "max-[899px]:hidden")}>{n.label}</span>
            {n.id === "plan" && open > 0 && <Tooltip><TooltipTrigger asChild><Badge tone="clay" className="ml-auto">{open}</Badge></TooltipTrigger><TooltipContent>Actions to do first</TooltipContent></Tooltip>}
            {n.id === "settings" && driftAlerts > 0 && <Badge tone="clay" className="ml-auto">!</Badge>}</Button></div>))}
        <div className="mt-auto pt-2.5 max-[899px]:hidden"><Button kind="text" size="small" onClick={() => setAdding(true)}><Icon n="plus" size={16} />Add a business</Button></div>
      <Button kind="text" size="small" role="switch" aria-checked={wanted === "dark"} aria-label="Dark mode" onClick={toggle}
        className="justify-start max-[899px]:ml-auto">
        <Icon n={wanted === "dark" ? "moon" : "sun"} size={16} /><span className="max-[899px]:hidden">{wanted === "dark" ? "Dark mode" : "Light mode"}</span></Button>
    </aside>}
    <main className="min-w-0">{body}</main>
    <Toaster />
  </div></TooltipProvider>);
}
