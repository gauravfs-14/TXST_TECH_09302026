import { useEffect, useState } from "react";
import { api } from "../api";
import { PROGRESS, describeOp, friendlyBlock, pageName, pct, progressIndex } from "../copy";
import { Banner, Button, Icon, Meter, useAction, usePoll } from "../ui";

export function Progress({ stage }: { stage: string }) {
  const at = progressIndex(stage);
  return (<div className="card hero">
    <h2>We're working on it</h2>
    <p className="muted">This usually takes 5 to 15 minutes. You can close this page and come back. We'll keep going.</p>
    <ul className="timeline">
      {PROGRESS.map((p, i) => (<li key={p.key} className={i < at ? "done" : i === at ? "now" : ""}>
        <span className="bullet">{i < at ? <Icon n="check" size={14} /> : i === at ? <span className="spin" /> : ""}</span>
        <span>{p.title}<br /><span className="muted small" style={{ fontWeight: 400 }}>{i === at ? p.detail : ""}</span></span></li>))}
    </ul>
  </div>);
}

function Compare({ label, before, after }: { label: string; before: number; after?: number }) {
  return (<div>
    <div className="row" style={{ gap: ".5rem" }}><span className="muted small" style={{ width: 96 }}>Today</span><div className="grow"><Meter value={before} /></div><b style={{ width: 44, textAlign: "right" }}>{pct(before)}</b></div>
    {after !== undefined && <div className="row" style={{ gap: ".5rem", marginTop: ".35rem" }}><span className="small" style={{ width: 96, color: "var(--primary)", fontWeight: 600 }}>With changes</span><div className="grow"><Meter value={after} after /></div><b style={{ width: 44, textAlign: "right" }}>{pct(after)}</b></div>}
    <span className="sr" style={{ position: "absolute", left: -9999 }}>{label}</span>
  </div>);
}

function Questions({ s }: { s: any }) {
  return (<div className="card">
    <h2>Your customers' questions</h2>
    <p className="muted">How often the AI assistants <b>mention your business</b> when asked each question.</p>
    {s.questions.map((q: any) => (<div key={q.id} style={{ padding: ".9rem 0", borderTop: "1px solid var(--line)" }}>
      <b>“{q.text}”</b>
      <div style={{ margin: ".5rem 0" }}><Compare label={q.text} before={q.before.mentioned} after={s.after ? q.after.mentioned : undefined} /></div>
      <details><summary>See what the AI said</summary>
        <div className="grid2" style={{ marginTop: ".75rem" }}>
          <div><p className="small muted">Today</p><div className="quote">{q.before_answer || "No answer."}</div></div>
          {s.after && <div><p className="small" style={{ color: "var(--primary)" }}>With the changes</p><div className="quote">{q.after_answer || "No answer."}</div></div>}
        </div></details>
    </div>))}
  </div>);
}

function Change({ p, checked, onToggle }: { p: any; checked: boolean; onToggle: () => void }) {
  const [more, setMore] = useState(false);
  return (<div style={{ padding: "1rem 0", borderTop: "1px solid var(--line)" }}>
    <label className="check" style={{ alignItems: "flex-start" }}>
      <input type="checkbox" checked={checked} onChange={onToggle} />
      <span><b>{pageName(p.url)}</b> <span className="muted small">{p.url.replace(/^https?:\/\//, "")}</span>
        <ul style={{ margin: ".4rem 0 .4rem 1rem", padding: 0 }}>{p.ops.map((o: any, i: number) => <li key={i}>{describeOp(o)}</li>)}</ul>
        <span className="muted small"><b>Why:</b> {p.rationale}</span>
        <br /><span className="pill good" style={{ marginTop: ".4rem" }}><Icon n="shield" size={13} />Passed all safety checks</span></span>
    </label>
    {p.guard_report?.warnings?.length > 0 && <p className="small muted" style={{ marginLeft: "2.2rem" }}>{p.guard_report.warnings.join(" ")}</p>}
    <Button kind="text" size="small" onClick={() => setMore(!more)} style={{ marginLeft: "1.6rem" }}>{more ? "Hide the exact wording" : "Show the exact wording"}</Button>
    {more && <div className="quote" style={{ marginLeft: "2.2rem" }}>{p.ops.map((o: any) => o.html ? o.html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim() : o.items ? o.items.map((i: any) => `${i.q}\n${i.a}`).join("\n\n") : o.text || o.content || "").filter(Boolean).join("\n\n")}</div>}
  </div>);
}

function Deliver({ s, runId, reload }: { s: any; runId: number; reload: () => void }) {
  const d = s.deployment;
  const { busy, error, run } = useAction();
  if (!d) return null;
  return (<div className="card hero">
    <h2>Your improvements are ready</h2>
    {d.how === "export" ? (<>
      <p>Download the improved pages and send them to whoever looks after your website. Nothing on your live site has changed yet.</p>
      <div className="row"><a className="btn primary big" href={`/api/deployments/${d.id}/download`}><Icon n="download" />Download the improvements</a></div>
      <hr style={{ border: 0, borderTop: "1px solid var(--line)", margin: "1.5rem 0" }} />
      <p><b>Once the changes are on your website</b>, tell us, and we'll check how AI assistants respond to them.</p>
    </>) : <p>The changes are waiting for you: {d.where}. Once they're live, tell us.</p>}
    {error && <Banner kind="bad">{error}</Banner>}
    <Button kind="quiet" busy={busy} onClick={() => run(async () => { await api(`/deployments/${d.id}/confirm-live`, "POST"); reload(); })}><Icon n="check" size={16} />The changes are now on my website</Button>
  </div>);
}

export function RunView({ runId }: { runId: number }) {
  const [s, setS] = useState<any>(null);
  const [props, setProps] = useState<any[]>([]);
  const [picked, setPicked] = useState<number[] | null>(null);
  const [undo, setUndo] = useState<number | null>(null);
  const { busy, error, run } = useAction();
  const load = async () => {
    const [sum, p] = await Promise.all([api(`/runs/${runId}/summary`), api(`/runs/${runId}/proposals`)]);
    setS(sum); setProps(p);
    setPicked(cur => cur ?? p.filter((x: any) => x.status === "candidate").map((x: any) => x.id));
  };
  useEffect(() => { setS(null); setPicked(null); load(); }, [runId]);
  const approving = !!s && s.stage === "awaiting_approval" && props.some(p => p.status === "approved");
  const active = !s || approving || s.status === "running" || s.status === "pending" || ["awaiting_live", "awaiting_measure", "deploy"].includes(s.stage);
  usePoll(load, 3000, active && !!runId);
  if (!s) return <p className="muted">Loading…</p>;

  const candidates = props.filter(p => p.status === "candidate");
  const blocked = props.filter(p => p.status === "blocked");
  const approved = props.filter(p => ["approved", "deployed"].includes(p.status));
  const decide = (approve: boolean) => run(async () => {
    await api(`/runs/${runId}/decide`, "POST", { proposal_ids: approve ? picked : candidates.map(c => c.id), approve });
    await load();
  });

  if (s.status === "failed") return (<div className="card"><Banner kind="bad"><b>Something went wrong.</b><br />{s.error}</Banner>
    <Button busy={busy} onClick={() => run(async () => { await api(`/runs/${runId}/advance`, "POST"); await load(); })}>Try again</Button></div>);

  if (["created", "kb", "prompts", "baseline", "optimize", "candidate", "evaluate"].includes(s.stage) && s.stage !== "done") return <Progress stage={s.stage} />;

  return (<div>
    {s.stage === "done" && s.recommendation === "no_changes" && <div className="card hero"><h2>No safe improvements this time</h2>
      <p className="muted">We looked carefully but couldn't find changes that would help and still respect your rules. That can mean your pages already answer these questions well.</p>
      {s.optimizer_summary && <p className="small muted">{s.optimizer_summary}</p>}</div>}

    {s.before && s.after && (<div className="card hero">
      <p className="muted small" style={{ margin: 0 }}>PRACTICE TEST RESULT</p>
      <h2>{candidates.length ? `We found ${candidates.length} improvement${candidates.length > 1 ? "s" : ""}` : "Results of the practice test"}</h2>
      <div className="row" style={{ gap: "1.5rem", margin: "1rem 0" }}>
        <div><div className="big-num" style={{ color: "var(--muted)" }}>{pct(s.before.mentioned)}</div><span className="muted small">of AI answers mention you today</span></div>
        <span className="arrow">→</span>
        <div><div className="big-num" style={{ color: "var(--primary)" }}>{pct(s.after.mentioned)}</div><span className="small">with these changes</span></div>
      </div>
      <p className="muted small" style={{ margin: 0 }}>This is a practice run, asking assistants the same questions with and without the changes. The real result depends on when AI assistants next look at your site, so we'll check again after you publish.</p>
    </div>)}

    {s.stage === "awaiting_approval" && candidates.length > 0 && (<div className="card">
      <h2>Choose what goes ahead</h2>
      <p className="muted">Every change below passed our safety checks. Untick anything you don't want.</p>
      {candidates.map(p => <Change key={p.id} p={p} checked={!!picked?.includes(p.id)} onToggle={() => setPicked(cur => (cur ?? []).includes(p.id) ? (cur ?? []).filter(x => x !== p.id) : [...(cur ?? []), p.id])} />)}
      {error && <Banner kind="bad">{error}</Banner>}
      <div className="row" style={{ marginTop: "1.25rem" }}>
        <Button size="big" busy={busy} disabled={!picked?.length} onClick={() => decide(true)}>Approve {picked?.length ?? 0} change{picked?.length === 1 ? "" : "s"}</Button>
        <Button kind="text" onClick={() => confirm("Skip all of these suggestions?") && decide(false)}>Not now</Button>
      </div>
    </div>)}

    {s.stage === "awaiting_live" && <Deliver s={s} runId={runId} reload={load} />}

    {s.stage === "awaiting_measure" && (<Banner kind="info"><Icon n="clock" size={18} /> <b>Your changes are live.</b> We'll check how AI assistants respond {s.measure_after ? `from ${new Date(s.measure_after).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" })}` : "in a few days"}. They need a little time to notice.</Banner>)}

    {s.stage === "done" && s.live_before && s.live_after && (<div className="card hero"><p className="muted small" style={{ margin: 0 }}>REAL RESULT</p><h2>What happened after the changes went live</h2>
      <div className="row" style={{ gap: "1.5rem", margin: "1rem 0" }}>
        <div><div className="big-num" style={{ color: "var(--muted)" }}>{pct(s.live_before.mentioned)}</div><span className="muted small">before</span></div><span className="arrow">→</span>
        <div><div className="big-num" style={{ color: "var(--primary)" }}>{pct(s.live_after.mentioned)}</div><span className="small">after</span></div></div>
      <p className="muted small">Share of AI answers that mention your business. We'll use this to do better next time.</p></div>)}

    {s.questions?.length > 0 && <Questions s={s} />}

    {approved.length > 0 && s.stage !== "awaiting_approval" && (<div className="card"><h3>Changes you approved</h3>
      {approved.map(p => <p key={p.id} style={{ margin: ".4rem 0" }}><b>{pageName(p.url)}</b>. <span className="muted">{p.ops.map(describeOp).join("; ")}</span></p>)}</div>)}

    {blocked.length > 0 && (<div className="card soft"><h3>Ideas we blocked to keep you safe</h3>
      <p className="muted small">Our checks stopped these before they reached you.</p>
      {blocked.map(p => <p key={p.id} className="small" style={{ margin: ".35rem 0" }}><b>{pageName(p.url)}:</b> {friendlyBlock((p.guard_report.violations ?? [""])[0])}</p>)}</div>)}

    {["awaiting_measure", "done"].includes(s.stage) && s.deployment?.status === "applied" && (<div className="card soft">
      <div className="row between"><div><b>Changed your mind?</b><br /><span className="muted small">You can put your pages back exactly as they were.</span></div>
        <Button kind="danger" busy={busy} onClick={() => confirm("Undo these changes and go back to your original pages?") && run(async () => { const r = await api(`/deployments/${s.deployment.id}/rollback`, "POST"); setUndo(r.rollback_id); await load(); })}><Icon n="undo" size={16} />Undo these changes</Button></div>
      {undo && <div style={{ marginTop: "1rem" }}><p>Download your original pages, put them back on your website, then tell us it's done.</p>
        <div className="row"><a className="btn quiet" href={`/api/deployments/${undo}/download`}><Icon n="download" size={16} />Download original pages</a>
          <Button kind="quiet" onClick={() => run(async () => { await api(`/deployments/${undo}/confirm-live`, "POST"); setUndo(null); await load(); })}>They're back on my website</Button></div></div>}
    </div>)}
  </div>);
}

export function Improvements({ projectId, focusRun, onFocusDone }: { projectId: number; focusRun: number | null; onFocusDone: () => void }) {
  const [runs, setRuns] = useState<any[]>([]);
  const [sel, setSel] = useState<number | null>(null);
  const load = () => api(`/projects/${projectId}/runs`).then((r: any[]) => { setRuns(r); setSel(cur => cur ?? focusRun ?? r[0]?.id ?? null); });
  useEffect(() => { load(); }, [projectId]);
  useEffect(() => { if (focusRun) { setSel(focusRun); onFocusDone(); } }, [focusRun]);
  usePoll(load, 8000);
  if (!runs.length) return <div className="card center"><h2>No improvements yet</h2><p className="muted">Go to Home and press “Find improvements” to start.</p></div>;
  const label = (r: any) => `Round ${r.iteration} · ${new Date(r.created_at + "Z").toLocaleDateString(undefined, { day: "numeric", month: "short" })}`;
  return (<div>
    <div className="row between" style={{ marginBottom: "1rem" }}><h1 style={{ margin: 0 }}>Improvements</h1>
      {runs.length > 1 && <select style={{ width: "auto" }} value={sel ?? ""} onChange={e => setSel(Number(e.target.value))} aria-label="Choose a round">{runs.map(r => <option key={r.id} value={r.id}>{label(r)}</option>)}</select>}</div>
    {sel && <RunView key={sel} runId={sel} />}
  </div>);
}
