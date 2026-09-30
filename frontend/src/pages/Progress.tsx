import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { PIPELINE, pipelineIndex } from "../copy";
import { useAction, usePoll } from "../hooks";
import { Banner, Button, Card, Check, Dots, Icon, Meter, Spinner } from "../ui";
import { cn } from "@/lib/utils";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

export const fmt = (sec: number | null | undefined) => {
  if (sec == null) return "";
  if (sec < 60) return `${sec} sec`;
  const m = Math.floor(sec / 60);
  return m < 60 ? `${m} min${sec % 60 >= 10 && m < 10 ? ` ${sec % 60} sec` : ""}` : `${Math.floor(m / 60)} h ${m % 60} min`;
};
const ICON: Record<string, string> = { ask: "✓", tool: "•", step: "▸", wait: "⏳", warn: "⚠", done: "✔", info: "·", llm: "·" };
const clock = (ts: string) => new Date(ts + "Z").toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });

export function Stepper({ stage, failed }: { stage: string; failed?: boolean }) {
  const at = pipelineIndex(stage);
  return (<div className="stepper" role="list" aria-label="Pipeline">{PIPELINE.map((p, i) => (
    <div key={p.key} role="listitem" className={`step ${i < at ? "done" : i === at ? "now" : ""}`} aria-current={i === at ? "step" : undefined}>
      <div className="dot">{i < at ? <Icon n="check" size={14} /> : i === at && !failed ? <Spinner className="size-3.5" /> : i + 1}</div>{p.title}</div>))}</div>);
}

const TIPS = ["Nothing on your website changes until you approve it.", "Every draft is tested in a sandbox copy of search results before you ever see it.", "You can leave this page. The round keeps running, and you'll find it under Optimize.",
  "More loops take longer, but usually find firmer improvements.", "Free AI plans allow only so many requests a minute, so short pauses are normal.", "The best draft is chosen by how it performs in the test, not by how it reads."];
function Tip() {
  const [i, setI] = useState(0);
  useEffect(() => { const t = setInterval(() => setI(n => n + 1), 6000); return () => clearInterval(t); }, []);
  const all = TIPS;
  return <p key={i} className="tip mt-4 mb-0 flex items-start gap-2 text-sm text-muted-foreground"><span className="mt-0.5 text-clay"><Icon n="tips" size={15} /></span>{all[i % all.length]}</p>;
}

/** What is happening right now: a real progress bar, a heartbeat, the loop, and a live feed. */
export default function Progress({ runId, stage, onChange, go }: { runId: number; stage: string; onChange?: () => void; go?: (v: any, ctx?: any) => void }) {
  const [live, setLive] = useState<any>(null);
  const [events, setEvents] = useState<any[]>([]);
  const [tech, setTech] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [misses, setMisses] = useState(0);
  const [open, setOpen] = useState<number | null>(null);
  const last = useRef(0);
  const seen = useRef(0);
  const stop = useAction();
  usePoll(async () => {
    try {
      const j = await api(`/runs/${runId}/live?after=${last.current}`);
      setLive(j); setMisses(j.known ? 0 : m => m + 1);
      if (j.events?.length) { last.current = j.last_seq; setEvents(e => [...e, ...j.events].slice(-400)); }
    } catch { /* keep the last picture */ }
  }, 1500);

  const known = live?.known;
  const pctv = known ? Math.round(live.pct) : null;
  const at = pipelineIndex(live?.stage ?? stage);
  const shown = events.filter(e => tech || e.kind !== "llm").slice().reverse().slice(0, 70);
  const newest = shown.find(e => e.kind !== "llm" && e.kind !== "tool") ?? shown[0];
  const fresh = seen.current; useEffect(() => { seen.current = events.length ? events[events.length - 1].seq : 0; }, [events]);
  const slow = known && live.idle_s > 180 && live.in_flight > 0;
  const stuck = known && live.idle_s > 600;
  const lp = known ? live.loop : null;
  const calm = known && (live.idle_s > 60 || live.waiting);
  return (<Card variant="hero">
    <div className="flex items-center gap-4"><span className={cn("orb", calm && "slow")} aria-hidden="true" />
      <div className="min-w-0 flex-1"><h2 className="m-0">Working on it<Dots className="ml-2 text-clay" /></h2>
        <p className="m-0 truncate text-sm text-muted-foreground" aria-live="polite">{newest ? newest.text : "Getting started…"}</p></div>
      {pctv !== null && <span className="tabular-nums font-serif text-4xl font-semibold" aria-label={`${pctv} percent done`}>{pctv}<span className="text-xl text-muted-foreground">%</span></span>}</div>
    <div className="mt-4 mb-5"><Meter value={(pctv ?? 3) / 100} after live /></div>
    <Stepper stage={live?.stage ?? stage} />
    <p className="mt-3.5 mb-0"><b>{PIPELINE[at].title}</b>{lp ? ` · loop ${lp.n} of up to ${lp.max}, ${lp.phase === "draft" ? "drafting changes" : "testing the draft"}` : ""}{known && live.stage_total > 0 && !lp ? ` · ${live.stage_done} of ${live.stage_total}` : lp && live.stage_total > 0 ? ` · ${live.stage_done} of ${live.stage_total} conversations` : ""}</p>
    <p className="text-muted-foreground text-sm mt-0.5 mb-3">{PIPELINE[at].detail}</p>
    <div className="row text-sm gap-x-5">
      {known && <span><span className={`pulse ${live.idle_s > 60 ? "slow" : ""}`} />{live.waiting ? `Slowing down on purpose (${live.waiting.seconds_left}s)` : live.in_flight > 0 ? `Waiting for the AI${live.in_flight > 1 ? ` (${live.in_flight} at once)` : ""}` : "Working"} · last activity {live.idle_s < 5 ? "just now" : `${fmt(live.idle_s)} ago`}</span>}
      {known && <span className="text-muted-foreground">Running for {fmt(live.elapsed_s)}{live.eta_s != null ? ` · roughly ${fmt(live.eta_s)} left` : ""}</span>}
      {known && <span className="text-muted-foreground">{live.llm_calls} AI requests</span>}
      {known && live.pace && <Tooltip><TooltipTrigger asChild><span className="text-muted-foreground">Speed: {live.pace.concurrency} at once{live.pace.rpm ? `, up to ${live.pace.rpm}/min` : ""}</span></TooltipTrigger><TooltipContent>Starts gently, speeds up while things go well, slows down if the service pushes back.</TooltipContent></Tooltip>}
    </div>
    <Tip />
    {known && live.waiting && <div className="mt-4"><Banner kind="clay"><b>{live.waiting.reason}</b> Free AI services allow only so many requests a minute, so Confiance is pausing for {live.waiting.seconds_left}s and then carries on. This is normal.</Banner></div>}
    {slow && !live.waiting && !stuck && <div className="mt-4"><Banner kind="info">The AI is taking a while. Large models can be slow, and it's still working.</Banner></div>}
    {stuck && <div className="mt-4"><Banner kind="warn"><b>Nothing has happened for {fmt(live.idle_s)}.</b> If this doesn't change soon, stop the round and try again. Finished stages are kept.</Banner></div>}
    {!known && misses >= 3 && <div className="mt-4"><Banner kind="info">Live details aren't available for this round (the app may have restarted), but progress is saved.</Banner></div>}
    <div className="row justify-between mt-5"><b>Live activity <span className="text-sm font-normal text-muted-foreground">· click a line for detail</span></b><span className="row"><Check className="text-sm" checked={tech} onChange={setTech}>Technical details</Check>{go && <Button kind="text" size="small" onClick={() => go("activity", { run: runId })}>Full history <Icon n="arrow" size={14} /></Button>}</span></div>
    <ul className="feed" aria-live="polite">{shown.length === 0 && <li className="text-muted-foreground">Waiting for the first update<Dots className="ml-2" /></li>}
      {shown.map(e => { const more = e.detail && Object.keys(e.detail).length > 0; const isOpen = open === e.seq;
        return (<li key={e.seq} className={cn(`k-${e.kind}`, e.seq > fresh && fresh > 0 && "fresh", "clickable flex-wrap")} onClick={() => setOpen(isOpen ? null : e.seq)}><span className="t">{clock(e.ts)}</span><span className="i">{ICON[e.kind] ?? "·"}</span>
          <span className={cn("min-w-0 flex-1 break-words", !isOpen && "line-clamp-2")}>{e.text}{tech && more && !isOpen && <span className="text-muted-foreground text-[0.78rem]"> {JSON.stringify(e.detail)}</span>}</span>
          {isOpen && <pre className="m-0 mt-1 w-full max-h-48 overflow-auto rounded-md bg-card p-2 text-[0.75rem] whitespace-pre-wrap break-words">{more ? JSON.stringify(e.detail, null, 2) : "No more detail was recorded for this line."}{`\n\n${e.kind} · ${new Date(e.ts + "Z").toLocaleString()}`}</pre>}</li>); })}</ul>
    <div className="row mt-5"><Button kind="danger" size="small" busy={stop.busy} disabled={stopping} onClick={() => confirm("Stop this round? What has been done so far is kept, and you can start a new round any time.") && stop.run(async () => { await api(`/runs/${runId}/cancel`, "POST"); setStopping(true); onChange?.(); })}><Icon n="stop" size={14} />{stopping ? "Stopping…" : "Stop this round"}</Button>
      {stopping && <span className="text-muted-foreground text-sm">It stops at the next step, usually within a minute.</span>}{stop.error && <span className="text-sm text-destructive">{stop.error}</span>}</div>
  </Card>);
}
