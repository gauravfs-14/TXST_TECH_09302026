"""Endpoints for the full product: site audit, products/SKUs, settings, the optimization loop, the improvement plan,
the report, and the overview. (The guided setup endpoints live in simple.py.)"""

import csv
import io

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, select

from .. import audit, reports, settings as settings_mod
from ..db import session_scope
from ..models import Page, PlanAction, Product, Project, Run, RunLoop, SimulationBatch, SiteAudit
from ..plan import generator as plan_gen
from ..services import scan as scan_mod
from ..sim import products as products_mod

router = APIRouter(prefix="/api")


def _404(x, what="item"):
    if x is None:
        raise HTTPException(404, f"{what} not found")
    return x


# ---- site audit ----------------------------------------------------------------------------------------------------
@router.get("/projects/{pid}/audit")
def get_audit(pid: int):
    with session_scope() as s:
        _404(s.get(Project, pid), "project")
        rec = scan_mod.latest(s, pid)
        hist = [{"id": a.id, "score": a.score, "at": a.created_at.isoformat()} for a in s.scalars(select(SiteAudit).where(SiteAudit.project_id == pid).order_by(SiteAudit.id.desc()).limit(12))]
        if rec is None:
            return {"scanned": False, "history": []}
        d = rec.data
        return {"scanned": True, "id": rec.id, "at": rec.created_at.isoformat(), "score": rec.score, "findings": d["audit"]["findings"], "counts": d["audit"]["counts"],
                "page_types": d["audit"]["page_types"], "schema_coverage": d["audit"]["schema_coverage"], "pages_checked": d["audit"]["pages_checked"], "indexed": d.get("indexed"), "lighthouse": d.get("lighthouse"),
                "discovery": d["discovery"], "pages": d["pages"], "history": list(reversed(hist))}


# ---- products / SKUs -------------------------------------------------------------------------------------------------
class ProductIn(BaseModel):
    name: str
    sku: str = ""
    url: str = ""
    category: str = ""
    brand: str = ""
    price: str = ""


class ProductPatch(BaseModel):
    name: str | None = None
    sku: str | None = None
    url: str | None = None
    category: str | None = None
    brand: str | None = None
    price: str | None = None
    active: bool | None = None
    queries: list[dict] | None = None


def _product_view(p: Product, latest: dict | None) -> dict:
    return {"id": p.id, "name": p.name, "sku": p.sku, "url": p.url, "category": p.category, "brand": p.brand, "price": p.price, "active": p.active, "source": p.source,
            "confidence": (p.attributes or {}).get("confidence"), "queries": p.queries or [], "visibility": (latest or {}).get(str(p.id))}


def _latest_product_visibility(s, pid: int) -> dict:
    """Most recent measured numbers per product: named / linked rates, and real-search rank if known."""
    run = s.scalars(select(Run).where(Run.project_id == pid, Run.stage.in_(["awaiting_approval", "deploy", "awaiting_live", "awaiting_measure", "measure", "done"]), Run.status != "cancelled").order_by(Run.id.desc())).first()
    if not run:
        return {}
    sm = run.summary or {}
    base = s.get(SimulationBatch, sm.get("baseline_batch")) if sm.get("baseline_batch") else None
    cand = s.get(SimulationBatch, sm.get("candidate_batch")) if sm.get("candidate_batch") else None
    ranks = {}
    for e in (sm.get("research") or {}).get("queries", []):
        pid_ = products_mod.product_id_of(e["id"])
        if pid_ is not None:
            ranks.setdefault(str(pid_), []).append(e.get("product_rank") or e.get("rank"))
    out = {}
    for k, v in ((base.aggregate if base else {}) or {}).get("by_product", {}).items():
        after = (((cand.aggregate if cand else {}) or {}).get("by_product", {}) or {}).get(k)
        rk = [r for r in ranks.get(k, []) if r]
        out[k] = {"named": v.get("product_mentioned_rate"), "linked": v.get("product_cited_rate"), "named_after": (after or {}).get("product_mentioned_rate"),
                  "linked_after": (after or {}).get("product_cited_rate"), "search_rank": min(rk) if rk else None, "round": run.iteration, "n": v.get("n")}
    return out


@router.get("/projects/{pid}/products")
def list_products(pid: int):
    with session_scope() as s:
        _404(s.get(Project, pid), "project")
        latest = _latest_product_visibility(s, pid)
        return [_product_view(p, latest) for p in s.scalars(select(Product).where(Product.project_id == pid).order_by(Product.active.desc(), Product.id))]


@router.post("/projects/{pid}/products")
def add_product(pid: int, body: ProductIn):
    if not body.name.strip():
        raise HTTPException(400, "Please give the product a name.")
    with session_scope() as s:
        _404(s.get(Project, pid), "project")
        p = Product(project_id=pid, source="manual", **{k: v.strip() for k, v in body.model_dump().items()})
        s.add(p)
        s.flush()
        audit.record("product.added", "user", {"name": p.name, "sku": p.sku}, project_id=pid)
        return _product_view(p, None)


class Suggested(BaseModel):
    items: list[dict]


@router.post("/projects/{pid}/products/suggest")
def suggest_products(pid: int):
    """Propose products or services the business could track, from what its own site says. Nothing is saved."""
    from .. import kb, llm

    with session_scope() as s:
        p = _404(s.get(Project, pid), "project")
        if not p.kb_version:
            raise HTTPException(409, "We need to read your website first.")
        card, name = kb.card(s, p), p.name
        rec = scan_mod.latest(s, pid)
        heads = [f"- {pg.get('title', '')}" + (": " + "; ".join(pg.get("h2", [])[:4]) if pg.get("h2") else "") for pg in (rec.data["pages"] if rec else [])[:15]]
        have = {x.name.lower() for x in s.scalars(select(Product).where(Product.project_id == pid))}
    schema = {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {
        "name": {"type": "string"}, "category": {"type": "string"}}, "required": ["name", "category"], "additionalProperties": False}}}, "required": ["items"], "additionalProperties": False}
    try:
        data = llm.json_call("products.suggest", system=llm.cached_system(card),
                             prompt=f"List up to 8 distinct products, plans, courses, tools or services that {name} sells or offers, things a visitor can buy, book, sign up for or download. "
                                    f"Use the names the site itself uses. Do NOT list topics, categories, article subjects or general themes. If {name} is mainly a blog, magazine or "
                                    f"tutorial site and offers nothing like that, return an empty list. Never invent things the site doesn't offer. Give each a short category.\n\nPages:\n" + "\n".join(heads or ["(none)"]),
                             schema=schema, max_tokens=4000)
    except Exception:
        raise HTTPException(502, "We couldn't come up with suggestions just now. You can add products yourself.")
    out = [{"name": i["name"].strip()[:300], "category": i["category"].strip()[:200]} for i in data["items"] if i["name"].strip() and i["name"].strip().lower() not in have]
    return {"items": out[:8]}


@router.post("/projects/{pid}/products/add-many")
def add_products(pid: int, body: Suggested):
    added = 0
    with session_scope() as s:
        _404(s.get(Project, pid), "project")
        have = {x.name.lower() for x in s.scalars(select(Product).where(Product.project_id == pid))}
        for i in body.items:
            nm = str(i.get("name", "")).strip()
            if nm and nm.lower() not in have:
                s.add(Product(project_id=pid, source="manual", name=nm[:300], category=str(i.get("category", "")).strip()[:200]))
                have.add(nm.lower())
                added += 1
    audit.record("products.added_many", "user", {"added": added}, project_id=pid)
    return {"added": added}


@router.patch("/products/{prid}")
def patch_product(prid: int, body: ProductPatch):
    with session_scope() as s:
        p = _404(s.get(Product, prid), "product")
        for k, v in body.model_dump(exclude_none=True).items():
            setattr(p, k, v.strip() if isinstance(v, str) else v)
        if body.name or body.category:
            p.queries = []  # the questions were written for the old name/category; regenerate on the next round
        audit.record("product.updated", "user", {"id": prid, **{k: v for k, v in body.model_dump(exclude_none=True).items() if k != "queries"}}, project_id=p.project_id)
        return _product_view(p, None)


@router.delete("/products/{prid}")
def delete_product(prid: int):
    with session_scope() as s:
        p = _404(s.get(Product, prid), "product")
        pid = p.project_id
        s.delete(p)
    audit.record("product.deleted", "user", {"id": prid}, project_id=pid)
    return {"ok": True}


class CsvIn(BaseModel):
    csv: str


@router.post("/projects/{pid}/products/import")
def import_products(pid: int, body: CsvIn):
    """CSV with a header row. Recognised columns: name, sku, url, category, brand, price (any order, extra columns ignored)."""
    rows = list(csv.DictReader(io.StringIO(body.csv.strip())))
    if not rows or "name" not in {k.strip().lower() for k in rows[0]}:
        raise HTTPException(400, "The first line must be a header that includes a 'name' column, for example: name,sku,url,category,price")
    added = skipped = 0
    with session_scope() as s:
        _404(s.get(Project, pid), "project")
        have = {(p.sku or "").lower() or p.name.lower() for p in s.scalars(select(Product).where(Product.project_id == pid))}
        for r in rows[:500]:
            r = {k.strip().lower(): (v or "").strip() for k, v in r.items() if k}
            if not r.get("name") or ((r.get("sku") or "").lower() or r["name"].lower()) in have:
                skipped += 1
                continue
            s.add(Product(project_id=pid, name=r["name"][:300], sku=r.get("sku", "")[:100], url=r.get("url", "")[:1000], category=r.get("category", "")[:200], brand=r.get("brand", "")[:200], price=r.get("price", "")[:50], source="csv"))
            have.add((r.get("sku") or "").lower() or r["name"].lower())
            added += 1
    audit.record("products.imported", "user", {"added": added, "skipped": skipped}, project_id=pid)
    return {"added": added, "skipped": skipped}


@router.post("/projects/{pid}/products/queries")
def make_product_queries(pid: int, force: bool = False):
    from .. import kb

    with session_scope() as s:
        p = _404(s.get(Project, pid), "project")
        n = products_mod.generate_queries(s, pid, p.name, kb.card(s, p), only_missing=not force)
    return {"products_updated": n}


# ---- settings ---------------------------------------------------------------------------------------------------------
@router.get("/projects/{pid}/settings")
def get_settings(pid: int):
    with session_scope() as s:
        p = _404(s.get(Project, pid), "project")
        return {"settings": settings_mod.for_project(p), "defaults": settings_mod.DEFAULTS, "limits": settings_mod.LIMITS}


@router.put("/projects/{pid}/settings")
def put_settings(pid: int, body: dict):
    with session_scope() as s:
        p = _404(s.get(Project, pid), "project")
        p.settings = settings_mod.clamp({**(p.settings or {}), **body})
        audit.record("settings.updated", "user", {"changed": sorted(body)}, project_id=pid)
        return {"settings": settings_mod.for_project(p)}


# ---- the loop ---------------------------------------------------------------------------------------------------------
@router.get("/runs/{rid}/loops")
def run_loops(rid: int):
    with session_scope() as s:
        run = _404(s.get(Run, rid), "round")
        ev = (run.summary or {}).get("evaluation") or {}
        return {"config": (run.summary or {}).get("config"), "best_loop": ev.get("best_loop"), "stop_reason": ev.get("stop_reason"),
                "loops": [{"n": l.n, "status": l.status, "decision": l.decision, "proposals": len(l.proposal_ids or []), "delta": (l.delta or {}).get("overall"), "by_track": (l.delta or {}).get("by_track"),
                           "verdict": (l.delta or {}).get("verdict"), "tested": (l.metrics or {}).get("tested_questions"), "funnel_base": (l.metrics or {}).get("funnel_base"),
                           "funnel_now": (l.metrics or {}).get("funnel_now"), "not_improved": ((l.metrics or {}).get("feedback") or {}).get("not_improved"), "notes": l.notes}
                          for l in s.scalars(select(RunLoop).where(RunLoop.run_id == rid).order_by(RunLoop.n))]}


# ---- plan ----------------------------------------------------------------------------------------------------------------
def _action_view(a: PlanAction) -> dict:
    return {"id": a.id, "seq": a.seq, "category": a.category, "priority": a.priority, "title": a.title, "why": a.why, "steps": a.steps or [], "draft": a.draft or {}, "targets": a.targets or [],
            "impact": a.impact, "effort": a.effort, "owner": a.owner, "timeframe": a.timeframe, "verify": a.verify, "evidence": a.evidence or [], "source": a.source, "status": a.status, "run_id": a.run_id}


@router.get("/runs/{rid}/plan")
def run_plan(rid: int):
    with session_scope() as s:
        _404(s.get(Run, rid), "round")
        return [_action_view(a) for a in s.scalars(select(PlanAction).where(PlanAction.run_id == rid).order_by(PlanAction.seq))]


@router.get("/projects/{pid}/plan")
def project_plan(pid: int):
    """The plan from the most recent round that has one."""
    plan_gen.ensure_initial(pid)
    with session_scope() as s:
        _404(s.get(Project, pid), "project")
        rid = plan_gen.current_run_id(s, pid)
        run = s.get(Run, rid) if rid else None
        return {"run_id": rid, "round": run.iteration if run else None, "initial": rid is None, "actions": [_action_view(a) for a in plan_gen.current(s, pid)]}


class StatusIn(BaseModel):
    status: str


@router.patch("/plan/{aid}")
def set_action_status(aid: int, body: StatusIn):
    if body.status not in ("todo", "doing", "done", "dismissed"):
        raise HTTPException(400, "status must be todo, doing, done or dismissed")
    with session_scope() as s:
        a = _404(s.get(PlanAction, aid), "action")
        a.status = body.status
        pid = a.project_id
    audit.record("plan.status", "user", {"action_id": aid, "status": body.status}, project_id=pid)
    return {"ok": True}


# ---- report -------------------------------------------------------------------------------------------------------------------
@router.get("/runs/{rid}/report")
def report_json(rid: int):
    try:
        return reports.build(rid)
    except LookupError:
        raise HTTPException(404, "round not found")


@router.get("/runs/{rid}/report.html")
def report_html(rid: int, download: bool = False):
    try:
        body = reports.render_html(reports.build(rid))
    except LookupError:
        raise HTTPException(404, "round not found")
    return Response(body, media_type="text/html", headers={"Content-Disposition": f'attachment; filename="report-round-{rid}.html"'} if download else {})


@router.get("/runs/{rid}/report.md")
def report_md(rid: int):
    try:
        body = reports.render_markdown(reports.build(rid))
    except LookupError:
        raise HTTPException(404, "round not found")
    return Response(body, media_type="text/markdown", headers={"Content-Disposition": f'attachment; filename="report-round-{rid}.md"'})


# ---- overview -----------------------------------------------------------------------------------------------------------------
@router.get("/projects/{pid}/overview")
def overview(pid: int):
    """Everything the dashboard needs in one call: health, findability, visibility (brand and products), trend, plan, activity."""
    plan_gen.ensure_initial(pid)
    with session_scope() as s:
        p = _404(s.get(Project, pid), "project")
        rec = scan_mod.latest(s, pid)
        runs = list(s.scalars(select(Run).where(Run.project_id == pid).order_by(Run.id)))
        finished = [r for r in runs if r.stage in ("awaiting_approval", "deploy", "awaiting_live", "awaiting_measure", "measure", "done") and r.status != "cancelled" and (r.summary or {}).get("baseline_batch")]
        history = []
        for r in finished:
            sm = r.summary
            base = s.get(SimulationBatch, sm["baseline_batch"])
            agg = (base.aggregate if base else {}) or {}
            bt = agg.get("by_track", {})
            ev = sm.get("evaluation") or {}
            history.append({"run_id": r.id, "round": r.iteration, "at": r.created_at.isoformat(), "brand": bt.get("brand", {}).get("mentioned_rate"), "brand_used": bt.get("brand", {}).get("used_page_rate"),
                            "product": bt.get("product", {}).get("product_mentioned_rate"), "found": (sm.get("findability_summary") or {}).get("questions_found"), "checked": (sm.get("findability_summary") or {}).get("questions_checked"),
                            "verdict": (ev.get("verdict") or {}).get("label"), "loops": len(ev.get("loops", [])), "real_world": (sm.get("real_world") or {}).get("delta")})
        last = finished[-1] if finished else None
        latest = runs[-1] if runs else None
        plan = plan_gen.current(s, pid)
        counts = {pr: sum(a.priority == pr and a.status in ("todo", "doing") for a in plan) for pr in ("P0", "P1", "P2", "P3")}
        prods = list(s.scalars(select(Product).where(Product.project_id == pid, Product.active)))
        research = ((last.summary or {}).get("research") or {}) if last else {}
        ev = ((last.summary or {}).get("evaluation") or {}) if last else {}
        cand_id, base_id = ((last.summary or {}).get("candidate_batch"), (last.summary or {}).get("baseline_batch")) if last else (None, None)
        return {"business": p.name, "domain": p.domain, "site_score": rec.score if rec else None, "site_scanned": rec.created_at.isoformat() if rec else None,
                "site_findings": (rec.data["audit"]["counts"] if rec else {}), "lighthouse": ((rec.data.get("lighthouse") or {}) if rec else None), "indexed": (rec.data.get("indexed") if rec else None),
                "findability": research.get("summary"), "brand_found": (research.get("brand") or {}).get("status"), "history": history,
                "latest_round": {"id": latest.id, "round": latest.iteration, "stage": latest.stage, "status": latest.status} if latest else None,
                "last_finished_round": {"id": last.id, "round": last.iteration, "verdict": ev.get("verdict"), "best_loop": ev.get("best_loop")} if last else None,
                "plan_open": counts, "plan_total": len(plan), "plan_done": sum(a.status == "done" for a in plan), "products": {"active": len(prods), "total": s.scalar(select(func.count()).select_from(Product).where(Product.project_id == pid))},
                "top_actions": [_action_view(a) for a in sorted((a for a in plan if a.status in ("todo", "doing")), key=lambda a: a.seq)[:4]],
                "pages": s.scalar(select(func.count()).select_from(Page).where(Page.project_id == pid, Page.kind == "page", Page.is_new.is_(False))),
                "candidate_batch": cand_id, "baseline_batch": base_id}
