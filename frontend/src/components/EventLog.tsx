import { ReactNode, useState } from "react";
import { describeAction } from "../copy";
import { Badge, Button, CodeBlock, Drawer, Icon, ago } from "../ui";
import { cn } from "@/lib/utils";

export type AuditRow = { id: number; ts: string; actor: string; action: string; payload: Record<string, any>; run_id: number | null; hash: string };

const humanKey = (k: string) => k.replace(/\bkb\b/g, "knowledge base").replace(/_/g, " ").replace(/^./, c => c.toUpperCase());
const isScalar = (v: any) => v == null || ["string", "number", "boolean"].includes(typeof v);
const when = (ts: string) => new Date(ts.endsWith("Z") ? ts : ts + "Z");
export const dayLabel = (ts: string) => { const d = when(ts), t = new Date(); const same = (a: Date, b: Date) => a.toDateString() === b.toDateString(); const y = new Date(t.getTime() - 864e5);
  return same(d, t) ? "Today" : same(d, y) ? "Yesterday" : d.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" }); };

/** A short "3 pages · score 62" style line, built from whatever the event recorded. */
export function gist(p: Record<string, any>): string {
  const bits: string[] = [];
  for (const [k, v] of Object.entries(p ?? {})) {
    if (bits.length >= 3) break;
    if (typeof v === "number" || typeof v === "boolean") bits.push(`${humanKey(k).toLowerCase()} ${v}`);
    else if (typeof v === "string" && v && v.length <= 48) bits.push(v);
    else if (Array.isArray(v)) bits.push(`${v.length} ${humanKey(k).toLowerCase()}`);
  }
  return bits.join(" · ");
}

function Val({ v }: { v: any }): ReactNode {
  if (v == null || v === "") return <span className="text-muted-foreground">none</span>;
  if (typeof v === "boolean") return <Badge tone={v ? "good" : undefined}>{v ? "Yes" : "No"}</Badge>;
  if (isScalar(v)) return <span className="break-words">{String(v)}</span>;
  if (Array.isArray(v) && v.every(isScalar)) return v.length ? <ul className="m-0 list-disc pl-5">{v.map((x, i) => <li key={i} className="break-words">{String(x)}</li>)}</ul> : <span className="text-muted-foreground">none</span>;
  return <pre className="m-0 max-h-56 overflow-auto rounded-lg bg-muted p-2.5 text-[0.78rem] break-words whitespace-pre-wrap">{JSON.stringify(v, null, 2)}</pre>;
}

export type RoundNames = Record<number, number>;
const roundName = (id: number, names?: RoundNames) => `Round ${names?.[id] ?? id}`;

export function EventDrawer({ ev, onClose, names }: { ev: AuditRow | null; onClose: () => void; names?: RoundNames }) {
  const [raw, setRaw] = useState(false);
  const entries = Object.entries(ev?.payload ?? {});
  return (<Drawer open={!!ev} onClose={() => { setRaw(false); onClose(); }} title={ev ? describeAction(ev.action) : ""}>{ev && <div className="space-y-4">
    <div className="row gap-2"><Badge tone={ev.actor === "user" ? "clay" : undefined}>{ev.actor === "user" ? "You did this" : "Confiance did this"}</Badge>{ev.run_id != null && <Badge>{roundName(ev.run_id, names)}</Badge>}
      <span className="text-sm text-muted-foreground" title={ev.ts}>{when(ev.ts).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "medium" })} · {ago(ev.ts)}</span></div>
    <div><h4 className="mb-2">What was recorded</h4>{entries.length === 0 ? <p className="text-sm text-muted-foreground">Nothing more than the event itself.</p> :
      <dl className="m-0 grid grid-cols-[minmax(110px,auto)_1fr] gap-x-4 gap-y-2.5 text-sm">{entries.map(([k, v]) => (<div key={k} className="contents"><dt className="font-medium text-muted-foreground">{humanKey(k)}</dt><dd className="m-0 min-w-0"><Val v={v} /></dd></div>))}</dl>}</div>
    <div><Button kind="text" size="small" onClick={() => setRaw(!raw)}><Icon n="down" size={15} />{raw ? "Hide" : "Show"} the technical record</Button>
      {raw && <div className="mt-2 space-y-2"><CodeBlock label="Exactly as saved" content={JSON.stringify({ event: ev.action, actor: ev.actor, time: ev.ts, round: ev.run_id, details: ev.payload }, null, 2)} filename={`event-${ev.id}.json`} />
        <p className="text-[0.78rem] text-muted-foreground break-all">Tamper-proof fingerprint: <span className="font-mono">{ev.hash}</span></p></div>}</div></div>}</Drawer>);
}

/** A clickable list of events, grouped by day. Each row opens the full record. */
export function EventList({ rows, showTech, empty, names }: { rows: AuditRow[]; showTech?: boolean; empty?: ReactNode; names?: RoundNames }) {
  const [open, setOpen] = useState<AuditRow | null>(null);
  if (rows.length === 0) return <>{empty ?? null}</>;
  let last = "";
  return (<>
    <div className="overflow-hidden rounded-xl border bg-card shadow-sm">{rows.map(r => {
      const d = dayLabel(r.ts), head = d !== last; last = d; const g = gist(r.payload);
      return (<div key={r.id}>{head && <div className="border-b bg-muted px-4 py-1.5 text-[0.72rem] font-semibold tracking-[.08em] text-muted-foreground uppercase [&:not(:first-child)]:border-t">{d}</div>}
        <button type="button" onClick={() => setOpen(r)} className="group flex w-full items-center gap-3 border-b px-4 py-2.5 text-left outline-none last:border-b-0 hover:bg-accent/50 focus-visible:bg-accent/60">
          <span className={cn("grid size-7 flex-none place-items-center rounded-full", r.actor === "user" ? "bg-clay-soft text-clay" : "bg-muted text-muted-foreground")}><Icon n={r.actor === "user" ? "edit" : "loop"} size={14} /></span>
          <span className="min-w-0 flex-1"><b className="font-semibold">{describeAction(r.action)}</b>{r.run_id != null && <span className="ml-2 text-[0.78rem] text-muted-foreground">{roundName(r.run_id, names)}</span>}
            {(g || showTech) && <span className="block truncate text-[0.82rem] text-muted-foreground">{g}{showTech && <span className="font-mono">{g ? " · " : ""}{r.action}</span>}</span>}</span>
          <span className="flex-none text-sm text-muted-foreground" title={r.ts}>{when(r.ts).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}</span>
          <span className="flex-none text-faint transition-transform group-hover:translate-x-0.5"><Icon n="chevron" size={16} /></span></button></div>);
    })}</div>
    <EventDrawer ev={open} onClose={() => setOpen(null)} names={names} /></>);
}
