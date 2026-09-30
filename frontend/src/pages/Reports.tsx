import { useEffect, useState } from "react";
import { VERDICT, isWorking } from "../copy";
import { useApi } from "../hooks";
import { Badge, Button, Empty, Icon, PageHead, Select, Skeleton, ago } from "../ui";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import type { Go } from "../App";

export default function Reports({ project, ctx }: { project: any; ctx: any; go: Go }) {
  const runs = useApi<any[]>(`/projects/${project.id}/runs`);
  const list = (runs.data ?? []).filter(r => !isWorking(r) && r.status !== "cancelled" && r.summary?.baseline_batch);
  const [sel, setSel] = useState<number | null>(ctx?.run ?? null);
  useEffect(() => { if (sel == null && list.length) setSel(list[0].id); }, [list.length]);
  const verdict = (r: any) => r.summary?.evaluation?.verdict;
  return (<div className="page wide">
    <PageHead title="Reports" sub="A complete, shareable write-up of each round: findings, research, tests, recommendations and the plan." actions={sel != null && <>
      <Button kind="quiet" asChild><a href={`/api/runs/${sel}/report.html?download=true`}><Icon n="download" size={16} />HTML</a></Button>
      <Button kind="quiet" asChild><a href={`/api/runs/${sel}/report.md`}><Icon n="download" size={16} />Markdown</a></Button>
      <Button kind="quiet" onClick={() => (document.getElementById("rep") as HTMLIFrameElement)?.contentWindow?.print()}><Icon n="print" size={16} />Print / PDF</Button></>} />
    {!runs.data ? <Skeleton h={400} /> : list.length === 0 ? <Empty title="No reports yet">A report is written when a round finishes testing.</Empty> : (<div className="grid items-start gap-4 min-[900px]:grid-cols-[208px_minmax(0,1fr)]">
      <div className="min-[900px]:hidden"><Select value={String(sel ?? "")} onChange={v => setSel(Number(v))} label="Choose a round" options={list.map(r => ({ value: String(r.id), label: `Round ${r.iteration} · ${ago(r.created_at)}${verdict(r) ? ` · ${VERDICT[verdict(r).label]?.label}` : ""}` }))} /></div>
      <nav aria-label="Rounds" className="max-[899px]:hidden"><h2 className="mb-2 px-1 text-base">Rounds</h2>
        <ScrollArea className="h-[calc(100vh-13rem)] min-h-[320px]"><div className="flex flex-col gap-1 pr-3">{list.map(r => (
          <Button key={r.id} kind="text" onClick={() => setSel(r.id)} aria-current={sel === r.id ? "true" : undefined}
            className={cn("h-auto flex-col items-start gap-1 px-3 py-2 text-left whitespace-normal", sel === r.id && "bg-card font-semibold text-foreground shadow-sm ring-1 ring-border hover:bg-card")}>
            <span>Round {r.iteration}<span className="text-muted-foreground text-[0.78rem] font-normal"> · {ago(r.created_at)}</span></span>
            {verdict(r) && <Badge tone={VERDICT[verdict(r).label]?.tone}>{VERDICT[verdict(r).label]?.label}</Badge>}</Button>))}</div></ScrollArea></nav>
      {sel != null && <iframe id="rep" key={sel} title="Report" src={`/api/runs/${sel}/report.html`} sandbox="allow-same-origin allow-modals" className="h-[calc(100vh-13rem)] min-h-[520px] w-full rounded-xl border bg-white" />}</div>)}
  </div>);
}
