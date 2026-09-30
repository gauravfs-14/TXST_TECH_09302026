import { ReactNode, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { VERDICT, isWorking } from "../copy";
import { useAction, useApi } from "../hooks";
import { Badge, Banner, Button, Card, Check, Choice, Empty, Field, Icon, ListInput, NumberField, PageHead, Skeleton, Steps, Toggle, ago, toast } from "../ui";
import { TaskFeed } from "../task";
import { SuggestProducts } from "@/components/SuggestProducts";
import { cn } from "@/lib/utils";
import type { Go } from "../App";
import RunView from "./RunView";

export type LoopCfg = { max_loops: number; min_gain: number; patience: number; min_effect: number; exposure_rank: number; track: string[]; plan: string; allow_new_pages: boolean; max_new_pages: number };
const STEPS = ["What to test", "How thorough", "Review and start"];

/** One thing a round can test, as a card you switch on. Its details appear inside once it's on. */
function Track({ on, onChange, icon, title, summary, children }: { on: boolean; onChange: (v: boolean) => void; icon: "chat" | "tag"; title: string; summary: ReactNode; children?: ReactNode }) {
  return (<div className={cn("rounded-xl border-[1.5px] bg-card transition-colors", on ? "border-primary" : "border-input")}>
    <button type="button" role="switch" aria-checked={on} onClick={() => onChange(!on)} className="flex w-full items-center gap-3.5 rounded-xl p-3.5 text-left outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50">
      <span className={cn("grid size-9 flex-none place-items-center rounded-lg", on ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground")}><Icon n={icon} /></span>
      <span className="flex-1"><b>{title}</b><span className="block text-sm text-muted-foreground">{summary}</span></span>
      <span className={cn("grid size-6 flex-none place-items-center rounded-md border-2", on ? "border-primary bg-primary text-primary-foreground" : "border-input")}>{on && <Icon n="check" size={14} />}</span></button>
    {on && children && <div className="animate-in border-t px-3.5 pt-3.5 pb-3.5 fade-in slide-in-from-top-1">{children}</div>}</div>);
}

/** When there are no products: the two ways forward, right where the person is looking. */
function FindProducts({ project, onManage, onAdded }: { project: any; onManage: () => void; onAdded: () => void }) {
  return (<div><p className="mb-3 text-sm">We haven't found any products on your site, and product questions need at least one to ask about. If you don't sell anything (a blog or tutorial site, say), just switch this off. Otherwise:</p>
    <SuggestProducts project={project} onAdded={onAdded} extra={<Button kind="quiet" onClick={onManage}><Icon n="plus" size={16} />Add one myself</Button>} /></div>);
}

/** What someone had chosen before stepping out to Products, handed back on return so nothing is lost. */
type Draft = { cfg: LoopCfg; qs: string[]; dirty: boolean };

function Start({ project, go, draft, onStarted }: { project: any; go: Go; draft?: Draft; onStarted: (id: number) => void }) {
  const st = useApi<any>(`/projects/${project.id}/settings`);
  const brief = useApi<any>(`/projects/${project.id}/simple-brief`);
  const prods = useApi<any[]>(`/projects/${project.id}/products`);
  const [cfg, setCfg] = useState<LoopCfg | null>(draft?.cfg ?? null);
  const [qs, setQs] = useState<string[] | null>(draft?.qs ?? null);
  const [dirty, setDirty] = useState(draft?.dirty ?? false);
  const [step, setStep] = useState(0);
  const [tune, setTune] = useState(false);
  const [editQs, setEditQs] = useState(false);
  useEffect(() => { if (st.data && !cfg) setCfg(st.data.settings); }, [st.data]);
  // With no products yet, product questions start switched off (brand questions still work); switching them on shows how to add products.
  const tidied = useRef(!!draft); // a returning draft already reflects what the person chose
  useEffect(() => { if (cfg && prods.data && !tidied.current) { tidied.current = true; if (!prods.data.some(p => p.active) && cfg.track.includes("brand")) setCfg({ ...cfg, track: cfg.track.filter(x => x !== "products") }); } }, [cfg, prods.data]);
  useEffect(() => { if (brief.data && qs === null) setQs(brief.data.questions?.length ? brief.data.questions : [""]); }, [brief.data]);
  const est = useApi<any>(cfg ? `/projects/${project.id}/plans?loops=${cfg.max_loops}&track=${cfg.track.join(",")}` : null);
  const go2 = useAction(), start = useAction(), gen = useAction();
  const active = (prods.data ?? []).filter(p => p.active);
  const missing = active.filter(p => !(p.queries?.length)).length;
  const writing = useRef(false);
  const wantProducts = !!cfg?.track.includes("products");
  // Product questions are written for you the moment they're needed, so nobody has to know that's a separate step.
  useEffect(() => {
    if (wantProducts && missing > 0 && !writing.current) { writing.current = true; gen.run(async (task) => { await api(`/projects/${project.id}/products/queries`, "POST", undefined, { task }); await prods.reload(); }).finally(() => { writing.current = false; }); }
  }, [wantProducts, missing]);
  if (!cfg || qs === null || !prods.data) return <Skeleton h={340} />;

  const brand = cfg.track.includes("brand"), products = cfg.track.includes("products");
  const okQs = qs.filter(q => q.trim());
  const flip = (t: string, on: boolean) => setCfg({ ...cfg, track: on ? [...new Set([...cfg.track, t])] : cfg.track.filter(x => x !== t) });
  const nQ = active.reduce((n, p) => n + (p.queries?.length ?? 0), 0);
  const problem = !brand && !products ? "Choose at least one thing to test."
    : brand && okQs.length === 0 ? "Add at least one brand question, or switch brand questions off."
    : !brand && products && active.length === 0 ? "Product questions need at least one product. Find or add products above, or also switch on brand questions." : "";
  const plans: any[] = est.data?.plans ?? [];
  const chosen = plans.find(p => p.id === cfg.plan);
  const up = (k: Partial<LoopCfg>) => setCfg({ ...cfg, ...k });
  const manage = () => go("products", { from: "optimize", draft: { cfg, qs, dirty } });

  const next = () => go2.run(async () => {
    if (step === 0 && brand && dirty) { await api(`/projects/${project.id}/questions`, "PUT", { questions: okQs }); setDirty(false); setQs(okQs); }
    setStep(step + 1);
  });
  const begin = () => start.run(async () => {
    await api(`/projects/${project.id}/settings`, "PUT", cfg); // remembered for next time, so there's no separate "save" to find
    const r = await api(`/projects/${project.id}/runs`, "POST", { intensity: cfg.plan, overrides: cfg }); toast("Round started"); onStarted(r.run_id);
  });
  const sum = (label: string, at: number, body: ReactNode) => (<div className="row items-start justify-between border-t py-3"><div><div className="text-[0.78rem] tracking-[.06em] text-muted-foreground uppercase">{label}</div><div>{body}</div></div><Button kind="text" size="small" onClick={() => setStep(at)}>Change</Button></div>);

  return (<div className="max-w-[46rem]">
    <Steps steps={STEPS} at={step} onGo={setStep} />
    {step === 0 && <Card variant="hero"><h2>What should this round test?</h2>
      <p className="text-muted-foreground">A round asks AI assistants your customers' questions, then tests improvements to your pages. Choose what to ask about. You can pick both.</p>
      <div className="space-y-3">
        <Track on={brand} onChange={v => flip("brand", v)} icon="chat" title="Brand questions" summary={`${okQs.length} question${okQs.length === 1 ? "" : "s"} about you and what you offer`}>
          {editQs ? <><p className="mb-2.5 text-sm text-muted-foreground">Put the most important first.</p>
            <ListInput values={qs} onChange={v => { setQs(v); setDirty(true); }} placeholder="A question your customers ask" addLabel="Add a question" />
            <Button kind="text" size="small" className="mt-2" onClick={() => { setEditQs(false); if (!qs.some(q => q.trim())) setQs([""]); }}>Done editing</Button></> : <>
            <ul className="m-0 mb-2 list-none p-0">{okQs.slice(0, 3).map((q, i) => <li key={i} className="truncate border-t py-1.5 text-sm first:border-t-0">“{q}”</li>)}</ul>
            {okQs.length > 3 && <p className="mb-2 text-sm text-muted-foreground">…and {okQs.length - 3} more.</p>}
            <Button kind="quiet" size="small" onClick={() => setEditQs(true)}><Icon n="edit" size={14} />Review or edit questions</Button></>}</Track>
        <Track on={products} onChange={v => flip("products", v)} icon="tag" title="Product questions" summary={active.length ? `${active.length} product${active.length === 1 ? "" : "s"}${nQ ? ` · ${nQ} shopper questions ready` : ""}` : "No products yet. Switch on to add some"}>
          {active.length === 0 ? <FindProducts project={project} onManage={manage} onAdded={prods.reload} /> : <div>
            {gen.busy && <p className="mb-2 text-sm text-muted-foreground">Writing shopper questions for your products…</p>}
            <ul className="m-0 mb-2.5 list-none p-0">{active.slice(0, 6).map(p => <li key={p.id} className="border-t py-1.5 text-sm first:border-t-0"><b>{p.name}</b>{p.queries?.length > 0 && <span className="text-muted-foreground"> · e.g. “{p.queries[p.queries.length > 2 ? 2 : 0].text}”</span>}</li>)}</ul>
            {active.length > 6 && <p className="text-sm text-muted-foreground">…and {active.length - 6} more.</p>}
            <Button kind="text" size="small" onClick={manage}>Manage products <Icon n="arrow" size={14} /></Button></div>}
          <TaskFeed task={gen.key} on={gen.busy} title="Writing shopper questions" /></Track></div>
      {problem && <div className="mt-4"><Banner kind="warn">{problem}</Banner></div>}
      {brand && products && active.length === 0 && !problem && <div className="mt-4"><Banner kind="info">Product questions will be skipped until you add a product. Brand questions still run.</Banner></div>}
      {go2.error && <div className="mt-4"><Banner kind="bad">{go2.error}</Banner></div>}
      <div className="row mt-5 justify-end"><Button size="big" busy={go2.busy || gen.busy} disabled={!!problem} onClick={next}>Continue<Icon n="arrow" /></Button></div></Card>}

    {step === 1 && <Card variant="hero"><h2>How thorough should it be?</h2>
      <p className="text-muted-foreground">More thorough means more AI requests and more time, but firmer results. If unsure, pick Standard.</p>
      <div className="grid g3">{(plans.length ? plans : [{ id: "quick", label: "Quick check", blurb: "" }, { id: "standard", label: "Standard", blurb: "" }, { id: "thorough", label: "Thorough", blurb: "" }]).map(p =>
        <Choice key={p.id} icon="spark" title={p.label} text={p.blurb} on={cfg.plan === p.id} onClick={() => up({ plan: p.id })} badge={p.now ? `~${p.now} AI requests` : undefined} />)}</div>
      <div className="mt-5"><Field label="Most improvement loops" hint="Each loop drafts changes, tests them in the sandbox and learns from the result. It stops early if more loops aren't helping.">
        <NumberField label="loops" value={cfg.max_loops} min={1} max={10} onChange={v => up({ max_loops: v })} /></Field>
        <Toggle checked={cfg.allow_new_pages} onChange={v => up({ allow_new_pages: v })} label="Allow brand-new pages" hint="When no existing page answers a question, draft a new one for you to review." /></div>
      <Button kind="text" size="small" onClick={() => setTune(!tune)} aria-expanded={tune}><Icon n="sliders" size={15} />{tune ? "Hide fine-tuning" : "Fine-tune (optional)"}</Button>
      {tune && <div className="grid g2 mt-3 animate-in fade-in slide-in-from-top-1">
        <Field label="Brand-new pages, at most"><NumberField label="new pages" value={cfg.max_new_pages} min={0} max={10} disabled={!cfg.allow_new_pages} onChange={v => up({ max_new_pages: v })} /></Field>
        <Field label="Give up after this many loops without progress" hint="Saves AI use once changes stop helping."><NumberField label="loops without progress" value={cfg.patience} min={1} max={5} onChange={v => up({ patience: v })} /></Field>
        <Field label="Smallest gain that counts as progress" hint="A loop must add at least this much."><NumberField label="gain" suffix="%" value={Math.round(cfg.min_gain * 100)} min={0} max={50} onChange={v => up({ min_gain: v / 100 })} /></Field>
        <Field label="Smallest improvement worth recommending" hint="Anything smaller is treated as noise. 5 is sensible."><NumberField label="improvement" suffix="%" value={Math.round(cfg.min_effect * 100)} min={0} max={50} onChange={v => up({ min_effect: v / 100 })} /></Field>
        <Field label="Where your page appears in the test" hint="1 = first result. Before and after use the same spot, so the comparison is fair."><NumberField label="position" value={cfg.exposure_rank} min={1} max={5} onChange={v => up({ exposure_rank: v })} /></Field></div>}
      <div className="row mt-5 justify-between"><Button kind="text" onClick={() => setStep(0)}>← Back</Button><Button size="big" onClick={() => setStep(2)}>Continue<Icon n="arrow" /></Button></div></Card>}

    {step === 2 && <Card variant="hero"><h2>Ready when you are</h2>
      <p className="text-muted-foreground">Here is what will happen. Nothing on your website changes until you approve it.</p>
      {sum("Testing", 0, <>{brand && <span>{okQs.length} brand question{okQs.length === 1 ? "" : "s"}</span>}{brand && products && <span> and </span>}{products && <span>{active.length ? `${active.length} product${active.length === 1 ? "" : "s"}` : "products (none yet, skipped)"}</span>}</>)}
      {sum("Depth", 1, <>{chosen?.label ?? cfg.plan}, up to {cfg.max_loops} loop{cfg.max_loops === 1 ? "" : "s"}{cfg.allow_new_pages ? `, up to ${cfg.max_new_pages} new page${cfg.max_new_pages === 1 ? "" : "s"}` : ", no new pages"}</>)}
      {chosen && <div className="border-t py-3 text-sm text-muted-foreground">At most about <b className="text-foreground">{chosen.now}</b> AI requests, fewer if it stops early. A follow-up check after you publish uses about {chosen.later}. {est.data?.used_24h != null && <>You've made {est.data.used_24h} in the last 24 hours.</>} Your choices are remembered for next time.</div>}
      {start.error && <Banner kind="bad">{start.error}</Banner>}
      <div className="row mt-3 justify-between"><Button kind="text" onClick={() => setStep(1)}>← Back</Button><Button size="big" busy={start.busy} onClick={begin}><Icon n="spark" size={18} />Start the round</Button></div></Card>}
  </div>);
}

const status = (r: any) => (r.status === "failed" ? "Problem" : r.status === "cancelled" ? "Stopped" : isWorking(r) ? "Running" : r.stage === "done" ? "Done" : "Ready to review");

export default function Optimize({ project, ctx, go }: { project: any; ctx: any; go: Go }) {
  const runs = useApi<any[]>(`/projects/${project.id}/runs`, { poll: 8000 });
  const [sel, setSel] = useState<number | null>(ctx?.run ?? null);
  const [fresh, setFresh] = useState(false);
  const list = runs.data ?? [];
  useEffect(() => { if (ctx?.run) setSel(ctx.run); }, [ctx]);
  useEffect(() => { if (sel == null && !fresh && list.length && list.some(isWorking)) setSel(list.find(isWorking)!.id); }, [list.length]);
  const working = list.some(isWorking);
  return (<div className="page">
    <PageHead title="Optimize" sub={sel != null ? "Follow a round, review what it found, and decide what goes ahead." : "Test how assistants answer, draft improvements, and check they work, all before you change anything."}
      actions={sel != null && <Button kind="quiet" onClick={() => { setSel(null); setFresh(true); }}>← All rounds</Button>} />
    {!runs.data ? <Skeleton h={300} /> : sel != null ? <RunView key={sel} runId={sel} go={go} /> : (<div className="space-y-4">
      {working ? <Banner kind="clay">A round is already running. <Button kind="text" size="small" onClick={() => setSel(list.find(isWorking)!.id)}>Watch it →</Button></Banner> : <Start project={project} go={go} draft={ctx?.draft} onStarted={id => { setSel(id); runs.reload(); }} />}
      {list.length > 0 && <Card title="Earlier rounds">{list.map((r, i) => (<button key={r.id} className={cn("row w-full justify-between py-3 text-left hover:bg-accent/40", i > 0 && "border-t")} onClick={() => setSel(r.id)}>
        <span><b>Round {r.iteration}</b><span className="text-sm text-muted-foreground"> · {ago(r.created_at)}</span></span>
        <span className="row">{r.summary?.evaluation?.verdict && <Badge tone={VERDICT[r.summary.evaluation.verdict.label]?.tone}>{VERDICT[r.summary.evaluation.verdict.label]?.label}</Badge>}<Badge tone={r.status === "failed" ? "bad" : undefined}>{status(r)}</Badge><Icon n="arrow" size={16} /></span></button>))}</Card>}
      {list.length === 0 && !working && <p className="text-center text-sm text-muted-foreground">Your first round takes a few minutes. You can leave this page while it runs.</p>}
    </div>)}
  </div>);
}
