import { ReactNode, useEffect, useState } from "react";

type P = { d: string; size?: number };
const Svg = ({ d, size = 20 }: P) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={d} /></svg>
);
const paths = {
  leaf: "M5 19c0-8 5-14 15-14 0 10-6 15-14 15M5 19c2-5 5-8 9-10",
  check: "M5 12.5l4.5 4.5L19 7.5", search: "M11 18a7 7 0 100-14 7 7 0 000 14zM20 20l-4-4",
  spark: "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 16l.7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7z",
  globe: "M12 21a9 9 0 100-18 9 9 0 000 18zM3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18",
  shield: "M12 3l8 3v6c0 4.5-3.2 8-8 9-4.8-1-8-4.5-8-9V6z", box: "M4 8l8-4 8 4v8l-8 4-8-4zM4 8l8 4 8-4M12 12v8",
  chat: "M4 5h16v11H9l-5 4z", key: "M14 10a4 4 0 11-2.8 6.9L4 18v-3l6-1 1-1.5A4 4 0 0114 10zM16 8h.01", arrow: "M5 12h14M13 6l6 6-6 6",
  undo: "M9 14L4 9l5-5M4 9h10a6 6 0 010 12h-3", download: "M12 4v11M7 11l5 5 5-5M5 20h14", clock: "M12 21a9 9 0 100-18 9 9 0 000 18zM12 7v5l3 2",
  plus: "M12 5v14M5 12h14", edit: "M4 20h4L19 9l-4-4L4 16zM14 6l4 4",
} as const;
export type IconName = keyof typeof paths;
export const Icon = ({ n, size }: { n: IconName; size?: number }) => <Svg d={paths[n]} size={size} />;

export function Button({ kind = "primary", size, busy, children, ...p }: {
  kind?: "primary" | "quiet" | "text" | "danger"; size?: "big" | "small"; busy?: boolean; children: ReactNode;
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button {...p} disabled={p.disabled || busy} className={`btn ${kind} ${size ?? ""}`}>{busy && <span className="spin" />}{children}</button>;
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return <div className="field"><label className="f">{label}</label>{hint && <p className="hint">{hint}</p>}{children}</div>;
}

/** A list of short text values the person can add to, edit and remove. */
export function ListInput({ values, onChange, placeholder, addLabel }: { values: string[]; onChange: (v: string[]) => void; placeholder: string; addLabel: string }) {
  return (<div>
    {values.map((v, i) => (
      <div className="list-row" key={i}>
        <input type="text" value={v} aria-label={placeholder} onChange={e => onChange(values.map((x, j) => (j === i ? e.target.value : x)))} />
        <button className="x" aria-label="Remove" onClick={() => onChange(values.filter((_, j) => j !== i))}>×</button>
      </div>))}
    <Button kind="quiet" size="small" onClick={() => onChange([...values, ""])}><Icon n="plus" size={16} />{addLabel}</Button>
  </div>);
}

export function Choice({ icon, title, text, on, disabled, onClick, badge }: { icon: IconName; title: string; text: string; on?: boolean; disabled?: boolean; onClick?: () => void; badge?: string }) {
  return (<button type="button" className={`choice ${on ? "on" : ""}`} disabled={disabled} onClick={onClick} aria-pressed={on}>
    <span className="ico"><Icon n={icon} /></span>
    <span><b>{title}</b> {badge && <span className="pill">{badge}</span>}<br /><span className="muted small">{text}</span></span>
    <span className="tick"><Icon n="check" /></span>
  </button>);
}

export function Meter({ value, after }: { value: number; after?: boolean }) {
  return <div className={`meter ${after ? "after" : ""}`} role="img" aria-label={`${Math.round(value * 100)} percent`}><i style={{ width: `${Math.max(2, Math.round(value * 100))}%` }} /></div>;
}

export function Steps({ total, at }: { total: number; at: number }) {
  return <div className="steps" aria-label={`Step ${at + 1} of ${total}`}>{Array.from({ length: total }, (_, i) => <span key={i} className={`step ${i < at ? "done" : i === at ? "now" : ""}`} />)}</div>;
}

export function Banner({ kind = "info", children }: { kind?: "info" | "warn" | "bad" | "clay"; children: ReactNode }) {
  return <div className={`banner ${kind}`} role={kind === "bad" ? "alert" : undefined}><div>{children}</div></div>;
}

export function useToast() {
  const [msg, setMsg] = useState("");
  useEffect(() => { if (msg) { const t = setTimeout(() => setMsg(""), 3200); return () => clearTimeout(t); } }, [msg]);
  return { toast: msg ? <div className="toast" role="status">{msg}</div> : null, say: setMsg };
}

/** Run an async action, tracking busy + error so screens stay simple. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const run = async <T,>(f: () => Promise<T>): Promise<T | undefined> => {
    setBusy(true); setError("");
    try { return await f(); } catch (e: any) { setError(e.message || "Something went wrong."); } finally { setBusy(false); }
  };
  return { busy, error, run, clear: () => setError("") };
}

export function usePoll(fn: () => void, ms: number, on = true) {
  useEffect(() => { if (!on) return; fn(); const t = setInterval(fn, ms); return () => clearInterval(t); }, [on, ms]);
}
