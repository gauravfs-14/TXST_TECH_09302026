import { useEffect, useState } from "react";
import { api } from "../api";
import { HIDDEN_ACTIONS, describeAction } from "../copy";
import { Button, Icon } from "../ui";

function ago(ts: string): string {
  const d = new Date(ts + "Z"), s = (Date.now() - d.getTime()) / 1000;
  if (s < 60) return "just now"; if (s < 3600) return `${Math.floor(s / 60)} min ago`; if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export function Activity({ projectId }: { projectId: number }) {
  const [rows, setRows] = useState<any[]>([]);
  const [ok, setOk] = useState<string>("");
  useEffect(() => { api(`/audit?project_id=${projectId}&limit=300`).then(setRows); }, [projectId]);
  const shown = rows.filter(r => !HIDDEN_ACTIONS.some(h => r.action.startsWith(h)));
  return (<div>
    <h1>Activity</h1>
    <p className="muted">A complete record of everything Confiance has done for you and everything you have decided.</p>
    <div className="card">
      {shown.length === 0 && <p className="muted">Nothing yet.</p>}
      {shown.map(r => (<div key={r.id} className="row between" style={{ padding: ".65rem 0", borderTop: "1px solid var(--line)" }}>
        <span><b>{describeAction(r.action)}</b>{r.actor === "user" && <span className="pill" style={{ marginLeft: ".5rem" }}>You</span>}</span>
        <span className="muted small" title={r.ts}>{ago(r.ts)}</span></div>))}
    </div>
    <div className="row"><Button kind="quiet" size="small" onClick={() => api("/audit/verify").then(r => setOk(r.ok ? "✓ Nothing in this history has been altered." : "⚠ Something in the history doesn't add up. Please contact support."))}><Icon n="shield" size={16} />Check this history hasn't been altered</Button><span className="small">{ok}</span></div>
  </div>);
}
