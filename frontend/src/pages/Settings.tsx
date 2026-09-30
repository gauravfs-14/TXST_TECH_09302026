import { useEffect, useState } from "react";
import { api } from "../api";
import { assistant, friendlyDrift, pageName } from "../copy";
import { useAction, useApi, usePoll } from "../hooks";
import { Badge, Banner, Button, Card, Check, Choice, Field, Icon, ListInput, PageHead, Skeleton, Tabs, ago, toast } from "../ui";
import { TaskFeed } from "../task";
import { Input } from "@/components/ui/input";
import { Accounts } from "./Accounts";
import type { Go } from "../App";

export function DeliveryChoice() {
  return (<div className="space-y-3.5">
    <Choice on icon="box" title="Send me the improved pages to review" text="We prepare the changes as files you can download. Nothing on your website changes until you decide." badge="Recommended" />
    <Choice disabled icon="globe" title="Update my WordPress site for me" text="Coming soon." />
    <Choice disabled icon="edit" title="Send the changes to my web developer" text="Coming soon." />
  </div>);
}

const same = (a: string, b: string) => a.trim().replace(/^https?:\/\//, "").replace(/\/+$/, "").toLowerCase() === b.trim().replace(/^https?:\/\//, "").replace(/\/+$/, "").toLowerCase();

function Business({ project, reload, toAI, go }: { project: any; reload: () => void; toAI: () => void; go: Go }) {
  const [name, setName] = useState(project.name);
  const [site, setSite] = useState(project.site_url.replace(/^https?:\/\//, ""));
  const [sure, setSure] = useState(false);
  const [reading, setReading] = useState(false);
  const [phase, setPhase] = useState("");
  const { busy, error, key, run } = useAction();
  useEffect(() => { setName(project.name); setSite(project.site_url.replace(/^https?:\/\//, "")); }, [project.id, project.site_url]);
  const siteChanged = !same(site, project.site_url);
  const dirty = siteChanged || name.trim() !== project.name;
  usePoll(async () => { const s = await api(`/projects/${project.id}/prepare`); setPhase(s.phase); if (s.phase === "done" || s.phase === "error") { setReading(false); if (s.phase === "done") toast("Your new website has been read"); } }, 1500, reading);
  const save = () => run(async () => {
    const r = await api(`/projects/${project.id}`, "PATCH", { business_name: name, ...(siteChanged ? { website: site } : {}) });
    setSure(false); reload();
    if (r.site_changed) { setReading(true); setPhase("finding_pages"); await api(`/projects/${project.id}/prepare`, "POST"); } else toast("Saved");
  });
  return (<div className="space-y-3.5"><Card title="Your business">
    <Field label="Business name"><Input type="text" value={name} onChange={e => setName(e.target.value)} /></Field>
    <Field label="Website address" hint="You can change this any time. We'll read the new site so everything matches it."><Input type="text" value={site} onChange={e => { setSite(e.target.value); setSure(false); }} placeholder="www.yourbusiness.com" /></Field>
    {sure && <div className="mb-4"><Banner kind="warn"><b>Switch to {site.trim()}?</b> We'll read that website again. Products we found on the old one are removed, and products you added yourself stay. Past rounds are kept.</Banner></div>}
    {error && <div className="mb-3"><Banner kind="bad">{error}</Banner></div>}
    <div className="row"><Button busy={busy} disabled={!dirty || reading} onClick={() => (siteChanged && !sure ? setSure(true) : save())}>{siteChanged ? (sure ? "Yes, switch and re-read" : "Save website") : "Save"}</Button>
      {sure && <Button kind="text" onClick={() => { setSure(false); setSite(project.site_url.replace(/^https?:\/\//, "")); }}>Keep the old one</Button>}</div>
    <p className="mt-4 mb-0 text-sm text-muted-foreground">Testing with <b>{project.model}</b>. <Button kind="text" size="small" className="px-1.5 text-primary underline underline-offset-4" onClick={toAI}>Change the AI connection</Button></p></Card>
    {(reading || phase === "done") && <Card variant="sunk">{reading ? <TaskFeed task={`prepare:${project.id}`} on title="Reading your new website" /> : <><p className="m-0"><b>Your new website has been read.</b></p><p className="mt-1 mb-3 text-sm text-muted-foreground">Check that your questions and products still fit it.</p><div className="row"><Button kind="quiet" size="small" onClick={() => go("products")}>Review products</Button><Button kind="quiet" size="small" onClick={() => go("site")}>See site health</Button></div></>}
      {reading && <p className="mt-3 mb-0 text-sm text-muted-foreground">This takes about a minute. You can keep using Confiance.</p>}</Card>}
    {phase === "error" && !reading && <Banner kind="bad">We couldn't read that website. Check the address, then use “Scan my site” in Site health to try again.</Banner>}
  </div>);
}

function Questions({ project }: { project: any }) {
  const [b, setB] = useState<any>(null);
  const [pages, setPages] = useState<string[]>([]);
  const { busy, error, run } = useAction();
  useEffect(() => { api(`/projects/${project.id}/simple-brief`).then(setB); api(`/projects/${project.id}/prepare`).then(r => setPages(r.pages ?? [])); }, [project.id]);
  if (!b) return <Skeleton h={300} />;
  const set = (k: string, v: any) => setB({ ...b, [k]: v });
  return (<Card title="Questions and rules"><p className="text-muted-foreground">Your next round uses what's saved here. Put the most important questions first.</p>
    <Field label="Questions your customers ask"><ListInput values={b.questions} onChange={v => set("questions", v)} placeholder="A question" addLabel="Add a question" /></Field>
    <Field label="Competitors' websites (optional)"><ListInput values={b.competitors} onChange={v => set("competitors", v)} placeholder="www.competitor.com" addLabel="Add a competitor" /></Field>
    <Field label="Sentences we must never change" hint="Copy them exactly as they appear on your website."><ListInput values={b.never_change} onChange={v => set("never_change", v)} placeholder="A sentence to keep as it is" addLabel="Add a sentence" /></Field>
    <Field label="Things we must never claim"><ListInput values={b.never_say} onChange={v => set("never_say", v)} placeholder="A claim we should never make" addLabel="Add a claim" /></Field>
    {pages.length > 0 && <Field label="Pages we may improve">{pages.map(pg => (<Check key={pg} checked={b.editable_pages.includes(pg)} onChange={c => set("editable_pages", c ? [...b.editable_pages, pg] : b.editable_pages.filter((x: string) => x !== pg))}>
      <span><b>{pageName(pg)}</b> <span className="text-muted-foreground text-sm">{pg.replace(/^https?:\/\//, "")}</span></span></Check>))}</Field>}
    {error && <Banner kind="bad">{error}</Banner>}
    <Button busy={busy} onClick={() => run(async () => { await api(`/projects/${project.id}/simple-brief`, "PUT", { ...b, editable_pages: b.editable_pages.length === pages.length ? [] : b.editable_pages }); toast("Saved. Your next round will use this."); })}>Save changes</Button></Card>);
}

function Health() {
  const d = useApi<any[]>("/drift"), al = useApi<any[]>("/alerts?unacknowledged=true");
  const [msg, setMsg] = useState("");
  const reload = () => { d.reload(); al.reload(); };
  return (<Card title="Are AI assistants behaving as usual?" actions={<Button kind="quiet" size="small" onClick={() => api("/drift/check", "POST", {}).then(() => setMsg("Checking now. Come back in a minute."))}>Check now</Button>}>
    <p className="text-muted-foreground">We quietly test each assistant every day. If one changes how it works, we'll tell you here, so a sudden drop isn't a mystery.</p>{msg && <p className="text-sm">{msg}</p>}
    {(d.data ?? []).length === 0 && <p className="text-muted-foreground text-sm">No checks yet.</p>}
    {(d.data ?? []).map(x => (<div key={x.id} className="border-t py-3"><div className="row justify-between"><b>{assistant(x.engine)} <span className="text-muted-foreground text-sm">{x.model}</span></b><Badge tone={x.status === "ok" || x.status === "baseline" ? "good" : "warn"}>{x.status === "ok" || x.status === "baseline" ? "Everything normal" : "Something changed"}</Badge></div>
      {x.findings.map((f: any, i: number) => <p key={i} className="text-sm mt-1.5 mb-0">{friendlyDrift(x.engine, f.kind)}</p>)}
      {x.status === "drift" && <Button kind="quiet" size="small" onClick={() => api("/drift/accept", "POST", { engine: x.engine, model: x.model }).then(reload)}>Treat this as the new normal</Button>}</div>))}
    {(al.data ?? []).length > 0 && <div className="mt-4"><b>Heads-ups</b>{al.data!.map(a => <div key={a.id} className="row justify-between py-1.5"><span className="text-sm">{a.title.replace(/^\[\w+\]\s*/, "")} <span className="text-muted-foreground text-[0.78rem]">{ago(a.created_at)}</span></span><Button kind="text" size="small" onClick={() => api(`/alerts/${a.id}/ack`, "POST").then(reload)}>Dismiss</Button></div>)}</div>}</Card>);
}

function Spending({ project }: { project: any }) {
  const u = useApi<any>(`/usage?project_id=${project.id}`);
  const tok = u.data ? u.data.rows.reduce((a: number, r: any) => a + r.input_tokens + r.output_tokens, 0) : 0;
  return (<Card title="What you've spent"><p className="text-muted-foreground">Confiance uses your own AI accounts. This is an estimate of what they have charged for this business.</p>
    <div className="tabular-nums font-serif text-4xl font-semibold">${(u.data?.total_usd ?? 0).toFixed(2)}</div>
    <p className="text-muted-foreground text-sm">{tok.toLocaleString()} units of AI work so far{u.data?.total_usd === 0 ? ". Models on your own computer and free tiers cost nothing." : "."}</p></Card>);
}

type T = "business" | "questions" | "connections" | "health";
export default function Settings({ project, reload, go }: { project: any; go: Go; reload: () => void }) {
  const [t, setT] = useState<T>("business");
  return (<div className="page"><PageHead title="Settings" sub="Set up the business once here. Options for a single round are on the Optimize page." />
    <div className="mb-4"><Tabs value={t} onChange={setT} items={[{ id: "business", label: "Business & website" }, { id: "questions", label: "Questions & rules" }, { id: "connections", label: "AI & delivery" }, { id: "health", label: "Health & spend" }]} /></div>
    {t === "business" && <Business project={project} reload={reload} go={go} toAI={() => setT("connections")} />}{t === "questions" && <Questions project={project} />}
    {t === "connections" && <div className="space-y-3.5"><Card title="Connected AI accounts"><Accounts onSaved={reload} /></Card><Card title="How you receive improvements"><DeliveryChoice /></Card></div>}
    {t === "health" && <div className="space-y-3.5"><Health /><Spending project={project} /></div>}</div>);
}
