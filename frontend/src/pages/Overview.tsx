import { api } from "../api";
import { Ring, Trend } from "../charts";
import { PRIORITY_TEXT, VERDICT, isWorking } from "../copy";
import { useAction, useApi } from "../hooks";
import { Badge, Button, Card, Empty, Icon, NextStep, PageHead, Skeleton, SkeletonCards, Stat, ago, pct, toast } from "../ui";
import { cn } from "@/lib/utils";
import type { Go } from "../App";

const check = (done: boolean, label: string, sub: string, onClick?: () => void, cta?: string) => (
  <div className="row border-t py-2.5">
    <span className={cn("grid size-6 flex-none place-items-center rounded-full", done ? "bg-primary text-primary-foreground" : "bg-muted text-faint")}>{done ? <Icon n="check" size={14} /> : "·"}</span>
    <div className="flex-1"><b>{label}</b><div className="text-muted-foreground text-sm">{sub}</div></div>{!done && onClick && <Button kind="quiet" size="small" onClick={onClick}>{cta}</Button>}</div>);

export default function Overview({ project, go }: { project: any; go: Go }) {
  const ov = useApi<any>(`/projects/${project.id}/overview`, { poll: 12000 });
  const done = useAction();
  const o = ov.data;
  if (!o) return <div className="page"><PageHead title={project.name} sub={project.domain} /><SkeletonCards n={4} /><div className="mt-4"><Skeleton h={280} /></div></div>;

  const hist: any[] = o.history ?? [];
  const last = hist[hist.length - 1];
  const fs = o.findability;
  const lr = o.latest_round;
  const working = isWorking(lr);
  const tone = (v: number | null | undefined) => (v == null ? undefined : v >= 0.5 ? "good" : v >= 0.2 ? "warn" : "bad") as any;
  const verdict = o.last_finished_round?.verdict;
  const complete = async (id: number) => { await done.run(async () => { await api(`/plan/${id}`, "PATCH", { status: "done" }); toast("Marked as done"); await ov.reload(); }); };

  return (<div className="page">
    <PageHead title={project.name} sub={<>{project.domain} · {o.pages} pages known{o.site_scanned ? <> · scanned {ago(o.site_scanned)}</> : null}</>}
      actions={<Button kind="quiet" onClick={() => go("site")}><Icon n="refresh" size={16} />Re-scan site</Button>} />

    {(() => {
      const open = o.plan_open?.P0 ?? 0;
      if (working) return <NextStep tone="clay" title="A round is running" action={<Button onClick={() => go("optimize")}>Watch it<Icon n="arrow" size={16} /></Button>}>You can leave and come back. It keeps going.</NextStep>;
      if (lr?.stage === "awaiting_approval" && lr.status === "waiting") return <NextStep tone="clay" title={`Review what round ${lr.round} found`} action={<Button onClick={() => go("optimize", { run: lr.id })}>Review<Icon n="arrow" size={16} /></Button>}>Nothing changes on your website until you approve.</NextStep>;
      if (hist.length === 0) return <NextStep title="Start your first round" action={<Button onClick={() => go("optimize")}><Icon n="spark" size={16} />Start a round</Button>}>We'll ask AI assistants your customers' questions, then test improvements. It takes a few minutes and changes nothing on your site.</NextStep>;
      if (open > 0) return <NextStep title={`Do the ${open} most important step${open > 1 ? "s" : ""} in your plan`} action={<Button onClick={() => go("plan")}>Open the plan<Icon n="arrow" size={16} /></Button>}>These are the changes most likely to help. After you make them, run another round to measure the effect.</NextStep>;
      return <NextStep title="Run another round to keep improving" action={<Button onClick={() => go("optimize")}><Icon n="spark" size={16} />Start a round</Button>}>Each round checks where you stand now and tests new ideas.</NextStep>;
    })()}

    <div className="grid g4 mb-4">
      <Stat label="Site health" plain value={<div className="flex items-center gap-3.5"><Ring value={o.site_score} /><div><b>{o.site_score == null ? "Not scanned" : o.site_score >= 80 ? "Healthy" : o.site_score >= 55 ? "Needs work" : "Weak"}</b>
        <div className="text-muted-foreground text-sm">{o.site_findings?.high ? `${o.site_findings.high} high-severity issue${o.site_findings.high > 1 ? "s" : ""}` : "No high-severity issues"}</div></div></div>} />
      <Stat label="Found in real search" value={fs ? `${fs.found} / ${fs.checked}` : "–"} tone={fs && fs.checked ? tone(fs.found / fs.checked) : undefined} sub={fs ? (fs.brand_found ? "Found by your business name" : "Not found by name") : "Run a round to check"} />
      <Stat label="Brand visibility" value={last?.brand != null ? pct(last.brand) : "–"} tone={tone(last?.brand)} sub={last ? `Assistants use your page in ${pct(last.brand_used)} of answers` : "Start your first round"} />
      <Stat label="Product visibility" value={last?.product != null ? pct(last.product) : o.products.active ? "–" : "n/a"} tone={tone(last?.product)} sub={o.products.active ? `${o.products.active} product${o.products.active > 1 ? "s" : ""} tracked` : <Button kind="text" size="small" className="-ml-3" onClick={() => go("products")}>Add products →</Button>} />
    </div>

    <div className="split">
      <div className="space-y-3.5">
        <Card title="Trend across rounds" actions={verdict && <Badge tone={VERDICT[verdict.label]?.tone}>{VERDICT[verdict.label]?.label}</Badge>}>
          {hist.length === 0 ? <Empty title="No rounds yet" action={<Button onClick={() => go("optimize")}>Start your first round</Button>}>Each round measures where you stand and tests improvements. The trend appears here.</Empty> : <>
            <Trend labels={hist.map(h => `R${h.round}`)} series={[{ name: "Brand mentioned", color: "var(--primary)", points: hist.map(h => h.brand) }, { name: "Page used", color: "var(--clay)", points: hist.map(h => h.brand_used) }, { name: "Product named", color: "var(--warning)", points: hist.map(h => h.product) }]} />
            <div className="row text-sm text-muted-foreground gap-4"><span><b className="text-primary">●</b> Brand mentioned</span><span><b className="text-clay">●</b> Your page used</span><span><b className="text-warning">●</b> Product named</span></div></>}
        </Card>
        <Card title="Getting the most from Confiance">
          {check(!!o.site_score, "Scan your website", o.site_score ? `Health score ${o.site_score}/100` : "Reads robots.txt, sitemap, llms.txt and your key pages", () => go("site"), "Scan")}
          {check(hist.length > 0, "Run a round", hist.length ? `${hist.length} round${hist.length > 1 ? "s" : ""} completed` : "Ask AI assistants your customers' questions, then test improvements", () => go("optimize"), "Start")}
          {check(o.plan_total > 0 && o.plan_done > 0, "Work through the plan", o.plan_total ? `${o.plan_done} of ${o.plan_total} steps done` : "The plan appears after your first round", () => go("plan"), "Open plan")}
          {check(hist.some(h => h.real_world != null), "Measure the real result", "After publishing, start another round to see the real effect", () => go("optimize"), "Start")}
        </Card>
      </div>
      <div className="space-y-3.5">
        <Card title="Do these first" actions={o.plan_total > 0 && <Button kind="text" size="small" onClick={() => go("plan")}>Full plan <Icon n="arrow" size={15} /></Button>}>
          {o.top_actions.length === 0 ? <Empty title={o.plan_total ? "You're all caught up" : "No plan yet"}>{o.plan_total ? "Every step in the plan is done or dismissed." : "Your prioritized plan is written at the end of each round."}</Empty> :
            o.top_actions.map((a: any) => (<div key={a.id} className="border-t py-3">
              <div className="row justify-between items-start"><div><Badge tone={a.priority === "P0" ? "bad" : a.priority === "P1" ? "warn" : undefined}>{a.priority} · {PRIORITY_TEXT[a.priority]}</Badge>
                <div className="mt-1 font-semibold">{a.title}</div><div className="text-muted-foreground text-sm">{a.timeframe || `${a.effort} effort`} · {a.owner}</div></div>
                <Button kind="quiet" size="small" busy={done.busy} onClick={() => complete(a.id)}><Icon n="check" size={15} />Done</Button></div></div>))}
        </Card>
        <Card title="Site issues" actions={<Button kind="text" size="small" onClick={() => go("site")}>Details <Icon n="arrow" size={15} /></Button>}>
          {o.site_score == null ? <p className="text-muted-foreground">Scan your site to see technical issues.</p> : <div className="row">{(["high", "medium", "low"] as const).map(s => <Badge key={s} tone={s === "high" ? "bad" : s === "medium" ? "warn" : "clay"}>{o.site_findings?.[s] ?? 0} {s}</Badge>)}
            {o.indexed?.checked && <Badge tone={o.indexed.results ? "good" : "bad"}>{o.indexed.results ? "Indexed" : "Not indexed"}</Badge>}</div>}
          {o.lighthouse?.available && <div className="row mt-3 text-sm text-muted-foreground"><span>Lighthouse:</span>{([["performance", "Speed"], ["accessibility", "Access."], ["seo", "SEO"]] as const).map(([k, l]) => <Badge key={k} tone={o.lighthouse.scores[k] >= 90 ? "good" : o.lighthouse.scores[k] >= 50 ? "warn" : "bad"}>{l} {o.lighthouse.scores[k]}</Badge>)}</div>}
        </Card>
      </div>
    </div>
  </div>);
}
