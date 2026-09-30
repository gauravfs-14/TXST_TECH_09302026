import { useEffect, useState } from "react";
import { api } from "../api";
import { pct } from "../copy";
import { Banner, Button, Icon, Meter, useAction, usePoll } from "../ui";
import { Progress } from "./Improvements";

const HOW = [
  { icon: "chat" as const, t: "1. We ask the questions", d: "Pretend customers ask AI assistants what your real customers ask." },
  { icon: "spark" as const, t: "2. We suggest fixes", d: "We find safe, honest changes to your website that help assistants understand you." },
  { icon: "shield" as const, t: "3. You decide", d: "Nothing changes without your approval, and every change can be undone." },
];

export function Home({ project, onReview, alertsCount, goto }: { project: any; onReview: (runId: number) => void; alertsCount: number; goto: (t: string) => void }) {
  const [runs, setRuns] = useState<any[] | null>(null);
  const [sum, setSum] = useState<any>(null);
  const { busy, error, run } = useAction();
  const load = async () => {
    const r: any[] = await api(`/projects/${project.id}/runs`);
    setRuns(r);
    if (r[0]) setSum(await api(`/runs/${r[0].id}/summary`)); else setSum(null);
  };
  useEffect(() => { setRuns(null); load(); }, [project.id]);
  const latest = runs?.[0];
  const working = latest && (latest.status === "running" || latest.status === "pending");
  usePoll(load, 4000, !!working);

  const start = () => run(async () => { const r = await api(`/projects/${project.id}/runs`, "POST"); await load(); return r; });
  const needsReview = latest?.stage === "awaiting_approval" && latest.status === "waiting";
  const needsLive = latest?.stage === "awaiting_live";

  return (<div>
    <h1>{project.name}</h1>
    <p className="muted" style={{ marginTop: "-.25rem" }}>{project.domain} · testing with {project.model || "your AI model"}</p>

    {alertsCount > 0 && <Banner kind="warn"><b>Something changed with an AI assistant.</b> <button className="btn text small" onClick={() => goto("settings")}>See what changed</button></Banner>}
    {error && <Banner kind="bad">{error}</Banner>}

    {working && <Progress stage={latest.stage} />}

    {needsReview && <div className="card hero"><h2>Your improvements are ready to review</h2>
      <p className="muted">We tested them in a practice round. Take a look, and choose what goes ahead.</p>
      <Button size="big" onClick={() => onReview(latest.id)}>Review improvements <Icon n="arrow" /></Button></div>}

    {needsLive && <div className="card hero"><h2>Waiting for your changes to go live</h2>
      <p className="muted">Download the improved pages, put them on your website, then tell us.</p>
      <Button size="big" onClick={() => onReview(latest.id)}>Open <Icon n="arrow" /></Button></div>}

    {latest?.status === "failed" && <div className="card"><Banner kind="bad"><b>The last round hit a problem.</b><br />{latest.error}</Banner>
      <Button onClick={() => onReview(latest.id)}>See details</Button></div>}

    {!working && !needsReview && !needsLive && (<div className="card hero">
      <h2>{latest ? "Ready for another round?" : "Ready to find improvements?"}</h2>
      <p className="muted">{latest ? "Each round learns from the last one. It takes about 10 minutes and costs a small amount of AI usage." : "We'll ask AI assistants your customers' questions, then suggest safe changes to your website. It takes about 10 minutes, and nothing changes without your approval."}</p>
      <Button size="big" busy={busy} onClick={start}><Icon n="spark" />Find improvements</Button></div>)}

    {sum?.before && (<div className="card">
      <h2>How AI assistants talk about you</h2>
      <p className="muted">Out of all the answers we collected, how often your business was…</p>
      <div className="grid2">
        {[["Mentioned by name", sum.before.mentioned, sum.live_after?.mentioned ?? sum.after?.mentioned], ["Linked to as a source", sum.before.cited, sum.live_after?.cited ?? sum.after?.cited]].map(([l, b, a]: any) => (
          <div key={l}><b>{l}</b>
            <div className="row" style={{ gap: ".6rem", margin: ".4rem 0" }}><span className="muted small" style={{ width: 52 }}>Before</span><div className="grow"><Meter value={b} /></div><b>{pct(b)}</b></div>
            {a !== undefined && <div className="row" style={{ gap: ".6rem" }}><span className="small" style={{ width: 52, color: "var(--primary)" }}>{sum.live_after ? "Now" : "Tested"}</span><div className="grow"><Meter value={a} after /></div><b>{pct(a)}</b></div>}
          </div>))}
      </div>
    </div>)}

    {!latest && (<div className="grid3">{HOW.map(h => <div className="card soft" key={h.t}><span style={{ color: "var(--primary)" }}><Icon n={h.icon} size={26} /></span><h3 style={{ marginTop: ".5rem" }}>{h.t}</h3><p className="muted small" style={{ margin: 0 }}>{h.d}</p></div>)}</div>)}
  </div>);
}
