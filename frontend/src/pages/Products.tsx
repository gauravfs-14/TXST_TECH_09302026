import { useState } from "react";
import { api } from "../api";
import { useAction, useApi } from "../hooks";
import { Badge, Banner, Button, Card, Choice, Drawer, Empty, Field, Icon, Meter, Modal, PageHead, Skeleton, TableBox, pct, toast } from "../ui";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { TaskFeed } from "../task";
import { SuggestProducts } from "@/components/SuggestProducts";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";
import type { Go } from "../App";

const blank = { name: "", sku: "", url: "", category: "", brand: "", price: "" };

function Form({ init, onSave, onCancel }: { init: any; onSave: (v: any) => Promise<void>; onCancel: () => void }) {
  const [v, setV] = useState({ ...blank, ...init });
  const { busy, error, run } = useAction();
  const f = (k: string, label: string, ph = "") => <Field label={label}><Input type="text" value={v[k] ?? ""} placeholder={ph} onChange={e => setV({ ...v, [k]: e.target.value })} /></Field>;
  return (<div>{f("name", "Product name", "For example: Trail Runner 2")}{f("sku", "SKU (optional)", "TR-2-BLK")}{f("url", "Product page address (optional)", "https://…")}{f("category", "Category (optional)", "Running shoes")}{f("brand", "Brand (optional)")}{f("price", "Price (optional)", "$89")}
    {error && <Banner kind="bad">{error}</Banner>}<div className="row"><Button busy={busy} disabled={!v.name.trim()} onClick={() => run(() => onSave(v))}>Save</Button><Button kind="text" onClick={onCancel}>Cancel</Button></div></div>);
}

export default function Products({ project, ctx, go }: { project: any; ctx: any; go: Go }) {
  const p = useApi<any[]>(`/projects/${project.id}/products`);
  const [edit, setEdit] = useState<any | null | false>(false);
  const [imp, setImp] = useState(false);
  const [find, setFind] = useState(false);
  const [csv, setCsv] = useState("");
  const [sel, setSel] = useState<any | null>(null);
  const act = useAction();
  const list = p.data ?? [];
  const reload = () => p.reload();
  // Shopper questions are written for you whenever products are added or renamed: there's no separate step to remember.
  const write = (force = false) => act.run(async (task) => { await api(`/projects/${project.id}/products/queries${force ? "?force=true" : ""}`, "POST", undefined, { task }); reload(); });
  const changed = () => { reload(); write(); };
  return (<div className="page">
    <PageHead title="Products" sub="Track how shoppers' questions rank each product, separately from your brand. Shopper questions are written for you automatically." actions={<>
      {ctx?.from === "optimize" && <Button kind="quiet" onClick={() => go("optimize", { draft: ctx.draft })}>← Back to Optimize</Button>}
      <Button onClick={() => setEdit(null)}><Icon n="plus" size={16} />Add a product</Button>
      <DropdownMenu><DropdownMenuTrigger asChild><Button kind="quiet"><Icon n="more" size={16} />More<Icon n="down" size={14} /></Button></DropdownMenuTrigger>
        <DropdownMenuContent><DropdownMenuItem onSelect={() => setFind(true)}><Icon n="spark" size={16} />Suggest from my website</DropdownMenuItem>
          <DropdownMenuItem onSelect={() => setImp(true)}><Icon n="file" size={16} />Import from a spreadsheet (CSV)</DropdownMenuItem>
          {list.length > 0 && <DropdownMenuItem onSelect={() => write(true)}><Icon n="refresh" size={16} />Rewrite all shopper questions</DropdownMenuItem>}</DropdownMenuContent></DropdownMenu></>} />
    {act.error && <Banner kind="bad">{act.error}</Banner>}
    <TaskFeed task={act.key} on={act.busy} title="Writing shopper questions" />
    {!p.data ? <Skeleton h={300} /> : list.length === 0 ? <Card variant="hero"><h2>Add the products you want to be found for</h2><p className="text-muted-foreground">We didn't find any on your website, so tell us what you sell. Pick whichever is quickest:</p>
      <div className="grid g3 mt-3"><Choice icon="spark" title="Suggest from my website" text="We read your site and list what it seems to sell. You tick the right ones." onClick={() => setFind(true)} />
        <Choice icon="plus" title="Add one by hand" text="Type a product name. Everything else is optional." onClick={() => setEdit(null)} />
        <Choice icon="file" title="Import a spreadsheet" text="Paste a CSV with a name column and, if you have them, SKU, price and more." onClick={() => setImp(true)} /></div></Card> : (
      <TableBox><Table><TableHeader><TableRow><TableHead>Product</TableHead><TableHead>SKU</TableHead><TableHead>Search rank</TableHead><TableHead>Named by assistants</TableHead><TableHead>Linked</TableHead><TableHead /></TableRow></TableHeader><TableBody>
        {list.map(x => (<TableRow key={x.id} className={cn("cursor-pointer", !x.active && "opacity-55")} onClick={() => setSel(x)}>
          <TableCell className="whitespace-normal"><b>{x.name}</b><div className="text-muted-foreground text-[0.78rem]">{x.category || ""}{x.source !== "manual" && <> · found on your site{x.confidence ? ` (${x.confidence})` : ""}</>}</div></TableCell><TableCell className="font-mono text-sm">{x.sku || "–"}</TableCell>
          <TableCell>{x.visibility?.search_rank ? `#${x.visibility.search_rank}` : <span className="text-muted-foreground">–</span>}</TableCell>
          <TableCell className="min-w-[150px]">{x.visibility?.named != null ? <div className="flex items-center gap-2"><div className="flex-1"><Meter value={x.visibility.named} /></div><b className="tabular-nums text-sm">{pct(x.visibility.named)}</b></div> : <span className="text-muted-foreground text-sm">Not measured</span>}</TableCell>
          <TableCell className="tabular-nums">{x.visibility?.linked != null ? pct(x.visibility.linked) : "–"}</TableCell><TableCell><span className="flex items-center gap-1">{!x.active && <Badge>Paused</Badge>}<Icon n="chevron" size={16} /></span></TableCell></TableRow>))}</TableBody></Table></TableBox>)}
    <Modal open={edit !== false} onClose={() => setEdit(false)} title={edit ? "Edit product" : "Add a product"}>{edit !== false && <Form init={edit ?? {}} onCancel={() => setEdit(false)} onSave={async v => { edit ? await api(`/products/${edit.id}`, "PATCH", v) : await api(`/projects/${project.id}/products`, "POST", v); setEdit(false); toast("Saved"); changed(); }} />}</Modal>
    <Modal open={imp} onClose={() => setImp(false)} title="Import products from CSV"><p className="text-muted-foreground text-sm">Paste a spreadsheet exported as CSV. The first line must have a <b>name</b> column; sku, url, category, brand and price are optional.</p>
      <Textarea rows={9} value={csv} onChange={e => setCsv(e.target.value)} placeholder={"name,sku,url,category,price\nTrail Runner 2,TR-2,https://…,Running shoes,$89"} className="font-mono text-[0.85rem]" />
      <div className="row mt-4"><Button disabled={!csv.trim()} onClick={() => act.run(async () => { const r = await api(`/projects/${project.id}/products/import`, "POST", { csv }); toast(`Added ${r.added}, skipped ${r.skipped} duplicate(s)`); setImp(false); setCsv(""); changed(); })}>Import</Button></div></Modal>
    <Modal open={find} onClose={() => setFind(false)} title="Suggest products from my website"><p className="text-muted-foreground text-sm">We read your site and list the products or services it seems to offer. Nothing is added until you tick it.</p>
      <SuggestProducts project={project} label="Read my website and suggest" onAdded={() => { setFind(false); changed(); }} /></Modal>
    <Drawer open={!!sel} onClose={() => setSel(null)} title={sel?.name ?? ""}>{sel && <div className="space-y-3.5">
      <p className="text-muted-foreground text-sm">{[sel.brand, sel.category, sel.price, sel.sku && `SKU ${sel.sku}`].filter(Boolean).join(" · ")}{sel.url && <><br /><a href={sel.url} target="_blank" rel="noreferrer">{sel.url}</a></>}</p>
      {sel.visibility && <Card tight variant="flat" title={`Round ${sel.visibility.round}`}><p className="text-sm" style={{ margin: 0 }}>Named in <b>{pct(sel.visibility.named)}</b> of answers{sel.visibility.named_after != null && <> → <b>{pct(sel.visibility.named_after)}</b> with changes</>}. Linked in {pct(sel.visibility.linked)}.</p></Card>}
      <div><h4>Shopper questions we ask</h4>{sel.queries?.length ? <ul className="text-sm list-disc pl-5">{sel.queries.map((q: any, i: number) => <li key={i}>{q.text ?? q}</li>)}</ul> : <p className="text-muted-foreground text-sm">{act.busy ? "Being written now…" : <>None yet. <Button kind="text" size="small" onClick={() => write()}>Write them now</Button></>}</p>}</div>
      <div className="row"><Button kind="quiet" size="small" onClick={() => { setEdit(sel); setSel(null); }}><Icon n="edit" size={15} />Edit</Button>
        <Button kind="quiet" size="small" onClick={() => act.run(async () => { await api(`/products/${sel.id}`, "PATCH", { active: !sel.active }); setSel(null); reload(); })}>{sel.active ? "Pause tracking" : "Resume tracking"}</Button>
        <Button kind="danger" size="small" onClick={() => confirm("Remove this product?") && act.run(async () => { await api(`/products/${sel.id}`, "DELETE"); setSel(null); reload(); })}><Icon n="trash" size={15} />Remove</Button></div></div>}</Drawer>
  </div>);
}
