import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { HIDDEN_ACTIONS, describeAction } from "../copy";
import { useApi } from "../hooks";
import { Banner, Button, Check, Empty, Icon, PageHead, Select, Skeleton, Tabs } from "../ui";
import { EventList, type AuditRow } from "@/components/EventLog";
import { Input } from "@/components/ui/input";
import type { Go } from "../App";

const PAGE = 200;
type Who = "all" | "user" | "system";

export default function Activity({ project, ctx }: { project: any; go: Go; ctx?: any }) {
  const first = useApi<AuditRow[]>(`/audit?project_id=${project.id}&limit=${PAGE}`, { poll: 15000 });
  const runs = useApi<any[]>(`/projects/${project.id}/runs`);
  const names = useMemo(() => Object.fromEntries((runs.data ?? []).map(r => [r.id, r.iteration])), [runs.data]);
  const [older, setOlder] = useState<AuditRow[]>([]);
  const [more, setMore] = useState(true);
  const [loading, setLoading] = useState(false);
  const [who, setWho] = useState<Who>("all");
  const [q, setQ] = useState("");
  const [round, setRound] = useState(ctx?.run ? String(ctx.run) : "");
  const [tech, setTech] = useState(false);
  const [ok, setOk] = useState<null | boolean>(null);
  useEffect(() => { setOlder([]); setMore(true); }, [project.id]);

  const fresh = first.data ?? [];
  const all = useMemo(() => { const seen = new Set(fresh.map(r => r.id)); return [...fresh, ...older.filter(r => !seen.has(r.id))]; }, [fresh, older]);
  const rounds = useMemo(() => [...new Set(all.map(r => r.run_id).filter((x): x is number => x != null))].sort((a, b) => b - a), [all]);
  const rows = all.filter(r => (tech || !HIDDEN_ACTIONS.some(h => r.action.startsWith(h))) && (who === "all" || (who === "user" ? r.actor === "user" : r.actor !== "user")) && (!round || String(r.run_id) === round)
    && (!q.trim() || `${describeAction(r.action)} ${r.action} ${JSON.stringify(r.payload)}`.toLowerCase().includes(q.trim().toLowerCase())));
  const loadOlder = async () => { setLoading(true); try { const last = all[all.length - 1]; const r: AuditRow[] = await api(`/audit?project_id=${project.id}&limit=${PAGE}&before_id=${last.id}`); setOlder(o => [...o, ...r]); if (r.length < PAGE) setMore(false); } finally { setLoading(false); } };
  const filtered = who !== "all" || q || round;

  return (<div className="page">
    <PageHead title="Activity" sub="Everything Confiance did and everything you decided, in order. Click any line to see the full detail."
      actions={<Button kind="quiet" onClick={() => api("/audit/verify").then(r => setOk(!!r.ok))}><Icon n="shield" size={16} />Check it hasn't been altered</Button>} />
    {ok !== null && <div className="mb-4"><Banner kind={ok ? "info" : "bad"}>{ok ? "Nothing in this history has been altered." : "Something in the history doesn't add up. Please investigate."}</Banner></div>}
    <div className="mb-4 flex flex-wrap items-center gap-3">
      <Tabs value={who} onChange={setWho} items={[{ id: "all", label: "Everything" }, { id: "user", label: "What I did" }, { id: "system", label: "What Confiance did" }]} />
      <div className="relative min-w-52 flex-1"><span className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-faint"><Icon n="search" size={16} /></span><Input type="search" value={q} onChange={e => setQ(e.target.value)} placeholder="Search the history" aria-label="Search the history" className="bg-card pl-9" /></div>
      {rounds.length > 0 && <Select value={round} onChange={setRound} label="Filter by round" className="w-44" options={[{ value: "", label: "All rounds" }, ...rounds.map(r => ({ value: String(r), label: `Round ${names[r] ?? r}` }))]} />}
      <Check checked={tech} onChange={setTech}>Technical events</Check></div>
    {!first.data ? <Skeleton h={300} /> : <>
      <EventList rows={rows} showTech={tech} names={names} empty={<Empty title={filtered ? "Nothing matches" : "Nothing yet"}>{filtered ? "Try a different search or filter." : "Things you and Confiance do will appear here."}</Empty>} />
      <div className="row justify-between mt-4"><span className="text-sm text-muted-foreground">Showing {rows.length} event{rows.length === 1 ? "" : "s"}{filtered ? " that match" : ""}.</span>
        {more && all.length >= PAGE && <Button kind="quiet" busy={loading} onClick={loadOlder}>Load older events</Button>}</div></>}
  </div>);
}
