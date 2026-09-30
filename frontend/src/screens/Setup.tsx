import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { pageName } from "../copy";
import { Banner, Button, Choice, Field, Icon, ListInput, Steps, useAction, usePoll } from "../ui";

const TITLES = ["About your business", "Reading your website", "Questions your customers ask", "Anything to protect?", "Almost done"];

export function DeliveryChoice() {
  return (<div className="stack">
    <Choice on icon="box" title="Send me the improved pages to review" text="We prepare the changes as files you can download. Nothing on your website changes until you decide." badge="Recommended" />
    <Choice disabled icon="globe" title="Update my WordPress site for me" text="Coming soon." />
    <Choice disabled icon="edit" title="Send the changes to my web developer" text="Coming soon." />
  </div>);
}

export function Setup({ project, onDone, onCreated }: { project: any | null; onDone: (pid: number) => void; onCreated: (pid: number) => void }) {
  const [pid, setPid] = useState<number | null>(project?.id ?? null);
  const [step, setStep] = useState(project ? (project.kb_version ? 2 : 1) : 0);
  const [name, setName] = useState(project?.name ?? "");
  const [site, setSite] = useState(project?.site_url ?? "");
  const [questions, setQuestions] = useState<string[]>([""]);
  const [competitors, setCompetitors] = useState<string[]>([]);
  const [keep, setKeep] = useState<string[]>([]);
  const [never, setNever] = useState<string[]>([]);
  const [pages, setPages] = useState<string[]>([]);
  const [chosenPages, setChosenPages] = useState<string[]>([]);
  const [prep, setPrep] = useState<{ phase: string; error?: string } | null>(null);
  const { busy, error, run, clear } = useAction();
  const suggested = useRef(false);
  useEffect(() => { window.scrollTo({ top: 0 }); }, [step]);

  // Step 1: read the website
  const startReading = () => run(async () => { setPrep({ phase: "finding_pages" }); await api(`/projects/${pid}/prepare`, "POST"); });
  useEffect(() => { if (step === 1 && pid && !prep) startReading(); }, [step, pid]);
  usePoll(async () => {
    const s = await api(`/projects/${pid}/prepare`);
    setPrep(s); setPages(s.pages ?? []);
    if (s.phase === "done") { setChosenPages(c => (c.length ? c : s.pages ?? [])); setStep(2); }
  }, 1500, step === 1 && !!pid && !!prep && prep.phase !== "error" && prep.phase !== "done");

  // Step 2: suggest questions once
  const suggest = () => run(async () => {
    let r;
    try { r = await api(`/projects/${pid}/suggest-questions`, "POST"); }
    catch { throw new Error("We couldn't come up with suggestions just now. You can type your own questions above."); }
    setQuestions(q => [...q.filter(x => x.trim()), ...r.questions.filter((x: string) => !q.includes(x))]);
  });
  useEffect(() => { if (step === 2 && pid && !suggested.current && !questions.some(q => q.trim())) { suggested.current = true; suggest(); } }, [step, pid]);
  useEffect(() => { if (step >= 2 && pid) api(`/projects/${pid}/prepare`).then(s => { setPages(s.pages ?? []); setChosenPages(c => c.length ? c : s.pages ?? []); }); }, [step, pid]);

  const next = async () => {
    clear();
    if (step === 0) {
      const r = await run(async () => {
        if (pid) { await api(`/projects/${pid}`, "PATCH", { business_name: name }); return pid; }
        const c = await api("/simple/projects", "POST", { business_name: name, website: site });
        onCreated(c.id); return c.id as number;
      });
      if (r) { setPid(r); setPrep(null); setStep(1); }
    } else if (step < 4) setStep(step + 1);
  };
  const finish = () => run(async () => {
    await api(`/projects/${pid}/simple-brief`, "PUT", {
      questions, competitors, never_change: keep, never_say: never,
      editable_pages: chosenPages.length === pages.length ? [] : chosenPages });
    onDone(pid!);
  });

  const canNext = step === 0 ? name.trim() && site.includes(".") : step === 2 ? questions.some(q => q.trim()) : true;
  const reading = ["finding_pages", "reading_pages", "learning"];
  const phaseIdx = prep ? Math.max(0, reading.indexOf(prep.phase)) : 0;

  return (<div className="narrow">
    <Steps total={5} at={step} />
    <p className="muted small" style={{ margin: 0 }}>Step {step + 1} of 5</p>
    <h1>{TITLES[step]}</h1>

    {step === 0 && (<div className="card">
      <p className="muted">Tell us who you are. We'll read your website ourselves. You don't need to prepare anything.</p>
      <Field label="What is your business called?"><input type="text" value={name} onChange={e => setName(e.target.value)} placeholder="For example: Riverside Plumbing" autoFocus /></Field>
      <Field label="What is your website address?" hint="You can copy it from your browser's address bar.">
        <input type="text" value={site} disabled={!!pid} onChange={e => setSite(e.target.value)} placeholder="www.yourbusiness.com" /></Field>
    </div>)}

    {step === 1 && (<div className="card">
      {prep?.phase === "error" ? (<>
        <Banner kind="bad"><b>We couldn't finish reading your website.</b><br />{prep.error}</Banner>
        <Button onClick={() => { setPrep(null); startReading(); }}>Try again</Button>
      </>) : (<>
        <p className="muted">This takes about a minute. You can watch, or make a cup of tea.</p>
        <ul className="timeline">
          {["Finding the pages on your website", "Reading them", "Learning what your business does"].map((t, i) => (
            <li key={t} className={i < phaseIdx ? "done" : i === phaseIdx ? "now" : ""}>
              <span className="bullet">{i < phaseIdx ? <Icon n="check" size={14} /> : i === phaseIdx ? <span className="spin" /> : ""}</span>{t}</li>))}
        </ul>
      </>)}
    </div>)}

    {step === 2 && (<>
      <div className="card">
        <p className="muted">These are questions people might ask an AI assistant when they need what you offer. Change them, remove them, or add your own.
          These are the questions we will try to get your business recommended for.</p>
        <ListInput values={questions} onChange={setQuestions} placeholder="A question your customers ask" addLabel="Add a question" />
        <div style={{ marginTop: "1rem" }}><Button kind="quiet" size="small" busy={busy} onClick={suggest}><Icon n="spark" size={16} />Suggest more questions</Button></div>
      </div>
      <div className="card">
        <Field label="Who are your competitors? (optional)" hint="We'll notice when an AI assistant recommends them instead of you.">
          <ListInput values={competitors} onChange={setCompetitors} placeholder="www.competitor.com" addLabel="Add a competitor's website" /></Field>
      </div>
    </>)}

    {step === 3 && (<>
      <Banner kind="info"><Icon n="shield" size={18} /> <b>You stay in control.</b> Nothing changes on your website without your approval, and you can undo any change.</Banner>
      <div className="card">
        <Field label="Sentences we must never change" hint="For example prices, guarantees or legal wording. Copy them exactly as they appear on your website.">
          <ListInput values={keep} onChange={setKeep} placeholder="A sentence to keep exactly as it is" addLabel="Add a sentence" /></Field>
        <Field label="Things we must never claim" hint="For example “cheapest in town” or “award winning”.">
          <ListInput values={never} onChange={setNever} placeholder="A claim we should never make" addLabel="Add a claim" /></Field>
      </div>
      {pages.length > 0 && <div className="card">
        <Field label="Which pages may we improve?" hint="Untick any page that should stay exactly as it is.">
          {pages.map(p => (<label className="check" key={p}>
            <input type="checkbox" checked={chosenPages.includes(p)} onChange={e => setChosenPages(e.target.checked ? [...chosenPages, p] : chosenPages.filter(x => x !== p))} />
            <span><b>{pageName(p)}</b> <span className="muted small">{p.replace(/^https?:\/\//, "")}</span></span></label>))}
        </Field></div>}
    </>)}

    {step === 4 && (<>
      <div className="card soft"><b>How we'll check</b><p className="muted small" style={{ margin: ".25rem 0 0" }}>We'll ask your customers' questions to <b>{project?.model || "your AI model"}</b>, the model you connected, and see whether it mentions your business. You can change the model in Settings.</p></div>
      <div className="card"><Field label="How would you like to receive the improvements?"><DeliveryChoice /></Field></div>
    </>)}

    {error && <Banner kind="bad">{error}</Banner>}
    {step !== 1 && (<div className="row between actions">
      {step > 0 && step !== 2 ? <Button kind="text" onClick={() => { clear(); setStep(step - 1); }}>← Back</Button> : step === 2 ? <span /> : <span />}
      {step < 4 ? <Button size="big" busy={busy} disabled={!canNext} onClick={next}>Continue <Icon n="arrow" /></Button>
        : <Button size="big" busy={busy} onClick={finish}>Finish setup <Icon n="check" /></Button>}
    </div>)}
  </div>);
}
