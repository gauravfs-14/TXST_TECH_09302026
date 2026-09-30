import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { pageName } from "../copy";
import { useAction, usePoll } from "../hooks";
import { Badge, Banner, Button, Card, Check, Field, Icon, ListInput, Skeleton, Spinner } from "../ui";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import { DeliveryChoice } from "./Settings";
import { TaskFeed } from "../task";

const TITLES = ["About your business", "Reading your website", "What should we track?", "Anything to protect?", "Almost done"];

export default function Setup({ project, onDone, onCreated }: { project: any | null; onDone: (pid: number) => void; onCreated: (pid: number) => void }) {
  const [pid, setPid] = useState<number | null>(project?.id ?? null);
  const [step, setStep] = useState(project ? (project.kb_version ? 2 : 1) : 0);
  const [name, setName] = useState(project?.name ?? "");
  const [site, setSite] = useState(project?.site_url ?? "");
  const [questions, setQuestions] = useState<string[]>([""]);
  const [competitors, setCompetitors] = useState<string[]>([]);
  const [keep, setKeep] = useState<string[]>([]);
  const [never, setNever] = useState<string[]>([]);
  const [pages, setPages] = useState<string[]>([]);
  const [chosen, setChosen] = useState<string[]>([]);
  const [prep, setPrep] = useState<{ phase: string; error?: string } | null>(null);
  const [facts, setFacts] = useState<any>(null);
  const [products, setProducts] = useState<any[]>([]);
  const { busy, error, key, run, clear } = useAction();
  const suggested = useRef(false);
  useEffect(() => { window.scrollTo({ top: 0 }); }, [step]);

  const startReading = () => run(async () => { setPrep({ phase: "finding_pages" }); await api(`/projects/${pid}/prepare`, "POST"); });
  useEffect(() => { if (step === 1 && pid && !prep) startReading(); }, [step, pid]);
  usePoll(async () => {
    const s = await api(`/projects/${pid}/prepare`);
    setPrep(s); setPages(s.pages ?? []);
    if (s.phase === "done") { setChosen(c => (c.length ? c : s.pages ?? [])); loadFacts(); }
  }, 1500, step === 1 && !!pid && !!prep && prep.phase !== "error" && prep.phase !== "done");
  const loadFacts = () => { api(`/projects/${pid}/audit`).then(setFacts).catch(() => {}); api(`/projects/${pid}/products`).then(setProducts).catch(() => {}); };
  useEffect(() => { if (step >= 2 && pid) { loadFacts(); api(`/projects/${pid}/prepare`).then(s => { setPages(s.pages ?? []); setChosen(c => c.length ? c : s.pages ?? []); }); } }, [step, pid]);

  const suggest = () => run(async (task) => {
    let r; try { r = await api(`/projects/${pid}/suggest-questions`, "POST", undefined, { task }); } catch { throw new Error("We couldn't come up with suggestions just now. You can type your own questions."); }
    setQuestions(q => [...q.filter(x => x.trim()), ...r.questions.filter((x: string) => !q.includes(x))]);
  });
  useEffect(() => { if (step === 2 && pid && !suggested.current && !questions.some(q => q.trim())) { suggested.current = true; suggest(); } }, [step, pid]);

  const next = async () => {
    clear();
    if (step === 0) {
      const r = await run(async () => {
        if (pid) { const r = await api(`/projects/${pid}`, "PATCH", { business_name: name, website: site }); return { id: pid, reread: !!r.site_changed }; }
        const c = await api("/simple/projects", "POST", { business_name: name, website: site }); onCreated(c.id); return { id: c.id as number, reread: true };
      });
      if (r) { setPid(r.id); if (r.reread || !prep) setPrep(null); setStep(1); }
    } else if (step < 4) setStep(step + 1);
  };
  const finish = () => run(async (task) => {
    await api(`/projects/${pid}/simple-brief`, "PUT", { questions, competitors, never_change: keep, never_say: never, editable_pages: chosen.length === pages.length ? [] : chosen });
    await api(`/projects/${pid}/products/queries`, "POST", undefined, { task }).catch(() => {});
    onDone(pid!);
  });
  const canNext = step === 0 ? name.trim() && site.includes(".") : step === 2 ? questions.some(q => q.trim()) : true;
  const PHASES = ["finding_pages", "reading_pages", "auditing", "learning"];
  const LABEL = ["Finding your pages (robots.txt, sitemap, llms.txt)", "Reading them", "Checking your site for problems", "Learning what you offer"];
  const at = prep?.phase === "done" ? PHASES.length : Math.max(0, PHASES.indexOf(prep?.phase ?? ""));
  const d = facts?.discovery;

  return (<div className="narrow">
    <div className="flex gap-1.5">{TITLES.map((_, i) => <span key={i} className={cn("h-[5px] flex-1 rounded-full", i <= step ? "bg-primary" : "bg-border")} />)}</div>
    <p className="text-muted-foreground text-sm mt-2.5 mb-0">Step {step + 1} of 5</p><h1 className="mb-4">{TITLES[step]}</h1>

    {step === 0 && <Card><p className="text-muted-foreground">Tell us who you are. We read your website ourselves, so there's nothing to prepare.</p>
      <Field label="What is your business called?"><Input type="text" value={name} onChange={e => setName(e.target.value)} placeholder="For example: Riverside Plumbing" autoFocus /></Field>
      <Field label="What is your website address?" hint="Copy it from your browser's address bar. You can change it later in Settings."><Input type="text" value={site} onChange={e => setSite(e.target.value)} placeholder="www.yourbusiness.com" /></Field></Card>}

    {step === 1 && <Card>{prep?.phase === "error" ? <><Banner kind="bad"><b>We couldn't finish reading your website.</b><br />{prep.error}</Banner><div className="mt-4"><Button onClick={() => { setPrep(null); startReading(); }}>Try again</Button></div></> : <>
      <p className="text-muted-foreground">About a minute. We find your pages the way search engines do, then read the important ones.</p>
      <ul className="mb-3">{LABEL.map((t, i) => <li key={t} className={cn("flex items-center gap-2.5 py-1", i > at && "text-muted-foreground")}><span className="grid size-5 flex-none place-items-center text-primary">{i < at ? <Icon n="check" size={14} /> : i === at ? <Spinner /> : <span className="size-1.5 rounded-full bg-border" />}</span>{t}</li>)}</ul>
      <TaskFeed task={pid ? `prepare:${pid}` : null} on={!!prep && prep.phase !== "done" && prep.phase !== "error"} title="Reading your website" />
      {prep?.phase === "done" && (facts ? <div className="mt-4"><Separator className="mb-4" /><h3 className="mb-2.5">Here's what we found</h3>
        <div className="flex flex-wrap gap-1.5"><Badge tone={d?.robots?.exists ? "good" : "warn"}>robots.txt {d?.robots?.exists ? "found" : "missing"}</Badge><Badge tone={(d?.sitemaps ?? []).some((e: any) => e.status === 200) ? "good" : "warn"}>sitemap {(d?.url_count ?? 0)} pages</Badge><Badge tone={d?.llms?.exists ? "good" : "warn"}>llms.txt {d?.llms?.exists ? "found" : "missing"}</Badge><Badge tone={facts.score >= 80 ? "good" : "warn"}>Health {facts.score}/100</Badge><Badge>{products.length} product{products.length === 1 ? "" : "s"} detected</Badge></div>
        <p className="text-muted-foreground text-sm">We'll turn the problems into a step-by-step plan after your first round.</p></div> : <Skeleton h={60} />)}
      {prep?.phase === "done" && <div className="row justify-end mt-4"><Button size="big" onClick={() => setStep(2)}>Continue <Icon n="arrow" /></Button></div>}</>}</Card>}

    {step === 2 && <><Card title="Brand questions"><p className="text-muted-foreground">What people might ask an AI assistant when they need what you offer. We try to get you recommended for these.</p>
      <ListInput values={questions} onChange={setQuestions} placeholder="A question your customers ask" addLabel="Add a question" />
      <div className="mt-4"><Button kind="quiet" size="small" busy={busy} onClick={suggest}><Icon n="spark" size={16} />Suggest more</Button></div><TaskFeed task={key} on={busy} title="Thinking up questions" /></Card>
      <Card title="Products" className="mt-4">{products.length === 0 ? <p className="text-muted-foreground mb-0">No products detected. That's fine for a service business. You can add products or import a CSV from the Products page later.</p> : <>
        <p className="text-muted-foreground">We'll also check how shoppers' questions rank these, one at a time. Review the list, or fix it later in Products.</p>
        {products.slice(0, 8).map(x => <div key={x.id} className="row justify-between border-t py-1.5"><span><b>{x.name}</b> <span className="text-muted-foreground text-[0.78rem]">{x.sku}</span></span><Badge>{x.source === "manual" ? "added" : "found on your site"}</Badge></div>)}
        {products.length > 8 && <p className="text-muted-foreground text-sm">…and {products.length - 8} more.</p>}</>}</Card>
      <Card className="mt-4"><Field label="Competitors (optional)" hint="We'll notice when an assistant recommends them instead of you."><ListInput values={competitors} onChange={setCompetitors} placeholder="www.competitor.com" addLabel="Add a competitor's website" /></Field></Card></>}

    {step === 3 && <><Banner kind="info"><b>You stay in control.</b> Nothing changes on your website without your approval, and every change can be undone.</Banner>
      <Card className="mt-4"><Field label="Sentences we must never change" hint="Prices, guarantees or legal wording, exactly as they appear."><ListInput values={keep} onChange={setKeep} placeholder="A sentence to keep exactly as it is" addLabel="Add a sentence" /></Field>
        <Field label="Things we must never claim" hint="For example “cheapest in town”."><ListInput values={never} onChange={setNever} placeholder="A claim we should never make" addLabel="Add a claim" /></Field></Card>
      {pages.length > 0 && <Card className="mt-4"><Field label="Which pages may we improve?" hint="Untick any page that should stay exactly as it is.">{pages.map(p => (<Check key={p} checked={chosen.includes(p)} onChange={c => setChosen(c ? [...chosen, p] : chosen.filter(x => x !== p))}><span><b>{pageName(p)}</b> <span className="text-muted-foreground text-sm">{p.replace(/^https?:\/\//, "")}</span></span></Check>))}</Field></Card>}</>}

    {step === 4 && <><Card><b>How we'll check</b><p className="text-muted-foreground text-sm mt-1 mb-0">We ask your customers' questions to <b>{project?.model || "your AI model"}</b> and real web search, then test improvements in a sandbox. Change the model any time in Settings.</p></Card>
      <Card className="mt-4"><Field label="How would you like to receive the improvements?"><DeliveryChoice /></Field></Card></>}

    {step === 4 && <TaskFeed task={key} on={busy} title="Saving and preparing your questions" />}
    {error && <div className="mt-4"><Banner kind="bad">{error}</Banner></div>}
    {step !== 1 && <div className="row justify-between mt-4">{step > 0 ? <Button kind="text" onClick={() => { clear(); setStep(step - 1); }}>← Back</Button> : <span />}
      {step < 4 ? <Button size="big" busy={busy} disabled={!canNext} onClick={next}>Continue <Icon n="arrow" /></Button> : <Button size="big" busy={busy} onClick={finish}>Finish setup <Icon n="check" /></Button>}</div>}
  </div>);
}
