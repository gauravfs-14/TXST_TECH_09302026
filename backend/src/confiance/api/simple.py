"""Endpoints that back the guided web app. They translate plain-language choices (a website address,
a list of questions, things to leave alone) into the brief, constraints and configuration that the
engine underneath needs, so nobody has to write JSON or CSS selectors."""

import io
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select

from .. import audit, brief as briefs, kb, llm, secrets_store
from ..brief import BriefData, Constraints, TargetQuestion
from ..db import session_scope
from ..models import Deployment, Page, Product, Project, Run, SimulationBatch, SimulationResult
from ..sim import stats
from ..sim.runner import load_rows
from ..textutil import domain_of, same_site

router = APIRouter(prefix="/api")
PREP: dict[int, dict] = {}  # project_id -> {"phase": ..., "error": ...}


def _404(x, what="item"):
    if x is None:
        raise HTTPException(404, f"{what} not found")
    return x


# ---- connecting the AI model and web search -------------------------------------------------------------------
@router.get("/setup/status")
def setup_status():
    return secrets_store.status()


@router.get("/setup/config")
def setup_config():
    return secrets_store.public()


class ConfigIn(BaseModel):
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_worker_model: str | None = None  # the fast model for the many small jobs; empty = same as main
    llm_rpm: int | None = None
    llm_max_concurrency: int | None = None
    llm_api_key: str | None = None      # empty string clears it
    search_provider: str | None = None
    search_api_key: str | None = None
    searxng_url: str | None = None


@router.put("/setup/config")
def save_config(body: ConfigIn):
    vals = {k: str(v) for k, v in body.model_dump().items() if v is not None}
    if vals.get("search_provider") not in (None, "duckduckgo", "tavily", "searxng", "brave"):
        raise HTTPException(400, "Unknown search option")
    secrets_store.save(vals)
    audit.record("setup.config_saved", "user", {"fields": sorted(vals)})  # names only, never values
    return secrets_store.public()


class ModelsIn(BaseModel):
    base_url: str
    api_key: str = ""


@router.post("/setup/models")
def find_models(body: ModelsIn):
    """List the models a server offers, using values typed on screen (nothing is saved)."""
    ids, err = secrets_store.list_models(body.base_url.strip(), body.api_key.strip() or None)
    return {"models": ids, "error": err, "suggested": secrets_store.suggest_models(ids)}


@router.post("/setup/test-llm")
def test_llm():
    return secrets_store.test_llm()


@router.post("/setup/test-search")
def test_search():
    return secrets_store.test_search()


# ---- creating a project from just a name and a website -----------------------------------------------------
def _origin(raw: str) -> str:
    raw = raw.strip()
    if not raw or "." not in raw:
        raise HTTPException(400, "Please enter your website address, for example www.yourbusiness.com")
    parts = urlsplit(raw if "//" in raw else f"https://{raw}")
    if not parts.netloc or " " in parts.netloc:
        raise HTTPException(400, "That doesn't look like a website address. Try something like www.yourbusiness.com")
    return f"{parts.scheme}://{parts.netloc}"


class NewProject(BaseModel):
    business_name: str
    website: str


@router.post("/simple/projects")
def new_project(body: NewProject):
    origin = _origin(body.website)
    engines = [{"name": "openai"}]  # the OpenAI-compatible model configured in Settings
    with session_scope() as s:
        p = Project(name=body.business_name.strip(), domain=domain_of(origin), site_url=origin, engines=engines,
                    deploy_config={"type": "export"})
        s.add(p)
        s.flush()
        audit.record("project.created", "user", {"name": p.name, "domain": p.domain}, project_id=p.id)
        return {"id": p.id}


class ProjectPatch(BaseModel):
    business_name: str | None = None
    website: str | None = None
    ai_assistants: list[str] | None = None  # "claude" | "openai" | "gemini"
    deploy_config: dict | None = None


@router.patch("/projects/{pid}")
def patch_project(pid: int, body: ProjectPatch):
    changed_site = False
    with session_scope() as s:
        p = _404(s.get(Project, pid), "project")
        if body.business_name:
            p.name = body.business_name.strip()
        if body.website is not None:
            origin = _origin(body.website)
            if origin != p.site_url:
                changed_site = True
                old = p.site_url
                p.site_url, p.domain = origin, domain_of(origin)
                # Pages and auto-detected products belonged to the old address: set them aside (history is kept).
                for pg in s.scalars(select(Page).where(Page.project_id == pid, Page.kind == "page")):
                    if not same_site(pg.url, p.domain):
                        pg.kind = "archived"
                for pr in s.scalars(select(Product).where(Product.project_id == pid, Product.source == "detected")):
                    s.delete(pr)
                audit.record("project.site_changed", "user", {"from": old, "to": origin}, project_id=pid)
        if body.ai_assistants is not None:
            if not body.ai_assistants:
                raise HTTPException(400, "Please choose at least one AI assistant")
            p.engines = [{"name": n} for n in body.ai_assistants]
        if body.deploy_config is not None:
            p.deploy_config = body.deploy_config
        audit.record("project.updated", "user", body.model_dump(exclude_none=True, exclude={"deploy_config", "website"}), project_id=pid)
    PREP.pop(pid, None) if changed_site else None
    return {"ok": True, "site_changed": changed_site}


# ---- reading the website -----------------------------------------------------------------------------------------
def _starting_plan(pid: int) -> None:
    """Give a new project something to work on straight away. Never lets a plan problem fail the onboarding."""
    try:
        from ..plan import generator as plan_gen
        plan_gen.generate_initial(pid)
    except Exception as e:
        audit.record("plan.initial_failed", "system", {"error": str(e)[:300]}, project_id=pid)


def _prepare(pid: int) -> None:
    """Scan the site (robots, sitemap, llms.txt, pages, products, audit), then learn the business. Runs in the background."""
    from .. import activity
    from ..context import task_scope
    from ..services import scan as scan_mod

    tid = activity.task_id(f"prepare:{pid}")
    try:
        PREP[pid] = {"phase": "finding_pages"}
        with task_scope(tid), session_scope() as s:
            result = scan_mod.scan(s, s.get(Project, pid), on_phase=lambda ph: PREP.__setitem__(pid, {"phase": ph}))
        _starting_plan(pid)
        PREP[pid] = {"phase": "learning"}
        with task_scope(tid), session_scope() as s:
            kb.build(s, s.get(Project, pid), force=True)
        _starting_plan(pid)  # again, now that the business summary can go into the drafts
        PREP[pid] = {"phase": "done", "scan": result}
    except Exception as e:
        msg = str(e)
        if isinstance(e, RuntimeError) and "We could not open your website" in msg:
            pass
        else:
            msg = "We couldn't use your AI model. Please check the connection in Settings, then try again."
            audit.record("prepare.failed", "system", {"error": str(e)[:300]}, project_id=pid)
        PREP[pid] = {"phase": "error", "error": msg[:300]}


@router.post("/projects/{pid}/prepare")
def prepare(pid: int, bg: BackgroundTasks):
    if not secrets_store.status().get("llm"):
        raise HTTPException(409, "Please connect your AI model in Settings first.")
    with session_scope() as s:
        _404(s.get(Project, pid), "project")
    if PREP.get(pid, {}).get("phase") in ("finding_pages", "reading_pages", "auditing", "speed_test", "learning"):
        return PREP[pid]
    PREP[pid] = {"phase": "finding_pages"}
    from .. import activity
    activity.begin_task(f"prepare:{pid}")  # a fresh live view for this scan
    bg.add_task(_prepare, pid)
    return PREP[pid]


@router.get("/projects/{pid}/prepare")
def prepare_status(pid: int):
    with session_scope() as s:
        p = _404(s.get(Project, pid), "project")
        pages = [x.url for x in s.scalars(select(Page).where(Page.project_id == pid, Page.kind != "archived"))]
        st = PREP.get(pid) or {"phase": "done" if p.kb_version else "idle"}
        return {**st, "pages": pages}


class Suggestions(BaseModel):
    questions: list[str]


@router.post("/projects/{pid}/suggest-questions")
def suggest_questions(pid: int):
    from ..services import scan as scan_mod

    with session_scope() as s:
        p = _404(s.get(Project, pid), "project")
        if not p.kb_version:
            raise HTTPException(409, "We need to read your website first.")
        card = kb.card(s, p)
        name = p.name
        rec = scan_mod.latest(s, pid)
        headings = []
        for pg in (rec.data["pages"] if rec else [])[:12]:
            headings.append(f"- {pg.get('title', '')} [{pg.get('type', '')}]" + (": " + "; ".join(pg.get("h2", [])[:4]) if pg.get("h2") else ""))
        prods = [x.name for x in s.scalars(select(Product).where(Product.project_id == pid, Product.active).limit(10))]
    schema = {"type": "object", "properties": {"questions": {"type": "array", "items": {"type": "string"}}}, "required": ["questions"], "additionalProperties": False}
    data = llm.json_call(
        "questions.suggest", system=llm.cached_system(card),
        prompt=f"Write 8 questions that real people might type into an AI assistant (like ChatGPT) where this business could be the right answer. "
               f"Make them a mix, worded the way a normal person would:\n"
               f"- 2 about the business by name (what {name} is, or whether it is good for something specific).\n"
               f"- 4 SPECIFIC questions tied to concrete topics, places, audiences, tools or problems on the site. These are the questions a smaller site can realistically win.\n"
               f"- 2 broader questions about the general subject.\n"
               f"List the by-name questions first. Do not make most of them broad.\n\nWhat the site actually covers:\n" + "\n".join(headings or ["(no page details)"]) +
               (f"\n\nProducts: {', '.join(prods)}. Include one question a shopper might ask about these." if prods else ""),
        schema=schema, max_tokens=8000)
    return {"questions": [q.strip() for q in data["questions"] if q.strip()][:8]}


# ---- the "what should we work on" form -----------------------------------------------------------------------------
class SimpleBrief(BaseModel):
    questions: list[str]
    competitors: list[str] = []      # website addresses
    never_change: list[str] = []     # sentences to keep exactly as they are
    never_say: list[str] = []        # claims we must not make
    editable_pages: list[str] = []   # page addresses we may edit; empty = all


def _path(u: str) -> str:
    return urlsplit(u).path or "/"


@router.put("/projects/{pid}/simple-brief")
def save_simple_brief(pid: int, body: SimpleBrief):
    qs = [q.strip() for q in body.questions if q.strip()]
    if not qs:
        raise HTTPException(400, "Please add at least one question.")
    data = BriefData(
        goals="Be found, cited and described accurately by AI assistants for these questions.",
        target_questions=[TargetQuestion(id=f"q{i + 1}", text=q, priority=1) for i, q in enumerate(qs)],
        competitors=[domain_of(c) for c in body.competitors if c.strip()],
        constraints=Constraints(locked_phrases=[x.strip() for x in body.never_change if x.strip()],
                                forbidden_claims=[x.strip() for x in body.never_say if x.strip()],
                                editable_url_globs=[_path(u) for u in body.editable_pages]))
    with session_scope() as s:
        p = _404(s.get(Project, pid), "project")
        v = briefs.create_version(s, p, data, note="saved from the setup form")
        return {"version": v.version}


class QuestionsIn(BaseModel):
    questions: list[str]


@router.put("/projects/{pid}/questions")
def save_questions(pid: int, body: QuestionsIn):
    """Change only the brand questions; every rule and page choice already saved stays as it is."""
    qs = [q.strip() for q in body.questions if q.strip()]
    if not qs:
        raise HTTPException(400, "Please keep at least one question.")
    with session_scope() as s:
        p = _404(s.get(Project, pid), "project")
        if not p.current_brief_version:
            raise HTTPException(409, "Finish setting up your business first.")
        _, b = briefs.get(s, pid)
        b = b.model_copy(update={"target_questions": [TargetQuestion(id=f"q{i + 1}", text=q, priority=1) for i, q in enumerate(qs)]})
        v = briefs.create_version(s, p, b, note="questions edited")
        return {"version": v.version}


@router.get("/projects/{pid}/simple-brief")
def get_simple_brief(pid: int):
    with session_scope() as s:
        p = _404(s.get(Project, pid), "project")
        if not p.current_brief_version:
            return None
        _, b = briefs.get(s, pid)
        urls = [x.url for x in s.scalars(select(Page).where(Page.project_id == pid, Page.kind != "archived"))]
    globs = b.constraints.editable_url_globs
    return {"questions": [q.text for q in b.target_questions], "competitors": b.competitors,
            "never_change": b.constraints.locked_phrases, "never_say": b.constraints.forbidden_claims,
            "editable_pages": [u for u in urls if not globs or _path(u) in globs]}


# ---- results in plain terms -----------------------------------------------------------------------------------------
def _overall(agg: dict) -> dict:
    o = (agg or {}).get("overall", {})
    return {"mentioned": o.get("mentioned_rate", 0), "cited": o.get("cited_rate", 0), "used": o.get("used_page_rate", 0), "n": o.get("n", 0)}


FUNNEL = (("exposed", "exposed_rate"), ("fetched", "fetched_rate"), ("used", "used_page_rate"), ("mentioned", "mentioned_rate"), ("cited", "cited_rate"),
          ("product_named", "product_mentioned_rate"), ("product_linked", "product_cited_rate"))


def _q_rates(agg: dict | None) -> dict:
    return {k: (agg or {}).get(src, 0) for k, src in FUNNEL} | {"n": (agg or {}).get("n", 0), "visibility": (agg or {}).get("visibility", 0)}


@router.get("/runs/{rid}/summary")
def run_summary(rid: int):
    with session_scope() as s:
        run = _404(s.get(Run, rid), "run")
        sm = run.summary or {}
        batches = {b.arm: b for b in s.scalars(select(SimulationBatch).where(SimulationBatch.run_id == rid))}
        base_b = s.get(SimulationBatch, sm["baseline_batch"]) if sm.get("baseline_batch") else batches.get("baseline")
        cand_b = s.get(SimulationBatch, sm["candidate_batch"]) if sm.get("candidate_batch") else batches.get("candidate")
        base_q = ((base_b.aggregate or {}).get("by_question", {})) if base_b else {}
        cand_q = ((cand_b.aggregate or {}).get("by_question", {})) if cand_b else None
        qlist = sm.get("questions")
        if not qlist:  # rounds from before product tracking
            brief = briefs.get(s, run.project_id, run.brief_version)[1]
            qlist = [{"id": q.id, "text": q.text, "track": "brand"} for q in brief.target_questions]

        def sample(batch, qid: str) -> str:
            if not batch:
                return ""
            r = s.scalars(select(SimulationResult).where(SimulationResult.batch_id == batch.id, SimulationResult.question_id == qid,
                                                         SimulationResult.persona_id.is_(None)).order_by(SimulationResult.id)).first()
            return (r.answer if r else "")[:20000]  # the whole answer: nothing is cut off on screen

        fit = {e["id"]: e for e in (sm.get("research") or {}).get("queries", [])}
        questions = [{"id": q["id"], "text": q["text"], "track": q.get("track", "brand"), "product": q.get("product", ""),
                      "before": _q_rates(base_q.get(q["id"])), "after": _q_rates((cand_q or {}).get(q["id"])), "retested": cand_q is None or q["id"] in cand_q,
                      "before_answer": sample(base_b, q["id"]), "after_answer": sample(cand_b, q["id"]),
                      "search_rank": (fit.get(q["id"]) or {}).get("rank"), "fit": (fit.get(q["id"]) or {}).get("fit"), "fit_reason": (fit.get(q["id"]) or {}).get("fit_reason")}
                     for q in qlist if q["id"] in base_q]
        dep = None
        if sm.get("deployment_id"):
            d = s.get(Deployment, sm["deployment_id"])
            dep = {"id": d.id, "status": d.status, "how": d.deployer, "where": d.external_ref, "details": d.details}
        live_pre, live_post = batches.get("live_pre"), batches.get("live_post")
        tested = {q["id"] for q in questions if q["retested"]}
        before_rows = [r for r in load_rows(s, base_b.id) if r["question_id"] in tested] if base_b else []
        ev = sm.get("evaluation") or {}
        return {"id": run.id, "stage": run.stage, "status": run.status, "error": run.error, "config": sm.get("config"), "plan": sm.get("plan"),
                "before": _overall(stats.aggregate(before_rows)) if (base_b and cand_b) else (_overall(base_b.aggregate) if base_b else None),
                "after": _overall(cand_b.aggregate) if cand_b else None,
                "verdict": ev.get("verdict"), "recommendation": ev.get("recommendation"), "best_loop": ev.get("best_loop"), "stop_reason": ev.get("stop_reason"), "loops": ev.get("loops", []),
                "by_track": ev.get("by_track"), "questions": questions, "deployment": dep, "optimizer_summary": sm.get("optimizer_summary", ""),
                "findability": sm.get("findability"), "findability_summary": sm.get("findability_summary"), "research": {k: (sm.get("research") or {}).get(k) for k in ("summary", "patterns", "competitors")},
                "recommendations": sm.get("recommendations", []), "narrative": sm.get("narrative", ""),
                "live_before": _overall(live_pre.aggregate) if live_pre else None, "live_after": _overall(live_post.aggregate) if live_post else None,
                "measure_after": run.measure_after.isoformat() if run.measure_after else None}


@router.get("/deployments/{did}/download")
def download(did: int):
    with session_scope() as s:
        d = _404(s.get(Deployment, did), "deployment")
        ref = d.external_ref if d.deployer == "export" else None
    if not ref or not Path(ref).is_dir():
        raise HTTPException(404, "There is no download for this change.")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        base = Path(ref)
        for f in sorted(base.rglob("*")):
            if f.is_file():  # include pages/, new-pages/ and site-files/, not just the top level
                z.write(f, f.relative_to(base).as_posix())
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="changes-{did}.zip"'})
