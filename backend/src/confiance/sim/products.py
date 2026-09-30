"""Product / SKU visibility: the questions a shopper asks, and how an AI answer treats a specific product.

Brand visibility asks "does the assistant know and recommend us?". Product visibility asks "when someone
wants this kind of product, is *this* product named, linked and near the top of the list?" They are measured
side by side because they fail for different reasons and are fixed by different work."""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import activity, llm
from ..models import Product
from ..textutil import norm_url

TRACK_RE = re.compile(r"^p(\d+)\.")
LIST_ITEM = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s+(.*)$")


def track_of(question_id: str) -> str:
    return "product" if TRACK_RE.match(question_id) else "brand"


def product_id_of(question_id: str) -> int | None:
    m = TRACK_RE.match(question_id)
    return int(m.group(1)) if m else None


def default_queries(p: dict) -> list[dict]:
    """Deterministic questions that need no AI. Ids are 'p<product id>.<n>'."""
    name, cat = p["name"].strip(), (p.get("category") or "").strip()
    generic = cat or " ".join(name.split()[-2:])
    out = [{"kind": "specific", "text": f"Is the {name} any good? What do reviews say?"},
           {"kind": "category", "text": f"What is the best {generic.lower()} to buy?"}]
    if p.get("sku"):
        out.append({"kind": "specific", "text": f"{name} {p['sku']} specs and price"})
    return [{"id": f"p{p['id']}.{i + 1}", **q} for i, q in enumerate(out)]


QUERY_SCHEMA = {"type": "object", "properties": {"products": {"type": "array", "items": {
    "type": "object", "properties": {"index": {"type": "integer"}, "use_case": {"type": "string"}, "comparison": {"type": "string"}},
    "required": ["index", "use_case", "comparison"], "additionalProperties": False}}}, "required": ["products"], "additionalProperties": False}


def generate_queries(s: Session, project_id: int, business: str, kb_card: str = "", only_missing: bool = True) -> int:
    """Write shopper questions onto each active product. One AI call covers several products; if it fails the
    deterministic questions are still saved, so this never blocks a round."""
    prods = list(s.scalars(select(Product).where(Product.project_id == project_id, Product.active)))
    todo = [p for p in prods if not (only_missing and p.queries)]
    for p in todo:
        p.queries = default_queries({"id": p.id, "name": p.name, "sku": p.sku, "category": p.category})
    for i in range(0, len(todo), 6):
        activity.emit(f"Writing shopper questions for products {i + 1} to {min(i + 6, len(todo))} of {len(todo)}…", "step")
        chunk = todo[i:i + 6]
        listing = "\n".join(f"{j}. {p.name}" + (f" (category: {p.category})" if p.category else "") for j, p in enumerate(chunk))
        try:
            data = llm.json_call(
                "products.queries", system=llm.cached_system(kb_card or f"Business: {business}"),
                prompt=f"For each product, write ONE realistic question a shopper would ask an AI assistant when choosing this kind of product "
                       f"for a specific need (use_case), and ONE comparing it with alternatives (comparison). Do not include the brand name "
                       f"in use_case. Products:\n{listing}", schema=QUERY_SCHEMA, max_tokens=8000)
        except Exception:
            continue
        for row in data["products"]:
            if 0 <= row["index"] < len(chunk) and row["use_case"].strip() and row["comparison"].strip():
                p = chunk[row["index"]]
                n = len(p.queries)
                p.queries = [*p.queries, {"id": f"p{p.id}.{n + 1}", "kind": "use_case", "text": row["use_case"].strip()},
                             {"id": f"p{p.id}.{n + 2}", "kind": "comparison", "text": row["comparison"].strip()}]
    return len(todo)


def select_queries(prods: list[Product], cap: int) -> list[dict]:
    """Up to `cap` product questions, spread across products first (one each), then a second each, and so on."""
    per = [[{**q, "product_id": p.id} for q in p.queries] for p in prods if p.active]
    out, i = [], 0
    while len(out) < cap and any(per):
        for lst in per:
            if i < len(lst) and len(out) < cap:
                out.append(lst[i])
        i += 1
        if i > 12:
            break
    return out


def _terms(p: dict) -> list[str]:
    name = p["name"].strip()
    terms = {name}
    brand = (p.get("brand") or "").strip()
    if brand and name.lower().startswith(brand.lower() + " "):
        terms.add(name[len(brand):].strip())  # "Acme Road Bike 3000" is often written "Road Bike 3000"
    if p.get("sku"):
        terms.add(p["sku"].strip())
    return [t for t in terms if len(t) >= 3]


def _has(text: str, terms: list[str]) -> bool:
    return any(re.search(rf"(?<!\w){re.escape(t)}(?!\w)", text, re.I) for t in terms)


def metrics(text: str, citations: list[str], p: dict) -> dict:
    """How one answer treated one product: named? linked? and where in the list of suggestions?"""
    terms = _terms(p)
    items = [m.group(1) for line in text.splitlines() for m in [LIST_ITEM.match(line)] if m]
    rank = next((i + 1 for i, it in enumerate(items) if _has(it, terms)), None)
    purl = norm_url(p["url"]) if p.get("url") else ""
    cited = bool(purl) and any(norm_url(c) == purl or norm_url(c).startswith(purl + "/") for c in citations)
    return {"product_mentioned": _has(text, terms), "product_cited": cited, "product_rank": rank, "list_len": len(items)}
