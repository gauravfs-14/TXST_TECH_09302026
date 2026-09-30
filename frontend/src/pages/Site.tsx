import { useState } from "react";
import { api } from "../api";
import { SEVERITY, pathOf } from "../copy";
import { useAction, useApi, usePoll } from "../hooks";
import { Badge, Banner, Button, Card, Empty, Icon, PageHead, Skeleton, Stat, TableBox, Tabs, ago, toast } from "../ui";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Ring, Trend } from "../charts";
import { TaskFeed } from "../task";
import type { Go } from "../App";

type Tab = "issues" | "discovery" | "pages";
const YesNo = ({ ok, yes, no }: { ok: boolean; yes: string; no: string }) => <Badge tone={ok ? "good" : "warn"}>{ok ? yes : no}</Badge>;

const LH_LABEL: [string, string][] = [["performance", "Speed"], ["accessibility", "Accessibility"], ["best_practices", "Best practices"], ["seo", "SEO"]];
const LH_METRIC: Record<string, string> = { fcp: "First content", lcp: "Main content", tbt: "Blocking time", cls: "Layout shift", speed_index: "Speed index" };

function Lighthouse({ lh }: { lh?: any }) {
  if (!lh?.available) return <Card title="Lighthouse" className="mb-4"><p className="text-muted-foreground m-0">{lh?.reason ? `Lighthouse couldn't run this time (${lh.reason}). Your site health score above is unaffected. Scan again to retry.` : "Scan your site again to add a Lighthouse test (Google's speed, accessibility and SEO score)."}</p></Card>;
  const fails = Object.entries(lh.failed ?? {}).flatMap(([k, rows]: [string, any]) => rows.map((r: any) => ({ ...r, area: LH_LABEL.find(l => l[0] === k)?.[1] ?? k })));
  return (<Card title="Lighthouse" actions={<Badge>{lh.strategy === "mobile" ? "Phone" : "Desktop"} · home page</Badge>} className="mb-4">
    <div className="grid g4">{LH_LABEL.map(([k, label]) => <div key={k} className="flex items-center gap-3"><Ring value={lh.scores?.[k] ?? null} size={72} label={label} /><b>{label}</b></div>)}</div>
    <div className="row mt-4 gap-4 text-sm text-muted-foreground">{Object.entries(lh.metrics ?? {}).filter(([, m]: any) => m.display).map(([k, m]: [string, any]) => <span key={k}>{LH_METRIC[k] ?? k}: <b className="text-foreground">{m.display}</b></span>)}</div>
    {(lh.opportunities?.length > 0 || fails.length > 0) && <Accordion type="single" collapsible className="mt-3">
      {lh.opportunities?.length > 0 && <AccordionItem value="speed"><AccordionTrigger>Biggest speed fixes ({lh.opportunities.length})</AccordionTrigger><AccordionContent><ul className="m-0 pl-5 text-sm">{lh.opportunities.map((o: any) => <li key={o.id}>{o.title}{o.detail && <span className="text-muted-foreground"> · {o.detail}</span>}</li>)}</ul></AccordionContent></AccordionItem>}
      {fails.length > 0 && <AccordionItem value="other"><AccordionTrigger>Other things Lighthouse flagged ({fails.length})</AccordionTrigger><AccordionContent><ul className="m-0 pl-5 text-sm">{fails.map((f: any) => <li key={f.area + f.id}>{f.title} <span className="text-muted-foreground">· {f.area}</span></li>)}</ul></AccordionContent></AccordionItem>}
    </Accordion>}
    <p className="text-muted-foreground text-xs mt-3 mb-0">Lighthouse is Google's own test, run on your home page{lh.source === "local" ? " on this computer" : " through PageSpeed Insights"}. Our site health score above checks different things: whether search engines and AI assistants can find and understand your pages.</p></Card>);
}

export default function Site({ project, go }: { project: any; go: Go }) {
  const a = useApi<any>(`/projects/${project.id}/audit`);
  const [tab, setTab] = useState<Tab>("issues");
  const [scanning, setScanning] = useState(false);
  const [phase, setPhase] = useState("");
  const act = useAction();
  const scan = () => act.run(async () => { setScanning(true); setPhase("finding_pages"); await api(`/projects/${project.id}/prepare`, "POST"); });
  usePoll(async () => { const s = await api(`/projects/${project.id}/prepare`); setPhase(s.phase); if (s.phase === "done" || s.phase === "error") { setScanning(false); a.reload(); if (s.phase === "done") toast("Scan finished"); } }, 1500, scanning);
  const PH: Record<string, string> = { finding_pages: "Finding your pages…", reading_pages: "Reading them…", auditing: "Checking for problems…", speed_test: "Running Lighthouse…", learning: "Learning what you offer…" };
  const head = <PageHead title="Site health" sub="What AI assistants and search engines can find and understand on your website." actions={<Button kind="quiet" busy={scanning} onClick={scan}><Icon n="refresh" size={16} />{scanning ? PH[phase] ?? "Working…" : a.data?.scanned ? "Scan again" : "Scan my site"}</Button>} />;
  if (!a.data) return <div className="page">{head}<Skeleton h={320} /></div>;
  if (!a.data.scanned) return <div className="page">{head}<Empty title="Not scanned yet" action={<Button onClick={scan} busy={scanning}>Scan my site</Button>}>We read your robots.txt, sitemap and llms.txt, then check your key pages.</Empty></div>;
  const d = a.data, disc = d.discovery, rob = disc.robots ?? {}, llms = disc.llms ?? {}, sm: any[] = disc.sitemaps ?? [];
  const bots = Object.entries(rob.ai_bots ?? {}) as [string, any][];
  const blocked = bots.filter(([, v]) => !v.allowed);
  const high = d.counts?.high ?? 0;
  const sev = (o: string) => d.findings.filter((f: any) => f.severity === o);
  return (<div className="page">{head}
    {act.error && <Banner kind="bad">{act.error}</Banner>}
    <TaskFeed task={`prepare:${project.id}`} on={scanning} title="Scanning your site" />
    <div className="grid g4 mb-4">
      <Stat label="Health score" plain value={<div className="flex items-center gap-3.5"><Ring value={d.score} /><div><b>{d.score >= 80 ? "Healthy" : d.score >= 55 ? "Needs work" : "Weak"}</b><div className="text-muted-foreground text-sm">Scanned {ago(d.at)}</div></div></div>} />
      <Stat label="Pages in sitemap" value={disc.url_count ?? 0} sub={`${d.pages_checked} pages read in detail`} />
      <Stat label="Issues" value={d.findings.length} tone={high ? "bad" : d.findings.length ? "warn" : "good"} sub={`${high} high, ${d.counts?.medium ?? 0} medium`} />
      <Stat label="Structured data" value={`${d.pages.length ? Math.round(100 * d.pages.filter((p: any) => p.schema_types?.length).length / d.pages.length) : 0}%`} sub="of pages describe themselves to machines" />
    </div>
    <Lighthouse lh={d.lighthouse} />
    {d.history?.length > 1 && <Card title="Score over time" className="mb-4"><Trend labels={d.history.map((h: any) => ago(h.at))} series={[{ name: "Score", color: "var(--primary)", points: d.history.map((h: any) => h.score / 100) }]} height={120} /></Card>}
    <div className="mb-4"><Tabs value={tab} onChange={setTab} items={[{ id: "issues", label: `Issues (${d.findings.length})` }, { id: "discovery", label: "Sitemap, robots & llms.txt" }, { id: "pages", label: `Pages (${d.pages.length})` }]} /></div>

    {tab === "issues" && (d.findings.length === 0 ? <Empty title="No issues found">Nice work.</Empty> : <div className="space-y-3.5">
      {["high", "medium", "low", "info"].map(o => sev(o).length > 0 && (<Card key={o} title={<>{SEVERITY[o].label} priority <span className="text-muted-foreground text-sm">({sev(o).length})</span></>}><Accordion type="multiple">{sev(o).map((f: any) => (<AccordionItem key={f.id} value={String(f.id)}>
        <AccordionTrigger className="items-center py-3 font-sans text-base"><span><b>{f.title}</b> <Badge tone={SEVERITY[o].tone as any}>{f.area}</Badge></span></AccordionTrigger>
        <AccordionContent className="text-base"><p className="text-muted-foreground mb-1.5">{f.detail}</p><p className="mb-1"><b>Fix:</b> {f.fix}</p>
        {f.urls?.length > 0 && <p className="text-[0.78rem] text-muted-foreground font-mono mb-0">{f.urls.slice(0, 5).map((u: string) => pathOf(u)).join("  ·  ")}{f.urls.length > 5 ? "  …" : ""}</p>}</AccordionContent></AccordionItem>))}</Accordion></Card>))}
      <Button kind="quiet" onClick={() => go("plan")}>Turn these into a step-by-step plan <Icon n="arrow" size={16} /></Button></div>)}

    {tab === "discovery" && (<div className="grid g2">
      <Card title="robots.txt" actions={<YesNo ok={!!rob.exists} yes="Found" no="Missing" />}>
        {rob.exists ? <>{rob.blocks_all && <Banner kind="bad">Your robots.txt blocks every crawler.</Banner>}<p className="text-muted-foreground text-sm">Which AI crawlers may read your site:</p>
          <div className="flex flex-wrap gap-1.5">{bots.map(([b, v]) => <Badge key={b} tone={v.allowed ? "good" : "bad"}>{b} · {v.allowed ? "allowed" : "blocked"}</Badge>)}</div>
          {blocked.length > 0 && <p className="text-sm mt-2.5">{blocked.length} crawler(s) are blocked. If that's not intentional, assistants can't learn from your pages. The plan includes a corrected file.</p>}</> : <p className="text-muted-foreground">No robots.txt. Crawlers will assume they may read everything, but you can't guide them either.</p>}</Card>
      <Card title="Sitemap" actions={<YesNo ok={sm.some(e => e.status === 200)} yes="Found" no="Missing" />}>
        {sm.length ? sm.map((e, i) => <p key={i} className="text-sm my-1"><span className="font-mono">{pathOf(e.url)}</span> <Badge tone={e.status === 200 ? "good" : "bad"}>{e.status === 200 ? `${e.urls ?? 0} pages` : `error ${e.status}`}</Badge></p>) : <p className="text-muted-foreground">No sitemap found.</p>}
        <div className="mt-4 flex flex-wrap gap-1.5">{Object.entries(disc.types ?? {}).map(([t, n]) => <Badge key={t}>{t}: {String(n)}</Badge>)}</div></Card>
      <Card title="llms.txt" actions={<YesNo ok={!!llms.exists} yes="Found" no="Missing" />}>
        {llms.exists ? <><p style={{ margin: 0 }}><b>{llms.title || "Untitled"}</b></p><p className="text-muted-foreground text-sm">{llms.summary}</p><p className="text-sm">{llms.links} links in {llms.sections?.length ?? 0} sections.</p></> : <p className="text-muted-foreground">A short guide that tells assistants what your site is and which pages matter. You don't have one yet. The plan includes a draft.</p>}</Card>
      <Card title="Notes">{(disc.notes ?? []).length ? <ul className="text-sm m-0 list-disc pl-[1.1rem]">{disc.notes.map((n: string, i: number) => <li key={i}>{n}</li>)}</ul> : <p className="text-muted-foreground">Nothing unusual.</p>}</Card></div>)}

    {tab === "pages" && <TableBox><Table><TableHeader><TableRow><TableHead>Page</TableHead><TableHead>Type</TableHead><TableHead>Words</TableHead><TableHead>Structured data</TableHead><TableHead>Title / description</TableHead></TableRow></TableHeader><TableBody>
      {d.pages.map((p: any) => <TableRow key={p.url}><TableCell className="max-w-[420px] whitespace-normal"><b className="font-mono text-sm break-all">{pathOf(p.url)}</b></TableCell><TableCell><Badge>{p.type}</Badge></TableCell><TableCell className="tabular-nums">{p.words}</TableCell><TableCell className="text-sm whitespace-normal">{(p.schema_types ?? []).join(", ") || <span className="text-muted-foreground">none</span>}</TableCell>
        <TableCell className="text-sm"><span className="flex gap-1"><YesNo ok={!!p.title} yes="Title" no="No title" /> <YesNo ok={!!p.meta_description} yes="Description" no="No description" /></span></TableCell></TableRow>)}</TableBody></Table></TableBox>}
  </div>);
}
