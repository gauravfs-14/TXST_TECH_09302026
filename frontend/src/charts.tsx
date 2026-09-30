import { pct } from "./ui";

/** Circular score (0-100). */
export function Ring({ value, size = 84, label }: { value: number | null; size?: number; label?: string }) {
  const r = (size - 12) / 2, c = 2 * Math.PI * r, v = Math.max(0, Math.min(100, value ?? 0));
  const tone = value == null ? "var(--input)" : v >= 80 ? "var(--primary)" : v >= 55 ? "var(--clay)" : "var(--destructive)";
  return (<svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={`${label ?? "score"} ${value ?? "unknown"}`}>
    <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--border)" strokeWidth="8" />
    <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={tone} strokeWidth="8" strokeLinecap="round" strokeDasharray={`${(v / 100) * c} ${c}`} transform={`rotate(-90 ${size / 2} ${size / 2})`} style={{ transition: "stroke-dasharray .6s" }} />
    <text x="50%" y="50%" textAnchor="middle" dominantBaseline="central" style={{ font: `600 ${size * 0.3}px var(--font-serif)`, fill: "var(--foreground)" }}>{value == null ? "–" : Math.round(v)}</text></svg>);
}

export type Series = { name: string; color: string; points: (number | null)[] };
/** Line chart of 0-1 rates across rounds. */
export function Trend({ labels, series, height = 170 }: { labels: string[]; series: Series[]; height?: number }) {
  const W = 560, H = height, L = 34, R = 12, T = 10, B = 26, iw = W - L - R, ih = H - T - B;
  const x = (i: number) => L + (labels.length <= 1 ? iw / 2 : (i / (labels.length - 1)) * iw), y = (v: number) => T + (1 - v) * ih;
  return (<svg viewBox={`0 0 ${W} ${H}`} className="sparkline" role="img" aria-label="Trend across rounds">
    {[0, 0.25, 0.5, 0.75, 1].map(g => <g key={g}><line x1={L} x2={W - R} y1={y(g)} y2={y(g)} stroke="var(--border)" strokeWidth="1" /><text x={L - 6} y={y(g)} textAnchor="end" dominantBaseline="central" style={{ font: "10px var(--font-sans)", fill: "var(--faint)" }}>{Math.round(g * 100)}%</text></g>)}
    {labels.map((l, i) => <text key={i} x={x(i)} y={H - 8} textAnchor="middle" style={{ font: "10.5px var(--font-sans)", fill: "var(--muted-foreground)" }}>{l}</text>)}
    {series.map(s => { const pts = s.points.map((v, i) => (v == null ? null : [x(i), y(v)] as [number, number])); const path = pts.filter(Boolean).map((p, i) => `${i ? "L" : "M"}${p![0]},${p![1]}`).join(" ");
      return <g key={s.name}><path d={path} fill="none" stroke={s.color} strokeWidth="2.4" strokeLinejoin="round" strokeLinecap="round" />{pts.map((p, i) => p && <g key={i}><circle cx={p[0]} cy={p[1]} r="4" fill="var(--card)" stroke={s.color} strokeWidth="2.2" /><title>{`${s.name}: ${pct(s.points[i])}`}</title></g>)}</g>; })}</svg>);
}

/** One bar per loop showing the change in score; the kept loop is highlighted. */
export function LoopBars({ loops, best }: { loops: { n: number; delta: number | null; label?: string | null }[]; best?: number | null }) {
  const W = 560, H = 150, L = 8, T = 22, B = 30, ih = H - T - B, max = Math.max(0.15, ...loops.map(l => Math.abs(l.delta ?? 0))), zero = T + ih / 2;
  const bw = Math.min(70, (W - L * 2) / Math.max(loops.length, 1) - 16);
  return (<svg viewBox={`0 0 ${W} ${H}`} className="sparkline" role="img" aria-label="Change in score per loop">
    <line x1={L} x2={W - L} y1={zero} y2={zero} stroke="var(--input)" />
    {loops.map((l, i) => { const cx = L + ((i + 0.5) / loops.length) * (W - L * 2), d = l.delta ?? 0, h = (Math.abs(d) / max) * (ih / 2), up = d >= 0, isBest = l.n === best;
      return <g key={l.n}><rect x={cx - bw / 2} y={up ? zero - h : zero} width={bw} height={Math.max(h, 2)} rx="6" fill={isBest ? "var(--primary)" : up ? "var(--faint)" : "var(--destructive)"} opacity={isBest ? 1 : 0.75} />
        <text x={cx} y={up ? zero - h - 6 : zero + h + 14} textAnchor="middle" style={{ font: "600 11px var(--font-sans)", fill: "var(--foreground)" }}>{d >= 0 ? "+" : ""}{d.toFixed(2)}</text>
        <text x={cx} y={H - 8} textAnchor="middle" style={{ font: `${isBest ? 700 : 500} 11.5px var(--font-sans)`, fill: isBest ? "var(--primary)" : "var(--muted-foreground)" }}>Loop {l.n}{isBest ? " ★" : ""}</text></g>; })}</svg>);
}
