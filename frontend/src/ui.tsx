import { ReactNode, useRef, useState } from "react";
import {
  ArrowRight, Check as CheckIcon, ChevronDown, ChevronRight, Ellipsis, Lightbulb, Minus, SlidersHorizontal, CircleAlert, Clock, Copy, Download, Eye, FileText, Globe, House, Info, KeyRound, Leaf, Link as LinkIcon, ListChecks, Loader2,
  MessageSquare, Package, Pencil, Plus, Printer, Play, RefreshCw, Repeat, Search, Settings, ShieldCheck, Sparkles, Square, Tag, Trash2, TriangleAlert, Undo2, X,
  type LucideIcon,
} from "lucide-react";
import { toast as sonner } from "sonner";
import { Alert } from "@/components/ui/alert";
import { Badge as ShBadge } from "@/components/ui/badge";
import { Button as ShButton } from "@/components/ui/button";
import { Card as ShCard, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Select as ShSelect, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton as ShSkeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Tabs as ShTabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Toaster as ShToaster } from "@/components/ui/sonner";
import { cn } from "@/lib/utils";
export { useAction, usePoll } from "./hooks";

/* ---------- icons (lucide, under the short names the pages use) ---------- */
const ICONS = {
  leaf: Leaf, check: CheckIcon, search: Search, spark: Sparkles, globe: Globe, shield: ShieldCheck, box: Package, chat: MessageSquare, key: KeyRound, arrow: ArrowRight, undo: Undo2,
  download: Download, clock: Clock, plus: Plus, edit: Pencil, home: House, eye: Eye, loop: Repeat, list: ListChecks, tag: Tag, file: FileText, gear: Settings, copy: Copy,
  minus: Minus, down: ChevronDown, more: Ellipsis, tips: Lightbulb, sliders: SlidersHorizontal,
  alert: TriangleAlert, info: Info, x: X, chevron: ChevronRight, trash: Trash2, print: Printer, stop: Square, play: Play, refresh: RefreshCw, link: LinkIcon,
} satisfies Record<string, LucideIcon>;
export type IconName = keyof typeof ICONS;
export const Icon = ({ n, size = 20 }: { n: IconName; size?: number }) => { const C = ICONS[n]; return <C size={size} strokeWidth={1.8} aria-hidden="true" />; };
export const Spinner = ({ className }: { className?: string }) => <Loader2 className={cn("size-3.5 animate-spin text-clay", className)} aria-hidden="true" />;

/* ---------- toasts (sonner) ---------- */
export const toast = (msg: string) => { sonner(msg); };
export const Toaster = () => <ShToaster position="bottom-center" />;

/* ---------- primitives ---------- */
type Kind = "primary" | "quiet" | "text" | "danger";
const VARIANT = { primary: "default", quiet: "outline", text: "ghost", danger: "outline" } as const;
export function Button({ kind = "primary", size, busy, asChild, children, className, ...p }: { kind?: Kind; size?: "big" | "small" | "icon"; busy?: boolean; asChild?: boolean; children: ReactNode } & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (<ShButton {...p} asChild={asChild} variant={VARIANT[kind]} size={size === "big" ? "lg" : size === "small" ? "sm" : size === "icon" ? "icon" : "default"} disabled={p.disabled || busy}
    className={cn(size === "big" && "h-11 px-7 text-base", kind === "danger" && "text-destructive hover:bg-danger-soft hover:text-destructive dark:hover:bg-danger-soft", kind === "text" && "text-muted-foreground hover:text-foreground", className)}>
    {asChild ? children : <>{busy && <Spinner />}{children}</>}</ShButton>);
}

type CardVariant = "hero" | "sunk" | "flat";
export const Card = ({ title, actions, children, className, tight, variant }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; tight?: boolean; variant?: CardVariant }) => (
  <ShCard className={cn("gap-3 py-5", tight && "py-4", variant === "hero" && "bg-gradient-to-br from-card to-muted py-6", variant === "sunk" && "bg-muted shadow-none", variant === "flat" && "shadow-none", className)}>
    {(title || actions) && <CardHeader className="items-center"><CardTitle role="heading" aria-level={2} className="font-serif text-lg leading-snug">{title}</CardTitle>{actions && <CardAction className="flex flex-wrap items-center gap-2 self-center">{actions}</CardAction>}</CardHeader>}
    <CardContent>{children}</CardContent></ShCard>);

const TONE_TEXT = { good: "text-success", warn: "text-clay", bad: "text-destructive" } as const;
export const Stat = ({ label, value, sub, tone, plain }: { label: string; value: ReactNode; sub?: ReactNode; tone?: "good" | "warn" | "bad"; plain?: boolean }) => (
  <ShCard className="min-h-[116px] gap-1 py-4"><CardContent className="flex h-full flex-col gap-1">
    <span className="text-[0.8rem] font-medium text-muted-foreground">{label}</span>
    {plain ? value : <span className={cn("tabular-nums font-serif text-3xl leading-tight font-semibold", tone && TONE_TEXT[tone])}>{value}</span>}
    {sub && <span className="mt-auto text-[0.82rem] text-muted-foreground">{sub}</span>}</CardContent></ShCard>);

export const Badge = ({ tone, children, className }: { tone?: "good" | "warn" | "bad" | "clay"; children: ReactNode; className?: string }) => <ShBadge variant={tone ?? "neutral"} className={className}>{children}</ShBadge>;

export function Tabs<T extends string>({ value, onChange, items }: { value: T; onChange: (v: T) => void; items: { id: T; label: ReactNode }[] }) {
  return (<ShTabs value={value} onValueChange={v => onChange(v as T)} className="max-w-full"><TabsList className="h-auto max-w-full justify-start overflow-x-auto">
    {items.map(i => <TabsTrigger key={i.id} value={i.id} className="px-3 py-1.5">{i.label}</TabsTrigger>)}</TabsList></ShTabs>);
}

const BANNER_ICON = { info: Info, warn: TriangleAlert, bad: CircleAlert, clay: Info } as const;
export const Banner = ({ kind = "info", children }: { kind?: "info" | "warn" | "bad" | "clay"; children: ReactNode }) => { const I = BANNER_ICON[kind];
  return <Alert variant={kind} role={kind === "bad" ? "alert" : "status"}><I /><div data-slot="alert-description" className="col-start-2 text-sm">{children}</div></Alert>; };

export const PageHead = ({ title, sub, actions }: { title: ReactNode; sub?: ReactNode; actions?: ReactNode }) => (
  <header className="mb-6 flex flex-wrap items-end justify-between gap-4"><div><h1>{title}</h1>{sub && <p className="mt-1 mb-0 text-muted-foreground">{sub}</p>}</div>{actions && <div className="flex flex-wrap items-center gap-2.5">{actions}</div>}</header>);
export const Empty = ({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) => (
  <div className="px-5 py-10 text-center text-muted-foreground"><h3 className="mb-1 text-foreground">{title}</h3>{children && <p>{children}</p>}{action}</div>);
export const Skeleton = ({ h = 16, w = "100%", className = "" }: { h?: number; w?: number | string; className?: string }) => <ShSkeleton className={className} style={{ height: h, width: w }} aria-hidden="true" />;
export const SkeletonCards = ({ n = 4, h = 116 }: { n?: number; h?: number }) => <div className="grid g4">{Array.from({ length: n }, (_, i) => <Skeleton key={i} h={h} />)}</div>;
export const TableBox = ({ children }: { children: ReactNode }) => <div className="rounded-xl border bg-card px-2 py-1 shadow-sm">{children}</div>;

export function Meter({ value, after, warn, live }: { value: number; after?: boolean; warn?: boolean; live?: boolean }) {
  const v = Math.max(0, Math.min(1, value || 0));
  return <Progress value={Math.max(2, Math.round(v * 100))} aria-label={`${Math.round(v * 100)} percent`} className={cn("h-2.5 min-w-[60px] border bg-muted", live && "live-bar h-3", after ? "[&>div]:bg-primary" : warn ? "[&>div]:bg-clay" : "[&>div]:bg-faint")} />;
}
export const pct = (x: number | null | undefined) => (x == null ? "n/a" : `${Math.round(x * 100)}%`);
export const signed = (x: number | null | undefined, d = 2) => (x == null ? "n/a" : `${x >= 0 ? "+" : ""}${x.toFixed(d)}`);
export const ago = (ts?: string | null) => {
  if (!ts) return "";
  const d = new Date(ts.endsWith("Z") ? ts : ts + "Z"), s = (Date.now() - d.getTime()) / 1000;
  if (s < 60) return "just now"; if (s < 3600) return `${Math.floor(s / 60)} min ago`; if (s < 86400) return `${Math.floor(s / 3600)} h ago`; if (s < 86400 * 14) return `${Math.floor(s / 86400)} d ago`;
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
};

/* ---------- forms ---------- */
export const Field = ({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) => (
  <div className="mb-4 grid gap-1.5"><Label className="text-[0.94rem]">{label}</Label>{hint && <p className="m-0 text-[0.86rem] text-muted-foreground">{hint}</p>}{children}</div>);
const EMPTY = "__empty__";
export function Select({ value, onChange, options, label, className }: { value: string; onChange: (v: string) => void; options: { value: string; label: string }[]; label: string; className?: string }) {
  return (<ShSelect value={value === "" ? EMPTY : value} onValueChange={v => onChange(v === EMPTY ? "" : v)}>
    <SelectTrigger aria-label={label} className={cn("w-full bg-card", className)}><SelectValue /></SelectTrigger>
    <SelectContent>{options.map(o => <SelectItem key={o.value} value={o.value === "" ? EMPTY : o.value}>{o.label}</SelectItem>)}</SelectContent></ShSelect>);
}
export function Check({ checked, onChange, children, className }: { checked: boolean; onChange: (v: boolean) => void; children: ReactNode; className?: string }) {
  return <Label className={cn("cursor-pointer items-center gap-2.5 py-1 font-normal", className)}><Checkbox checked={checked} onCheckedChange={v => onChange(v === true)} />{children}</Label>;
}
export function Toggle({ checked, onChange, label, hint }: { checked: boolean; onChange: (v: boolean) => void; label: string; hint?: string }) {
  return (<Label className="cursor-pointer items-center justify-between gap-4 py-2"><span><b className="font-semibold">{label}</b>{hint && <span className="block text-sm font-normal text-muted-foreground">{hint}</span>}</span>
    <Switch checked={checked} onCheckedChange={onChange} /></Label>);
}
export function ListInput({ values, onChange, placeholder, addLabel }: { values: string[]; onChange: (v: string[]) => void; placeholder: string; addLabel: string }) {
  return (<div>
    {values.map((v, i) => (<div className="mb-2 flex items-center gap-2" key={i}>
      <Input type="text" value={v} aria-label={placeholder} placeholder={placeholder} onChange={e => onChange(values.map((x, j) => (j === i ? e.target.value : x)))} />
      <Button kind="text" size="icon" aria-label="Remove" onClick={() => onChange(values.filter((_, j) => j !== i))}><X /></Button></div>))}
    <Button kind="quiet" size="small" onClick={() => onChange([...values, ""])}><Plus />{addLabel}</Button></div>);
}
export function Choice({ icon, title, text, on, disabled, onClick, badge }: { icon: IconName; title: string; text: string; on?: boolean; disabled?: boolean; onClick?: () => void; badge?: string }) {
  return (<button type="button" disabled={disabled} onClick={onClick} aria-pressed={on}
    className={cn("flex w-full items-start gap-3.5 rounded-xl border-[1.5px] bg-card p-3.5 text-left transition-colors outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-55", on ? "border-primary bg-success-soft" : "border-input enabled:hover:border-primary")}>
    <span className="grid size-9 flex-none place-items-center rounded-lg bg-muted text-primary"><Icon n={icon} /></span>
    <span><b>{title}</b> {badge && <Badge>{badge}</Badge>}<br /><span className="text-sm text-muted-foreground">{text}</span></span>
    <span className={cn("ml-auto text-primary", on ? "opacity-100" : "opacity-0")}><Icon n="check" /></span></button>);
}

/** A number with themed − / + buttons (the browser's own arrows don't match the theme). Typing works too. */
export function NumberField({ value, onChange, min = 0, max = 99, step = 1, label, suffix, disabled, className }: { value: number; onChange: (v: number) => void; min?: number; max?: number; step?: number; label: string; suffix?: string; disabled?: boolean; className?: string }) {
  const [text, setText] = useState<string | null>(null);
  const clamp = (n: number) => Math.max(min, Math.min(max, Math.round(n / step) * step));
  const commit = () => { if (text !== null) { const n = parseFloat(text); if (!Number.isNaN(n)) onChange(clamp(n)); setText(null); } };
  return (<div role="group" aria-label={label} className={cn("inline-flex h-10 w-fit items-center overflow-hidden rounded-lg border border-input bg-card shadow-xs focus-within:border-ring focus-within:ring-[3px] focus-within:ring-ring/50", disabled && "pointer-events-none opacity-50", className)}>
    <button type="button" aria-label={`Less ${label}`} disabled={disabled || value <= min} onClick={() => onChange(clamp(value - step))} className="grid h-full w-10 place-items-center text-muted-foreground transition-colors outline-none hover:bg-accent hover:text-foreground disabled:opacity-35 disabled:hover:bg-transparent"><Minus size={16} /></button>
    <input inputMode="numeric" aria-label={label} value={text ?? String(value)} disabled={disabled} onFocus={e => e.currentTarget.select()} onChange={e => setText(e.target.value.replace(/[^\d.]/g, ""))} onBlur={commit} onKeyDown={e => { if (e.key === "Enter") commit(); if (e.key === "ArrowUp") { e.preventDefault(); onChange(clamp(value + step)); } if (e.key === "ArrowDown") { e.preventDefault(); onChange(clamp(value - step)); } }}
      className="h-full w-14 border-x bg-transparent text-center text-base font-semibold tabular-nums outline-none" />
    {suffix && <span className="border-r px-2.5 text-sm text-muted-foreground">{suffix}</span>}
    <button type="button" aria-label={`More ${label}`} disabled={disabled || value >= max} onClick={() => onChange(clamp(value + step))} className="grid h-full w-10 place-items-center text-muted-foreground transition-colors outline-none hover:bg-accent hover:text-foreground disabled:opacity-35 disabled:hover:bg-transparent"><Plus size={16} /></button></div>);
}

/** The one thing to do next, said plainly, with a single button. */
export function NextStep({ title, children, action, tone = "primary" }: { title: ReactNode; children?: ReactNode; action?: ReactNode; tone?: "primary" | "clay" }) {
  return (<div className={cn("mb-5 flex flex-wrap items-center justify-between gap-4 rounded-xl border-[1.5px] px-5 py-4 animate-in fade-in slide-in-from-top-1", tone === "clay" ? "border-clay/50 bg-clay-soft" : "border-primary/40 bg-success-soft")}>
    <div className="flex min-w-0 flex-1 items-start gap-3.5"><span className={cn("mt-0.5 grid size-9 flex-none place-items-center rounded-full text-primary-foreground", tone === "clay" ? "bg-clay" : "bg-primary")}><ArrowRight size={18} /></span>
      <div className="min-w-[220px]"><div className="text-[0.72rem] font-semibold tracking-[.1em] text-muted-foreground uppercase">Your next step</div><div className="font-serif text-lg leading-snug font-semibold">{title}</div>{children && <div className="mt-0.5 text-sm text-muted-foreground">{children}</div>}</div></div>
    {action}</div>);
}

/** Three softly bouncing dots: "something is happening". */
export const Dots = ({ className }: { className?: string }) => <span className={cn("dots", className)} aria-hidden="true"><i /><i /><i /></span>;

/** A wizard header: numbered steps you can click back to. */
export function Steps({ steps, at, onGo }: { steps: string[]; at: number; onGo?: (i: number) => void }) {
  return (<ol className="m-0 mb-5 flex list-none gap-2 p-0" aria-label="Steps">{steps.map((s, i) => (<li key={s} className="flex-1">
    <button type="button" disabled={i > at || !onGo} onClick={() => onGo?.(i)} aria-current={i === at ? "step" : undefined} className={cn("group flex w-full items-center gap-2.5 rounded-lg border px-3 py-2 text-left text-sm outline-none transition-colors focus-visible:ring-[3px] focus-visible:ring-ring/50", i === at ? "border-primary bg-success-soft font-semibold" : i < at ? "bg-card enabled:hover:border-primary" : "bg-muted text-faint")}>
      <span className={cn("grid size-6 flex-none place-items-center rounded-full text-xs font-bold", i < at ? "bg-primary text-primary-foreground" : i === at ? "bg-clay text-primary-foreground" : "bg-border text-muted-foreground")}>{i < at ? <CheckIcon size={13} /> : i + 1}</span>
      <span className="max-[560px]:hidden">{s}</span></button></li>))}</ol>);
}

/* ---------- overlays ---------- */
export function Drawer({ open, onClose, title, children }: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode }) {
  return (<Sheet open={open} onOpenChange={o => !o && onClose()}><SheetContent className="w-full gap-0 overflow-y-auto p-6 sm:max-w-[640px]">
    <SheetHeader className="mb-4 p-0"><SheetTitle className="font-serif text-xl">{title}</SheetTitle><SheetDescription className="sr-only">Details</SheetDescription></SheetHeader>{children}</SheetContent></Sheet>);
}
export function Modal({ open, onClose, title, children }: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode }) {
  return (<Dialog open={open} onOpenChange={o => !o && onClose()}><DialogContent className="max-h-[88vh] overflow-y-auto p-6 sm:max-w-[560px]">
    <DialogHeader><DialogTitle className="font-serif text-xl">{title}</DialogTitle><DialogDescription className="sr-only">Dialog</DialogDescription></DialogHeader>{children}</DialogContent></Dialog>);
}

/* ---------- code / drafts ---------- */
export function CodeBlock({ label, content, filename, language }: { label?: string; content: string; filename?: string; language?: string }) {
  const [done, setDone] = useState(false);
  const timer = useRef<any>(undefined);
  const copy = async () => { try { await navigator.clipboard.writeText(content); setDone(true); clearTimeout(timer.current); timer.current = setTimeout(() => setDone(false), 1800); } catch { toast("Couldn't copy. Select the text and copy it."); } };
  const save = () => { const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([content], { type: "text/plain" })); a.download = filename || "draft.txt"; a.click(); URL.revokeObjectURL(a.href); };
  return (<div className="rounded-xl border bg-muted"><div className="flex items-center justify-between border-b py-1 pr-2 pl-3.5 text-[0.78rem] text-muted-foreground"><span>{label ?? language ?? "Draft"}{filename && <span className="font-mono"> · {filename}</span>}</span>
    <span className="flex gap-0.5"><Button kind="text" size="small" onClick={copy}><Icon n={done ? "check" : "copy"} size={15} />{done ? "Copied" : "Copy"}</Button>{filename && <Button kind="text" size="small" onClick={save}><Icon n="download" size={15} />Save</Button>}</span></div>
    <pre className="m-0 max-h-[340px] overflow-auto px-4 py-3.5 text-[0.82rem] break-words whitespace-pre-wrap">{content}</pre></div>);
}

/* ---------- a long AI answer, in a scrollable box ---------- */
export const Answer = ({ children }: { children: ReactNode }) => <div className="max-h-[420px] overflow-auto rounded-xl border bg-muted px-3.5 py-3 text-[0.92rem]">{children}</div>;
