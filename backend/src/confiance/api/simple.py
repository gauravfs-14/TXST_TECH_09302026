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
from ..models import Deployment, Page, Project, Run, SimulationBatch, SimulationResult
from ..sim import stats
from ..sim.runner import load_rows
from ..textutil import domain_of

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
class NewProject(BaseModel):
    business_name: str
    website: str


@router.post("/simple/projects")
def new_project(body: NewProject):
    raw = body.website.strip()
    if not raw or "." not in raw:
        raise HTTPException(400, "Please enter your website address, for example www.yourbusiness.com")
    url = raw if "//" in raw else f"https://{raw}"
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
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
    ai_assistants: list[str] | None = None  # "claude" | "openai" | "gemini"
    deploy_config: dict | None = None


@router.patch("/projects/{pid}")
def patch_project(pid: int, body: ProjectPatch):
    with session_scope() as s:
        p = _404(s.get(Project, pid), "project")
        if body.business_name:
            p.name = body.business_name.strip()
        if body.ai_assistants is not None:
            if not body.ai_assistants:
                raise HTTPException(400, "Please choose at least one AI assistant")
            p.engines = [{"name": n} for n in body.ai_assistants]
        if body.deploy_config is not None:
            p.deploy_config = body.deploy_config
        audit.record("project.updated", "user", body.model_dump(exclude_none=True, exclude={"deploy_config"}), project_id=pid)
    return {"ok": True}


# ---- reading the website -----------------------------------------------------------------------------------------
def _prepare(pid: int) -> None:
    try:
        PREP[pid] = {"phase": "finding_pages"}
        with session_scope() as s:
            p = s.get(Project, pid)
            site = p.site_url or p.domain
        urls = kb.discover(site, limit=8)
        PREP[pid] = {"phase": "reading_pages"}
        with session_scope() as s:
            p = s.get(Project, pid)
            pages = kb.crawl(s, p, urls)
            if not pages:
                raise RuntimeError("We could not open your website. Please check the address and try again.")
        PREP[pid] = {"phase": "learning"}
        with session_scope() as s:
            kb.build(s, s.get(Project, pid), force=True)
        PREP[pid] = {"phase": "done"}
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
    if PREP.get(pid, {}).get("phase") in ("finding_pages", "reading_pages", "learning"):
        return PREP[pid]
    PREP[pid] = {"phase": "finding_pages"}
    bg.add_task(_prepare, pid)
    return PREP[pid]


@router.get("/projects/{pid}/prepare")
def prepare_status(pid: int):
    with session_scope() as s:
        p = _404(s.get(Project, pid), "project")
        pages = [x.url for x in s.scalars(select(Page).where(Page.project_id == pid))]
        st = PREP.get(pid) or {"phase": "done" if p.kb_version else "idle"}
        return {**st, "pages": pages}


class Suggestions(BaseModel):
    questions: list[str]


@router.post("/projects/{pid}/suggest-questions")
def suggest_questions(pid: int):
    with session_scope() as s:
        p = _404(s.get(Project, pid), "project")
        if not p.kb_version:
            raise HTTPException(409, "We need to read your website first.")
        card = kb.card(s, p)
        name = p.name
    schema = {"type": "object", "properties": {"questions": {"type": "array", "items": {"type": "string"}}},
              "required": ["questions"], "additionalProperties": False}
    data = llm.json_call(
        "questions.suggest", system=llm.cached_system(card),
        prompt=f"Write 8 questions that real people might type into an AI assistant (like ChatGPT) where this business could "
               f"be the right answer. Make them a mix, and write them the way a normal person would:\n"
               f"- 2 about the business by name (for example what {name} is, or whether it is good for something specific).\n"
               f"- 4 SPECIFIC questions tied to concrete things on the website: particular topics, places, audiences, languages, "
               f"tools or problems it covers. These are the questions a smaller site can realistically win.\n"
               f"- 2 broader questions about the general subject.\n"
               f"Do not make most of them broad: broad questions are dominated by huge sites. List the by-name questions first.",
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


@router.get("/projects/{pid}/simple-brief")
def get_simple_brief(pid: int):
    with session_scope() as s:
        p = _404(s.get(Project, pid), "project")
        if not p.current_brief_version:
            return None
        _, b = briefs.get(s, pid)
        urls = [x.url for x in s.scalars(select(Page).where(Page.project_id == pid))]
    globs = b.constraints.editable_url_globs
    return {"questions": [q.text for q in b.target_questions], "competitors": b.competitors,
            "never_change": b.constraints.locked_phrases, "never_say": b.constraints.forbidden_claims,
            "editable_pages": [u for u in urls if not globs or _path(u) in globs]}


# ---- results in plain terms -----------------------------------------------------------------------------------------
def _overall(agg: dict) -> dict:
    o = (agg or {}).get("overall", {})
    return {"mentioned": o.get("mentioned_rate", 0), "cited": o.get("cited_rate", 0), "used": o.get("used_page_rate", 0), "n": o.get("n", 0)}


@router.get("/runs/{rid}/summary")
def run_summary(rid: int):
    with session_scope() as s:
        run = _404(s.get(Run, rid), "run")
        batches = {b.arm: b for b in s.scalars(select(SimulationBatch).where(SimulationBatch.run_id == rid))}
        brief = briefs.get(s, run.project_id, run.brief_version)[1]
        texts = {f"q{i}": q.text for i, q in enumerate(brief.target_questions, 1)}
        texts.update({q.id: q.text for q in brief.target_questions})

        def sample(arm: str, qid: str) -> str:
            b = batches.get(arm)
            if not b:
                return ""
            r = s.scalars(select(SimulationResult).where(SimulationResult.batch_id == b.id, SimulationResult.question_id == qid,
                                                         SimulationResult.persona_id.is_(None)).order_by(SimulationResult.id)).first()
            return (r.answer if r else "")[:900]

        def rate(arm: str, qid: str) -> dict:
            b = batches.get(arm)
            q = ((b.aggregate or {}).get("by_question", {}).get(qid) if b else None) or {}
            return {"mentioned": q.get("mentioned_rate", 0), "cited": q.get("cited_rate", 0)}

        cand_q = set(((batches["candidate"].aggregate or {}).get("by_question", {}))) if "candidate" in batches else None
        questions = [{"id": qid, "text": t, "before": rate("baseline", qid), "after": rate("candidate", qid),
                      "retested": cand_q is None or qid in cand_q,
                      "before_answer": sample("baseline", qid), "after_answer": sample("candidate", qid)}
                     for qid, t in texts.items() if qid in ((batches.get("baseline").aggregate or {}).get("by_question", {})
                                                            if batches.get("baseline") else {})]
        dep = None
        if run.summary.get("deployment_id"):
            d = s.get(Deployment, run.summary["deployment_id"])
            dep = {"id": d.id, "status": d.status, "how": d.deployer, "where": d.external_ref, "details": d.details}
        out = {"id": run.id, "stage": run.stage, "status": run.status, "error": run.error,
               # "before" covers the same questions that were re-asked, so before and after compare like with like
               "before": (_overall(stats.aggregate([r for r in load_rows(s, batches["baseline"].id) if cand_q is None or r["question_id"] in cand_q]))
                          if "baseline" in batches else None),
               "after": _overall(batches["candidate"].aggregate) if "candidate" in batches else None,
               "recommendation": (run.summary.get("evaluation") or {}).get("recommendation"),
               "questions": questions, "deployment": dep, "optimizer_summary": run.summary.get("optimizer_summary", ""),
               "findability": run.summary.get("findability"), "findability_summary": run.summary.get("findability_summary"),
               "recommendations": run.summary.get("recommendations", []),
               "live_before": _overall(batches["live_pre"].aggregate) if "live_pre" in batches else None,
               "live_after": _overall(batches["live_post"].aggregate) if "live_post" in batches else None,
               "measure_after": run.measure_after.isoformat() if run.measure_after else None}
        return out


@router.get("/deployments/{did}/download")
def download(did: int):
    with session_scope() as s:
        d = _404(s.get(Deployment, did), "deployment")
        ref = d.external_ref if d.deployer == "export" else None
    if not ref or not Path(ref).is_dir():
        raise HTTPException(404, "There is no download for this change.")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(Path(ref).iterdir()):
            z.write(f, f.name)
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="changes-{did}.zip"'})
