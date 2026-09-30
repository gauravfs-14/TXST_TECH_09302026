import { ReactNode, useState } from "react";
import { api } from "../api";
import { TaskFeed } from "../task";
import { Banner, Button, Check, Icon, toast, useAction } from "../ui";

/** "Suggest products from my website": reads the site, lists what it sells, and adds what you tick. */
export function SuggestProducts({ project, onAdded, extra, label = "Suggest products from my website" }: { project: any; onAdded: () => void; extra?: ReactNode; label?: string }) {
  const [items, setItems] = useState<any[] | null>(null);
  const [picked, setPicked] = useState<number[]>([]);
  const find = useAction(), add = useAction();
  const search = () => find.run(async (task) => { const r = await api(`/projects/${project.id}/products/suggest`, "POST", undefined, { task }); setItems(r.items); setPicked(r.items.map((_: any, i: number) => i)); });
  const save = () => add.run(async () => { await api(`/projects/${project.id}/products/add-many`, "POST", { items: (items ?? []).filter((_, i) => picked.includes(i)) }); toast("Products added"); setItems(null); onAdded(); });
  return (<div>
    {items === null ? <div className="row"><Button kind="quiet" busy={find.busy} onClick={search}><Icon n="spark" size={16} />{label}</Button>{extra}</div> :
      items.length === 0 ? <><p className="text-sm text-muted-foreground">Your site doesn't seem to sell anything specific, so there's nothing to suggest. If that's right, you don't need product questions: brand questions already cover your content. You can still add products yourself.</p><div className="row"><Button kind="text" onClick={() => setItems(null)}>Back</Button>{extra}</div></> : <div>
        <p className="mb-1.5 text-sm font-semibold">Tick the ones you sell:</p>
        {items.map((x, i) => <Check key={i} checked={picked.includes(i)} onChange={c => setPicked(c ? [...picked, i] : picked.filter(j => j !== i))}><span><b>{x.name}</b> {x.category && <span className="text-sm text-muted-foreground">{x.category}</span>}</span></Check>)}
        <div className="row mt-3"><Button busy={add.busy} disabled={!picked.length} onClick={save}>Add {picked.length} product{picked.length === 1 ? "" : "s"}</Button><Button kind="text" onClick={() => setItems(null)}>Cancel</Button></div></div>}
    <TaskFeed task={find.key} on={find.busy} title="Reading your site for products" />
    {(find.error || add.error) && <div className="mt-3"><Banner kind="bad">{find.error || add.error}</Banner></div>}</div>);
}
