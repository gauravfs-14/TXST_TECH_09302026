import { useEffect, useState } from "react";
import { api } from "../api";
import { assistant, friendlyDrift } from "../copy";
import { Banner, Button, Field, useAction } from "../ui";
import { Accounts } from "./Accounts";
import { DeliveryChoice } from "./Setup";

function Health() {
  const [d, setD] = useState<any[]>([]);
  const [alerts, setAlerts] = useState<any[]>([]);
  const [msg, setMsg] = useState("");
  const load = () => { api("/drift").then(setD); api("/alerts?unacknowledged=true").then(setAlerts); };
  useEffect(load, []);
  return (<div className="card">
    <div className="row between"><h2 style={{ margin: 0 }}>Are AI assistants behaving as usual?</h2>
      <Button kind="quiet" size="small" onClick={() => api("/drift/check", "POST", {}).then(() => setMsg("Checking now. Come back in a minute."))}>Check now</Button></div>
    <p className="muted">We quietly test each assistant every day. If one changes how it works, we'll tell you here.</p>
    {msg && <p className="small">{msg}</p>}
    {d.length === 0 && <p className="muted small">No checks yet. The first one runs automatically once you have started a round.</p>}
    {d.map(x => (<div key={x.id} style={{ padding: ".75rem 0", borderTop: "1px solid var(--line)" }}>
      <div className="row between"><b>{assistant(x.engine)}</b>
        <span className={`pill ${x.status === "ok" || x.status === "baseline" ? "good" : "warn"}`}>{x.status === "ok" || x.status === "baseline" ? "Everything normal" : "Something changed"}</span></div>
      {x.findings.map((f: any, i: number) => <p key={i} className="small" style={{ margin: ".4rem 0 0" }}>{friendlyDrift(x.engine, f.kind)}</p>)}
      {x.status === "drift" && <div style={{ marginTop: ".5rem" }}><Button kind="quiet" size="small" onClick={() => api("/drift/accept", "POST", { engine: x.engine, model: x.model }).then(load)}>Got it. Treat this as the new normal</Button></div>}
    </div>))}
    {alerts.length > 0 && <div style={{ marginTop: "1rem" }}><b>Heads-ups</b>{alerts.map(a => <div key={a.id} className="row between" style={{ padding: ".4rem 0" }}><span className="small">{a.title.replace(/^\[\w+\]\s*/, "")}</span><Button kind="text" size="small" onClick={() => api(`/alerts/${a.id}/ack`, "POST").then(load)}>Dismiss</Button></div>)}</div>}
  </div>);
}

function Spending({ projectId }: { projectId: number }) {
  const [u, setU] = useState<any>(null);
  useEffect(() => { api(`/usage?project_id=${projectId}`).then(setU); }, [projectId]);
  return (<div className="card"><h2>What you've spent</h2>
    <p className="muted">Confiance uses your own AI accounts. This is an estimate of what those accounts have charged for this business.</p>
    <div className="big-num">{u && u.total_usd > 0 ? `$${u.total_usd.toFixed(2)}` : "$0.00"}</div>
    {u && <p className="muted small" style={{ marginTop: ".5rem" }}>{(u.rows.reduce((a: number, r: any) => a + r.input_tokens + r.output_tokens, 0)).toLocaleString()} units of AI work so far{u.total_usd === 0 ? ". Models running on your own computer are free." : "."}</p>}</div>);
}

export function Settings({ project, onChanged }: { project: any; onChanged: () => void }) {
  const [name, setName] = useState(project.name);
  const { busy, error, run } = useAction();
  const [saved, setSaved] = useState(false);
  return (<div>
    <h1>Settings</h1>
    <div className="card"><h2>Your business</h2>
      <Field label="Business name"><input type="text" value={name} onChange={e => setName(e.target.value)} /></Field>
      <p className="muted small">Testing with <b>{project.model}</b>. Change the model under “Connected accounts” below.</p>
      {error && <Banner kind="bad">{error}</Banner>}
      <div className="row"><Button busy={busy} onClick={() => run(async () => { await api(`/projects/${project.id}`, "PATCH", { business_name: name }); setSaved(true); onChanged(); })}>Save</Button>{saved && <span className="small">✓ Saved</span>}</div>
    </div>
    <div className="card"><h2>How you receive improvements</h2><DeliveryChoice /></div>
    <Health />
    <Spending projectId={project.id} />
    <div className="card"><h2>Connected accounts</h2><Accounts /></div>
  </div>);
}
