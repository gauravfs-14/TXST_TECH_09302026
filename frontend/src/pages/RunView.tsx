import { useEffect, useState } from "react";
import { api } from "../api";
import { LoopBars } from "../charts";
import { HIDDEN_ACTIONS, STOP_REASON, VERDICT, friendlyError, describeOp, friendlyBlock, pathOf, pageName } from "../copy";
import { useAction, useApi } from "../hooks";
import { Markdown } from "../md";
import { Answer, Badge, Banner, Button, Card, Check, CodeBlock, Empty, Icon, Meter, Select, Skeleton, TableBox, Tabs, pct, signed, toast } from "../ui";
import { Separator } from "@/components/ui/separator";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";
import type { Go } from "../App";
import Progress, { Stepper } from "./Progress";
import { TaskFeed } from "../task";
import { EventList, type AuditRow } from "@/components/EventLog";

type Tab = "summary" | "loops" | "changes" | "answers" | "log";
const FUNNEL: [string, string][] = [["exposed", "Your page was in front of the assistant"], ["fetched", "The assistant opened it"], ["used_page", "The answer used its content"], ["mentioned", "The answer named your business"], ["cited", "The answer linked to your site"]];

function Funnel({ before, after }: { before: any; after: any }) {
  if (!before || !after) return <p className="text-muted-foreground">No test results yet.</p>;
  return (<div className="funnel"><span className="h">Step</span><span className="h">Before</span><span /><span className="h">After</span><span />
    {FUNNEL.map(([k, label]) => (<><span key={k + "l"}>{label}</span><Meter value={before[k]} /><b className="tabular-nums">{pct(before[k])}</b><Meter value={after[k]} after /><b className="tabular-nums">{pct(after[k])}</b></>))}</div>);
}

function Deliver({ s, reload }: { s: any; reload: () => void }) {
  const d = s.deployment; const { busy, error, run } = useAction();
  if (!d) return null;
  return (<Card variant="hero"><h2>Your improvements are ready to publish</h2>
    {d.how === "export" ? (<><p>Download the package and give it to whoever looks after your website. It has the improved pages, any brand-new pages, the site files from your plan, and the full report. <b>Nothing on your live site has changed yet.</b></p>
      <Button size="big" asChild><a href={`/api/deployments/${d.id}/download`}><Icon n="download" />Download the package</a></Button></>) : <p>The changes are waiting: {d.where}.</p>}
    <Separator className="my-4" /><p><b>Once the changes are on your website</b>, tell us, and we'll schedule the real-world check.</p>
    {error && <Banner kind="bad">{error}</Banner>}
    <Button kind="quiet" busy={busy} onClick={() => run(async () => { await api(`/deployments/${d.id}/confirm-live`, "POST"); toast("Marked as live"); reload(); })}><Icon n="check" size={16} />The changes are now on my website</Button></Card>);
}

function Changes({ s, props, reload, runId }: { s: any; props: any[]; reload: () => void; runId: number }) {
  const qtext: Record<string, string> = Object.fromEntries((s.questions ?? []).map((q: any) => [q.id, q.text]));
  const cands = props.filter(p => p.status === "candidate");
  const [picked, setPicked] = useState<number[]>(cands.map(c => c.id));
  useEffect(() => setPicked(cands.map(c => c.id)), [props.length, s.stage]);
  const [open, setOpen] = useState<number | null>(null);
  const blocked = props.filter(p => p.status === "blocked");
  const approved = props.filter(p => ["approved", "deployed"].includes(p.status));
  const { busy, error, key, run } = useAction();
  const decide = (approve: boolean) => run(async (task) => { await api(`/runs/${runId}/decide`, "POST", { proposal_ids: approve ? picked : cands.map(c => c.id), approve }, { task }); toast(approve ? "Approved. Preparing your package…" : "Skipped"); reload(); });
  const exact = (p: any) => p.ops.map((o: any) => o.type === "create_page" ? `NEW PAGE ${o.path}\nTitle: ${o.title}\nDescription: ${o.meta_description}\n\n${o.html}` : describeOp(o) + (o.html ? `\n${o.html}` : o.items ? `\n${o.items.map((i: any) => `Q: ${i.q}\nA: ${i.a}`).join("\n\n")}` : o.json ? `\n${o.json}` : "")).join("\n\n———\n\n");
  const group = (title: string, list: any[]) => list.length > 0 && (<div className="mb-4"><h3 className="mb-2">{title} <span className="text-muted-foreground text-sm">({list.length})</span></h3>
    {list.map(p => (<Card key={p.id} variant="flat" tight className="mb-2.5">
      <Check className="items-start" checked={picked.includes(p.id)} onChange={() => setPicked(cur => cur.includes(p.id) ? cur.filter(x => x !== p.id) : [...cur, p.id])}>
        <span className="flex-1"><span className="row"><b className="font-mono text-[0.9rem]">{pathOf(p.url)}</b>{p.kind === "new_page" && <Badge tone="good">New page</Badge>}<Badge>Loop {p.loop}</Badge><Badge tone="good"><Icon n="shield" size={12} />Passed safety checks</Badge></span>
          <ul className="mt-1.5 mb-1 list-disc pl-[1.1rem] font-normal">{p.ops.map((o: any, i: number) => <li key={i}>{describeOp(o)}</li>)}</ul>
          <span className="text-muted-foreground text-sm block font-normal"><b>Why:</b> {p.rationale}</span>
          {p.target_questions?.length > 0 && <div className="text-muted-foreground text-sm mt-1 font-normal"><b>Helps with:</b> {p.target_questions.map((q: string) => `“${qtext[q] ?? q}”`).join(" · ")}</div>}</span></Check>
      <Button kind="text" size="small" onClick={() => setOpen(open === p.id ? null : p.id)}>{open === p.id ? "Hide the exact wording" : "Show the exact wording"}</Button>
      {open === p.id && <CodeBlock label="Exactly what will change" content={exact(p)} />}</Card>))}</div>);
  if (!cands.length && !approved.length && !blocked.length) return <Empty title="No changes this round">No safe changes could be drafted for these questions.</Empty>;
  return (<div>
    {s.verdict && s.verdict.label !== "improved" && cands.length > 0 && <div className="mb-4"><Banner kind="warn"><b>The sandbox didn't show a clear improvement.</b> {s.verdict.text} You can still publish changes you like, but expect little effect.</Banner></div>}
    {cands.length > 0 && <>{group("New pages", cands.filter(p => p.kind === "new_page"))}{group("Edits to existing pages", cands.filter(p => p.kind !== "new_page"))}
      {error && <Banner kind="bad">{error}</Banner>}
      <TaskFeed task={key} on={busy} title="Preparing your package" />
      <div className="row"><Button size="big" busy={busy} disabled={!picked.length} onClick={() => decide(true)}>Approve {picked.length} change{picked.length === 1 ? "" : "s"}</Button>
        <Button kind="text" onClick={() => setPicked(picked.length === cands.length ? [] : cands.map(c => c.id))}>{picked.length === cands.length ? "Select none" : "Select all"}</Button>
        <Button kind="danger" onClick={() => confirm("Skip all of these suggestions?") && decide(false)}>Not now</Button></div></>}
    {approved.length > 0 && <div className="mt-4"><h3>Approved</h3>{approved.map(p => <p key={p.id} className="my-1.5"><b className="font-mono">{pathOf(p.url)}</b> <span className="text-muted-foreground">{p.ops.map(describeOp).join("; ")}</span></p>)}</div>}
    {blocked.length > 0 && <Card variant="sunk" className="mt-4"><h3>Ideas blocked to keep you safe</h3><p className="text-muted-foreground text-sm">Our checks stopped these before they reached you.</p>
      {blocked.map(p => <p key={p.id} className="text-sm my-1"><b className="font-mono">{pathOf(p.url)}</b> {friendlyBlock((p.guard_report?.violations ?? [""])[0])}</p>)}</Card>}
  </div>);
}

function Answers({ s }: { s: any }) {
  const [sel, setSel] = useState<string>(s.questions?.[0]?.id);
  const q = s.questions?.find((x: any) => x.id === sel) ?? s.questions?.[0];
  if (!q) return <Empty title="No answers yet" />;
  return (<div className="space-y-3.5">
    <div className="row"><div className="min-w-[260px] flex-1"><Select value={q.id} onChange={setSel} label="Question" className="text-left" options={s.questions.map((x: any) => ({ value: x.id, label: `${x.track === "product" ? "🛍 " : ""}${x.text}` }))} /></div>
      {!q.retested && <Badge>Not re-asked (unaffected)</Badge>}</div>
    <div className="grid g2"><div><h4 className="mb-1.5">Today</h4><Answer><Markdown text={q.before_answer} /></Answer></div>
      <div><h4 className="mb-1.5 text-primary">With the changes</h4><Answer>{q.retested ? <Markdown text={q.after_answer} /> : <p className="text-muted-foreground">This question wasn't affected by the changes, so it wasn't asked again.</p>}</Answer></div></div>
    <p className="text-muted-foreground text-sm">Full answers as the assistant wrote them. Your page was placed among the search results in both rounds, so the difference comes from your content.</p></div>);
}

function Log({ runId }: { runId: number }) {
  const [tech, setTech] = useState(false);
  const a = useApi<AuditRow[]>(`/audit?run_id=${runId}&limit=1000`);
  const rows = (a.data ?? []).filter(r => tech || !HIDDEN_ACTIONS.some(h => r.action.startsWith(h)));
  return (<div className="space-y-3.5"><div className="row justify-between"><p className="m-0 text-sm text-muted-foreground">Everything recorded during this round, newest first. Click a line for the full detail.</p><Check checked={tech} onChange={setTech}>Technical events</Check></div>
    {!a.data ? <Skeleton h={220} /> : <EventList rows={rows} showTech={tech} empty={<Empty title="Nothing recorded">No events were saved for this round.</Empty>} />}</div>);
}

export default function RunView({ runId, go }: { runId: number; go: Go }) {
  const sum = useApi<any>(`/runs/${runId}`, { poll: 3000 });
  const working = sum.data && (sum.data.status === "running" || sum.data.status === "pending");
  const settled = sum.data && !working;
  const s = useApi<any>(settled ? `/runs/${runId}/summary` : null, { poll: settled && ["awaiting_live", "awaiting_measure", "deploy"].includes(sum.data.stage) ? 4000 : undefined, deps: [sum.data?.stage, sum.data?.status] });
  const props = useApi<any[]>(settled ? `/runs/${runId}/proposals` : null, { deps: [sum.data?.stage] });
  const loops = useApi<any>(settled ? `/runs/${runId}/loops` : null, { deps: [sum.data?.stage] });
  const [tab, setTab] = useState<Tab>("summary");
  const [undo, setUndo] = useState<number | null>(null);
  const act = useAction();
  const reload = () => { sum.reload(); s.reload(); props.reload(); };

  if (!sum.data) return <div className="space-y-3.5"><Skeleton h={90} /><Skeleton h={260} /></div>;
  const r = sum.data;
  if (working) return <Progress runId={runId} stage={r.stage} onChange={sum.reload} go={go} />;
  if (r.status === "failed") return (<Card><Stepper stage={r.stage} failed /><div className="mt-4"><Banner kind="bad"><b>This round hit a problem.</b><br />{friendlyError(r.error).text}</Banner></div>
    <div className="row mt-4"><Button busy={act.busy} onClick={() => act.run(async () => { await api(`/runs/${runId}/advance`, "POST"); toast("Trying again from where it stopped"); setTimeout(sum.reload, 800); })}><Icon n="refresh" size={16} />Try again</Button><span className="text-muted-foreground text-sm">Finished stages are kept, so nothing is repeated.</span></div>
    <div className="mt-6"><h3 className="mb-2">What happened</h3>{r.error && <p className="mb-3 text-sm text-muted-foreground">Technical message: <span className="font-mono break-all">{friendlyError(r.error).raw.slice(0, 400)}</span></p>}<Log runId={runId} /></div></Card>);
  if (r.status === "cancelled") return <Card><h2>This round was stopped</h2><p className="text-muted-foreground">Nothing was changed on your website. Start a new round whenever you like.</p><h3 className="mt-5 mb-2">What happened before it stopped</h3><Log runId={runId} /></Card>;
  if (!s.data) return <div className="space-y-3.5"><Skeleton h={90} /><Skeleton h={260} /></div>;

  const d = s.data, v = d.verdict, best = (loops.data?.loops ?? []).find((l: any) => l.n === d.best_loop);
  const cands = (props.data ?? []).filter(p => p.status === "candidate").length;
  const tabs = [{ id: "summary" as Tab, label: "Summary" }, { id: "loops" as Tab, label: `Loops${loops.data?.loops?.length ? ` (${loops.data.loops.length})` : ""}` }, { id: "changes" as Tab, label: `Changes${cands ? ` (${cands})` : ""}` }, { id: "answers" as Tab, label: "Answers" }, { id: "log" as Tab, label: "Log" }];
  const fs = d.findability_summary;

  return (<div className="space-y-3.5">
    <Card><Stepper stage={r.stage} /></Card>
    {r.stage === "awaiting_live" && <Deliver s={d} reload={reload} />}
    {r.stage === "awaiting_measure" && <Banner kind="info"><b>Your changes are live.</b> We'll check the real effect {d.measure_after ? `from ${new Date(d.measure_after).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" })}` : "in a few days"}; assistants need a little time to notice.</Banner>}
    {r.stage === "done" && d.live_before && d.live_after && <Card variant="hero"><h2>Real result after publishing</h2><div className="row my-3 gap-7">
      <div><div className="tabular-nums font-serif text-4xl font-semibold text-muted-foreground">{pct(d.live_before.mentioned)}</div><span className="text-muted-foreground text-sm">named you before</span></div><span className="text-2xl text-faint">→</span>
      <div><div className="tabular-nums font-serif text-4xl font-semibold text-primary">{pct(d.live_after.mentioned)}</div><span className="text-sm">after</span></div></div></Card>}

    <div className="row justify-between"><Tabs value={tab} onChange={setTab} items={tabs} />
      <div className="row"><Button kind="quiet" size="small" onClick={() => go("plan")}><Icon n="list" size={15} />Improvement plan</Button><Button kind="quiet" size="small" onClick={() => go("reports", { run: runId })}><Icon n="file" size={15} />Full report</Button></div></div>

    {tab === "summary" && (<div className="space-y-3.5">
      <Card variant="hero"><div className="row justify-between items-start"><div><span className="text-muted-foreground text-[0.78rem] tracking-[.08em]">SANDBOX RESULT</span>
        <h2 className="mt-1 mb-1.5">{v ? (VERDICT[v.label]?.label ?? v.label) : "No result"}</h2></div>{v && <Badge tone={VERDICT[v.label]?.tone}>{d.loops?.length ?? 0} loop{(d.loops?.length ?? 0) === 1 ? "" : "s"} · best: {d.best_loop ?? "–"}</Badge>}</div>
        <p className="text-[1.02rem]">{v?.text}</p>
        {d.stop_reason && <p className="text-muted-foreground text-sm">The loop ended because {STOP_REASON[d.stop_reason] ?? d.stop_reason}.</p>}
        {d.narrative && <><Separator className="my-4" /><p>{d.narrative}</p></>}
        <div className="row mt-4">{cands > 0 && r.stage === "awaiting_approval" && <Button onClick={() => setTab("changes")}>Review {cands} change{cands > 1 ? "s" : ""}<Icon n="arrow" size={16} /></Button>}<Button kind="quiet" onClick={() => go("plan")}>Open the improvement plan</Button></div></Card>
      <div className="split">
        <Card title="How assistants treat your page" ><Funnel before={best?.funnel_base} after={best?.funnel_now} />
          <p className="text-muted-foreground text-sm mt-3">Your page was placed among the search results in both the before and after tests, at the same position, so this shows how much better the page works, not luck in ranking.</p></Card>
        <div className="space-y-3.5">
          {d.by_track && <Card title="By what we measured">{(["brand", "product"] as const).map(t => d.by_track[t] && d.by_track[t].pairs > 0 && (<div key={t} className="row justify-between border-t py-2">
            <span><b>{t === "brand" ? "Brand questions" : "Product questions"}</b><div className="text-muted-foreground text-[0.78rem]">{d.by_track[t].pairs} comparisons</div></span><span className={cn(d.by_track[t].delta >= 0.05 && "font-semibold text-primary", d.by_track[t].delta <= -0.05 && "font-semibold text-destructive")}>{signed(d.by_track[t].delta)}</span></div>))}</Card>}
          {fs && <Card title="Real search today"><p className="mb-0">Search shows your site for <b>{fs.questions_found} of {fs.questions_checked}</b> questions{fs.brand_found ? ", and finds you by name." : ", and doesn't find you by name."}</p>
            <Button kind="text" size="small" onClick={() => go("visibility", { tab: "discover" })}>See who wins instead <Icon n="arrow" size={15} /></Button></Card>}
        </div></div></div>)}

    {tab === "loops" && (loops.data ? (<div className="space-y-3.5">
      <Card title="Change in score, loop by loop" actions={<Badge>Limit: {loops.data.config?.max_loops} loops</Badge>}>
        {loops.data.loops.length ? <LoopBars loops={loops.data.loops.map((l: any) => ({ n: l.n, delta: l.delta?.delta ?? null }))} best={loops.data.best_loop} /> : <p className="text-muted-foreground">No loops ran.</p>}
        <p className="text-muted-foreground text-sm">Each loop drafts changes, tests them in the sandbox, and decides whether another loop is worth it. The best loop (★) is the one you'll review, not necessarily the last.</p></Card>
      <TableBox><Table><TableHeader><TableRow><TableHead>Loop</TableHead><TableHead>Changes</TableHead><TableHead>Questions tested</TableHead><TableHead>Change</TableHead><TableHead>Verdict</TableHead><TableHead>Decision</TableHead></TableRow></TableHeader><TableBody>
        {loops.data.loops.map((l: any) => (<TableRow key={l.n}><TableCell><b>{l.n}</b>{l.n === loops.data.best_loop && " ★"}</TableCell><TableCell>{l.proposals}</TableCell><TableCell>{l.tested?.length ?? "–"}</TableCell>
          <TableCell className="tabular-nums">{signed(l.delta?.delta)}<div className="text-muted-foreground text-[0.78rem]">{l.delta?.ci ? `${signed(l.delta.ci[0])} to ${signed(l.delta.ci[1])}` : ""}</div></TableCell>
          <TableCell className="whitespace-normal">{l.verdict ? <Badge tone={VERDICT[l.verdict.label]?.tone}>{VERDICT[l.verdict.label]?.label}</Badge> : "–"}<div className="text-muted-foreground text-[0.78rem] max-w-[260px]">{l.verdict?.text}</div></TableCell>
          <TableCell className="text-sm whitespace-normal">{STOP_REASON[l.decision] ?? l.decision}{l.not_improved?.length ? <div className="text-muted-foreground text-[0.78rem]">Didn't improve: {l.not_improved.length} question(s)</div> : null}</TableCell></TableRow>))}</TableBody></Table></TableBox></div>) : <Skeleton h={220} />)}

    {tab === "changes" && (props.data ? <Changes s={d} props={props.data} reload={reload} runId={runId} /> : <Skeleton h={220} />)}
    {tab === "answers" && <Answers s={d} />}
    {tab === "log" && <Log runId={runId} />}

    {["awaiting_measure", "done"].includes(r.stage) && d.deployment?.status === "applied" && (<Card variant="sunk"><div className="row justify-between"><div><b>Changed your mind?</b><br /><span className="text-muted-foreground text-sm">You can put your pages back exactly as they were.</span></div>
      <Button kind="danger" busy={act.busy} onClick={() => confirm("Undo these changes and go back to your original pages?") && act.run(async () => { const x = await api(`/deployments/${d.deployment.id}/rollback`, "POST"); setUndo(x.rollback_id); reload(); })}><Icon n="undo" size={16} />Undo these changes</Button></div>
      {undo && <div className="mt-4"><p>Download your original pages, put them back on your website, then tell us it's done.</p><div className="row"><Button kind="quiet" asChild><a href={`/api/deployments/${undo}/download`}><Icon n="download" size={16} />Download original pages</a></Button>
        <Button kind="quiet" onClick={() => act.run(async () => { await api(`/deployments/${undo}/confirm-live`, "POST"); setUndo(null); reload(); })}>They're back on my website</Button></div></div>}</Card>)}
  </div>);
}

export { pageName };
