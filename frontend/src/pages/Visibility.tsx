import { useState } from "react";
import { FIT, assistant, pageName, pathOf } from "../copy";
import { useApi } from "../hooks";
import { Answer, Badge, Banner, Button, Card, Empty, Icon, Meter, PageHead, Skeleton, Stat, TableBox, Tabs, pct, signed } from "../ui";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Markdown } from "../md";
import { cn } from "@/lib/utils";
import type { Go } from "../App";

type Tab = "brand" | "product" | "discover";

function QuestionRow({ q }: { q: any }) {
  const [open, setOpen] = useState(false);
  const fit = q.fit ? FIT[q.fit] : null;
  return (<div className="border-t py-3">
    <div className="row justify-between items-start"><div className="flex-1"><b>{q.text}</b>
      <div className="row mt-1 gap-1.5">{fit && <Badge tone={fit.tone}>{fit.label}</Badge>}{q.search_rank ? <Badge>Search rank #{q.search_rank}</Badge> : <Badge tone="warn">Not in search results</Badge>}{q.product && <Badge>{q.product}</Badge>}</div></div>
      <div className="min-w-[190px]"><div className="row justify-between text-sm"><span>Named you</span><b className="tabular-nums">{pct(q.before.mentioned)}</b></div><Meter value={q.before.mentioned} />
        <div className="row justify-between text-sm mt-1"><span>Used your page</span><b className="tabular-nums">{pct(q.before.used)}</b></div><Meter value={q.before.used} /></div></div>
    {q.fit_reason && <p className="text-muted-foreground text-sm mt-1.5 mb-0">{q.fit_reason}</p>}
    <Button kind="text" size="small" onClick={() => setOpen(!open)}>{open ? "Hide the answer" : "Read the answer"}</Button>
    {open && <Answer><Markdown text={q.before_answer || "No answer recorded."} /></Answer>}</div>);
}

export default function Visibility({ project, ctx, go }: { project: any; ctx: any; go: Go }) {
  const ov = useApi<any>(`/projects/${project.id}/overview`);
  const rid = ov.data?.last_finished_round?.id;
  const s = useApi<any>(rid ? `/runs/${rid}/summary` : null);
  const [tab, setTab] = useState<Tab>(ctx?.tab === "discover" ? "discover" : "brand");
  if (!ov.data || (rid && !s.data)) return <div className="page"><PageHead title="Visibility" /><Skeleton h={340} /></div>;
  if (!rid) return <div className="page"><PageHead title="Visibility" sub="How AI assistants and search treat your business." /><Empty title="Nothing measured yet" action={<Button onClick={() => go("optimize")}>Start a round</Button>}>A round asks assistants your customers' questions and checks real search.</Empty></div>;
  const d = s.data, qs: any[] = d.questions ?? [];
  const brand = qs.filter(q => q.track !== "product"), prod = qs.filter(q => q.track === "product");
  const avg = (l: any[], k: string) => (l.length ? l.reduce((a, q) => a + (q.before[k] || 0), 0) / l.length : null);
  const fs = d.findability_summary, r = d.research ?? {}, comps: any[] = r.competitors ?? [], pat = r.patterns ?? {};
  const fitCount = (f: string) => qs.filter(q => q.fit === f).length;
  const byProduct: Record<string, any[]> = {};
  prod.forEach(q => (byProduct[q.product || "Other"] ??= []).push(q));
  return (<div className="page">
    <PageHead title="Visibility" sub={`From round ${ov.data.last_finished_round.round}. Two different questions: can people find you in search, and does an assistant use your page once it does?`} />
    <div className="grid g4 mb-4">
      <Stat label="Found in real search" value={fs ? `${fs.questions_found} / ${fs.questions_checked}` : "–"} sub={fs?.brand_found ? "Found by your name" : "Not found by your name"} />
      <Stat label="Assistants name you (brand)" value={pct(avg(brand, "mentioned"))} sub={`${brand.length} questions`} />
      <Stat label="Assistants use your page" value={pct(avg(brand, "used"))} sub="When it's in front of them" />
      <Stat label="Named for products" value={prod.length ? pct(avg(prod, "product_named")) : "n/a"} sub={prod.length ? `${prod.length} shopper questions` : "Add products to track"} />
    </div>
    <div className="mb-4"><Tabs value={tab} onChange={setTab} items={[{ id: "brand", label: `Brand (${brand.length})` }, { id: "product", label: `Products (${prod.length})` }, { id: "discover", label: "Discoverability" }]} /></div>
    {tab === "brand" && <Card>{brand.length ? brand.map(q => <QuestionRow key={q.id} q={q} />) : <Empty title="No brand questions in this round" />}
      <p className="text-muted-foreground text-sm">"Named you" means the assistant's answer mentioned your business. Your page was placed in the search results for these tests, so this measures how well the assistant uses it.</p></Card>}
    {tab === "product" && (prod.length ? <div className="space-y-3.5">{Object.entries(byProduct).map(([name, list]) => (<Card key={name} title={name}>{list.map(q => <QuestionRow key={q.id} q={q} />)}</Card>))}</div>
      : <Empty title="No product questions yet" action={<Button onClick={() => go("products")}>Manage products</Button>}>Add your products and Confiance will test how shoppers' questions rank them.</Empty>)}
    {tab === "discover" && (<div className="space-y-3.5">
      <Banner kind={fs?.brand_found ? "info" : "warn"}>{fs?.brand_found ? <>Real search finds you when someone types your business name.</> : <><b>Real search doesn't find you by name.</b> Getting indexed comes first, and the plan starts there.</>}</Banner>
      <div className="grid g3"><Stat label="Already winning" value={fitCount("winning")} tone="good" sub="Shown near the top" /><Stat label="Within reach" value={fitCount("in_reach")} tone="warn" sub="Content exists or you're on the list" /><Stat label="Needs new content" value={fitCount("needs_content")} tone="bad" sub="Your site doesn't cover it" /></div>
      <Card title="Question by question">{qs.filter(q => q.track !== "product").concat(prod).map((q, i) => (<div key={q.id} className={cn("row justify-between py-2.5", i > 0 && "border-t")}>
        <span className="flex-1">{q.text}<div className="text-muted-foreground text-[0.78rem]">{q.fit_reason}</div></span>{q.fit && <Badge tone={FIT[q.fit]?.tone}>{FIT[q.fit]?.label}</Badge>}</div>))}</Card>
      {comps.length > 0 && <Card title="Who search shows instead"><TableBox><Table><TableHeader><TableRow><TableHead>Site</TableHead><TableHead>Page</TableHead><TableHead>Words</TableHead><TableHead>Structured data</TableHead><TableHead>FAQ</TableHead></TableRow></TableHeader><TableBody>
        {comps.slice(0, 10).map((c, i) => <TableRow key={i}><TableCell><b>{c.domain}</b></TableCell><TableCell className="text-sm whitespace-normal">{c.title || pathOf(c.url)}</TableCell><TableCell className="tabular-nums">{c.words}</TableCell><TableCell className="text-sm whitespace-normal">{(c.schema_types ?? []).slice(0, 3).join(", ") || "none"}</TableCell><TableCell>{c.has_faq ? "Yes" : "–"}</TableCell></TableRow>)}</TableBody></Table></TableBox>
        {pat.pages > 0 && <p className="text-muted-foreground text-sm mt-2.5">Across {pat.pages} winning pages: typical length {pat.median_words} words, {pct(pat.share_with_faq)} have an FAQ{pat.common_schema?.length ? `, most use ${pat.common_schema.map((x: any) => x.type).join(", ")}` : ""}.</p>}</Card>}
      <Button kind="quiet" onClick={() => go("plan")}>See the plan to close these gaps <Icon n="arrow" size={16} /></Button>
    </div>)}
  </div>);
}
export { assistant, pageName, signed };
