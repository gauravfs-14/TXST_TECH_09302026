import { useState } from "react";
import { api } from "../api";
import { CATEGORY, PRIORITY_TEXT } from "../copy";
import { useAction, useApi } from "../hooks";
import { Badge, Banner, Button, Card, CodeBlock, Empty, Icon, Meter, PageHead, Select, Skeleton, Tabs, toast } from "../ui";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import type { Go } from "../App";

const STATUS = { todo: "To do", doing: "In progress", done: "Done", dismissed: "Skipped" } as const;
type St = keyof typeof STATUS;
const LEVEL = (x: string | null | undefined) => (x ? x[0].toUpperCase() + x.slice(1) : "–");

export function ActionCard({ a, onChange }: { a: any; onChange: () => void }) {
  const [open, setOpen] = useState(false);
  const act = useAction();
  const set = (status: St) => act.run(async () => { await api(`/plan/${a.id}`, "PATCH", { status }); if (status === "done") toast("Marked as done"); onChange(); });
  const cat = CATEGORY[a.category] ?? { label: a.category };
  const dim = a.status === "done" || a.status === "dismissed";
  return (<Card variant="flat" className={cn(dim && "opacity-65")}>
    <div className="row justify-between items-start">
      <div className="flex-1"><div className="row mb-1.5 gap-1.5"><Badge tone={a.priority === "P0" ? "bad" : a.priority === "P1" ? "warn" : undefined}>{PRIORITY_TEXT[a.priority] ?? a.priority}</Badge><Badge tone={cat.tone as any}>{cat.label}</Badge>
        {a.source === "ai" && <Badge tone="clay"><Icon n="spark" size={12} />Tailored</Badge>}{a.status !== "todo" && <Badge tone={a.status === "done" ? "good" : undefined}>{STATUS[a.status as St]}</Badge>}</div>
        <h3 className="m-0">{a.title}</h3><p className="text-muted-foreground mt-1.5 mb-0">{a.why}</p></div>
      <div className="row gap-1.5">{a.status !== "done" && <Button kind="quiet" size="small" busy={act.busy} onClick={() => set("done")}><Icon n="check" size={15} />Done</Button>}
        <Button kind="text" size="small" onClick={() => setOpen(!open)} aria-expanded={open}>{open ? "Less" : "How"}</Button></div></div>
    <div className="row text-muted-foreground text-[0.78rem] mt-2 gap-3.5"><span>Impact: <b>{LEVEL(a.impact)}</b></span><span>Effort: <b>{LEVEL(a.effort)}</b></span>{a.owner && <span>Who: <b>{a.owner}</b></span>}{a.timeframe && <span>When: <b>{a.timeframe}</b></span>}</div>
    {open && <div className="mt-4">
      {a.steps?.length > 0 && <><h4 className="mb-1.5">Steps</h4><ol className="mb-3 list-decimal pl-5">{a.steps.map((s: string, i: number) => <li key={i} className="mb-1">{s}</li>)}</ol></>}
      {a.targets?.length > 0 && <p className="text-sm"><b>Applies to:</b> {a.targets.map((t: string) => <code key={t} className="font-mono mr-2">{t}</code>)}</p>}
      {a.draft?.content && <CodeBlock label="Ready to use. Copy it, or save it as a file" content={a.draft.content} filename={a.draft.filename} />}
      {a.verify && <p className="text-sm"><Icon n="check" size={14} /> <b>How you'll know it worked:</b> {a.verify}</p>}
      {a.evidence?.length > 0 && <Collapsible className="text-sm text-muted-foreground"><CollapsibleTrigger className="cursor-pointer underline-offset-4 hover:underline">Why we're saying this</CollapsibleTrigger><CollapsibleContent><ul className="mt-1.5 list-disc pl-5">{a.evidence.map((e: any, i: number) => <li key={i}>{typeof e === "string" ? e : JSON.stringify(e)}</li>)}</ul></CollapsibleContent></Collapsible>}
      <div className="row mt-4">{(["todo", "doing", "dismissed"] as St[]).filter(s => s !== a.status).map(s => <Button key={s} kind="text" size="small" onClick={() => set(s)}>{s === "todo" ? "Move back to To do" : s === "doing" ? "Mark in progress" : "Skip this"}</Button>)}</div></div>}
  </Card>);
}

export default function Plan({ project, go }: { project: any; go: Go }) {
  const p = useApi<any>(`/projects/${project.id}/plan`);
  const [f, setF] = useState<"open" | "all" | "done">("open");
  const [cat, setCat] = useState("all");
  if (!p.data) return <div className="page"><PageHead title="Improvement plan" /><Skeleton h={300} /></div>;
  const all: any[] = p.data.actions;
  if (!all.length) return <div className="page"><PageHead title="Improvement plan" sub="A prioritized to-do list written for your business." /><Empty title="No plan yet" action={<Button onClick={() => go("optimize")}>Start a round</Button>}>Your plan is written at the end of each round, using your site scan, research and test results.</Empty></div>;
  const open = all.filter(a => a.status === "todo" || a.status === "doing");
  const done = all.filter(a => a.status === "done");
  const shown = all.filter(a => (f === "all" || (f === "open" ? a.status === "todo" || a.status === "doing" : a.status === "done" || a.status === "dismissed")) && (cat === "all" || a.category === cat));
  const cats = Array.from(new Set(all.map(a => a.category)));
  const pctDone = Math.round(100 * done.length / all.length);
  return (<div className="page">
    <PageHead title="Improvement plan" sub={p.data.initial ? "Your starting plan, written from the site scan. In order, most valuable first. It updates after each round." : `From round ${p.data.round}. In order, most valuable first.`} actions={p.data.run_id != null && <Button kind="quiet" onClick={() => go("reports", { run: p.data.run_id })}><Icon n="file" size={16} />Full report</Button>} />
    <Card variant="hero"><div className="row justify-between"><div><b>{done.length} of {all.length} steps done</b><div className="text-muted-foreground text-sm">{open.filter(a => a.priority === "P0").length} high-priority step(s) left</div></div><span className="tabular-nums font-serif text-3xl font-semibold">{pctDone}%</span></div>
      <div className="mt-2.5"><Meter value={pctDone / 100} after /></div></Card>
    <div className="row justify-between mt-4 mb-4"><Tabs value={f} onChange={setF} items={[{ id: "open", label: `To do (${open.length})` }, { id: "done", label: `Finished (${all.length - open.length})` }, { id: "all", label: "Everything" }]} />
      <Select value={cat} onChange={setCat} label="Filter by type" className="w-44" options={[{ value: "all", label: "All types" }, ...cats.map(c => ({ value: c, label: CATEGORY[c]?.label ?? c }))]} /></div>
    {shown.length === 0 ? <Banner kind="info">Nothing here.</Banner> : <div className="space-y-3.5">{shown.map(a => <ActionCard key={a.id} a={a} onChange={p.reload} />)}</div>}
  </div>);
}
