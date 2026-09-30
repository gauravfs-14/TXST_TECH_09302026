import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { fmt } from "./pages/Progress";
import { Dots, Spinner } from "./ui";

const ICON: Record<string, string> = { step: "›", ask: "✦", tool: "↗", wait: "◔", warn: "!", done: "✓", info: "·" };
const SHOW_AFTER_S = 5;

/** For anything that takes more than a few seconds: proof it is alive. A ticking clock, what the server is doing
 *  right now (its own words), and an honest note when the AI or a rate limit is the slow part. Hidden for quick tasks. */
export function TaskFeed({ task, on, title = "Working on it" }: { task: string | null; on: boolean; title?: string }) {
  const [secs, setSecs] = useState(0);
  const [live, setLive] = useState<any>(null);
  const [events, setEvents] = useState<any[]>([]);
  const last = useRef(0);
  useEffect(() => { setSecs(0); setLive(null); setEvents([]); last.current = 0; }, [task]);
  useEffect(() => { setSecs(0); if (!on) return; const t0 = Date.now(); const t = setInterval(() => setSecs(Math.floor((Date.now() - t0) / 1000)), 500); return () => clearInterval(t); }, [on, task]);
  const show = on && secs >= SHOW_AFTER_S;
  useEffect(() => {
    if (!show || !task) return;
    let dead = false;
    const tick = async () => {
      try {
        const j = await api(`/tasks/${encodeURIComponent(task)}/live?after=${last.current}`);
        if (dead) return;
        setLive(j);
        if (j.events?.length) { last.current = j.last_seq; setEvents(e => [...e, ...j.events].slice(-30)); }
      } catch { /* keep the last picture */ }
    };
    tick(); const t = setInterval(tick, 1200);
    return () => { dead = true; clearInterval(t); };
  }, [show, task]);
  if (!show) return null;
  const shown = events.filter(e => e.kind !== "llm").slice(-6).reverse();
  const idle = live?.known ? live.idle_s : null;
  return (<div className="mt-3 animate-in rounded-xl border bg-muted px-3.5 py-3 fade-in slide-in-from-top-1" role="status" aria-live="polite">
    <div className="row justify-between"><b className="inline-flex items-center gap-2"><Spinner /> {title}<Dots className="text-clay" /></b><span className="tabular-nums text-muted-foreground text-sm" aria-label={`${secs} seconds so far`}>{fmt(secs)}</span></div>
    <div className="indet mt-2.5" aria-hidden="true" />
    {live?.waiting ? <p className="text-sm" style={{ margin: ".4rem 0 0", color: "var(--clay)" }}>{live.waiting.reason} Resuming in about {live.waiting.seconds_left}s. Nothing is wrong.</p>
      : <p className="text-muted-foreground text-sm" style={{ margin: ".4rem 0 0" }}>{live?.in_flight ? "Waiting for the AI to answer. That can take a little while, and it's still working." : "Still working. Nothing is stuck."}</p>}
    {shown.length > 0 && <ul className="feed" style={{ maxHeight: 150 }}>{shown.map((e, i) => <li key={e.seq} className={`k-${e.kind} ${i === 0 ? "fresh" : ""}`} style={{ opacity: i === 0 ? 1 : 0.65 }}><span className="i">{ICON[e.kind] ?? "·"}</span><span>{e.text}</span></li>)}</ul>}
    {live?.known && <p className="text-muted-foreground text-[0.78rem]" style={{ margin: ".4rem 0 0" }}>{live.llm_calls > 0 ? `${live.llm_calls} AI request${live.llm_calls === 1 ? "" : "s"} finished · ` : ""}last update {idle != null && idle < 2 ? "just now" : `${idle ?? 0}s ago`}</p>}
  </div>);
}
