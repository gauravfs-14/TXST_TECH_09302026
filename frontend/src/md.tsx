import { ReactNode } from "react";

/** A tiny, safe markdown renderer for AI answers: paragraphs, lists, **bold**, `code`, links. It builds React nodes
 *  (never raw HTML), so an answer containing markup can't inject anything into the page. */
function inline(text: string, key: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\(https?:\/\/[^)\s]+\)|https?:\/\/[^\s)]+)/g;
  let last = 0, i = 0, m: RegExpExecArray | null;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const t = m[0];
    if (t.startsWith("**")) out.push(<strong key={`${key}b${i}`}>{t.slice(2, -2)}</strong>);
    else if (t.startsWith("`")) out.push(<code key={`${key}c${i}`}>{t.slice(1, -1)}</code>);
    else if (t.startsWith("[")) { const mm = /\[([^\]]+)\]\(([^)]+)\)/.exec(t)!; out.push(<a key={`${key}l${i}`} href={mm[2]} target="_blank" rel="noreferrer">{mm[1]}</a>); }
    else out.push(<a key={`${key}u${i}`} href={t} target="_blank" rel="noreferrer">{t.replace(/^https?:\/\//, "").slice(0, 60)}</a>);
    last = m.index + t.length; i++;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function Markdown({ text, className = "" }: { text: string; className?: string }) {
  const blocks: ReactNode[] = [];
  const lines = (text || "").replace(/\r/g, "").split("\n");
  let list: { ordered: boolean; items: string[] } | null = null;
  const flush = (k: number) => { if (list) { const L = list; blocks.push(L.ordered ? <ol key={`l${k}`}>{L.items.map((t, j) => <li key={j}>{inline(t, `${k}.${j}`)}</li>)}</ol> : <ul key={`l${k}`}>{L.items.map((t, j) => <li key={j}>{inline(t, `${k}.${j}`)}</li>)}</ul>); list = null; } };
  lines.forEach((raw, k) => {
    const line = raw.trimEnd();
    const ul = /^\s*[-*•]\s+(.*)$/.exec(line), ol = /^\s*\d+[.)]\s+(.*)$/.exec(line), h = /^(#{1,4})\s+(.*)$/.exec(line);
    if (ul) { if (!list || list.ordered) { flush(k); list = { ordered: false, items: [] }; } list.items.push(ul[1]); return; }
    if (ol) { if (!list || !list.ordered) { flush(k); list = { ordered: true, items: [] }; } list.items.push(ol[1]); return; }
    flush(k);
    if (h) blocks.push(<p key={k} className="md-h">{inline(h[2], `${k}`)}</p>);
    else if (line.trim()) blocks.push(<p key={k}>{inline(line, `${k}`)}</p>);
  });
  flush(lines.length);
  return <div className={`md ${className}`}>{blocks.length ? blocks : <p className="text-muted-foreground">(nothing)</p>}</div>;
}
