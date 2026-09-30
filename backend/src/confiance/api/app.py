from contextlib import asynccontextmanager
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import func, select

from .. import audit, brief as briefs, kb, snapshots, usage
from ..config import get_settings
from ..db import init_db, session_scope
from ..deploy import service as deploy_service
from ..drift import monitor
from ..engines import available_engines
from ..models import (Alert, AuditEvent, ChangeProposal, Deployment, DriftCheck, Page, PageVersion, Persona, Project,
                      Run, SimulationBatch)
from ..pipeline import orchestrator
from ..scheduler import build as build_scheduler
from .. import secrets_store
from .simple import router as simple_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    secrets_store.apply()
    sched = None
    if get_settings().enable_scheduler:
        sched = build_scheduler()
        sched.start()
    yield
    if sched:
        sched.shutdown(wait=False)


app = FastAPI(title="CONFIANCE", version="0.1.0", lifespan=lifespan)
app.include_router(simple_router)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])


def _404(x, what):
    if x is None:
        raise HTTPException(404, f"{what} not found")
    return x


# ---- projects / onboarding --------------------------------------------------------------------------
class ProjectIn(BaseModel):
    name: str
    domain: str
    brand_aliases: list[str] = []
    engines: list[dict[str, Any]] = [{"name": "claude"}, {"name": "openai"}, {"name": "gemini"}]
    deploy_config: dict[str, Any] = {"type": "export"}
    brief: briefs.BriefData | None = None


def _project_out(p: Project) -> dict:
    return {"id": p.id, "name": p.name, "domain": p.domain, "site_url": p.site_url, "model": get_settings().llm_model, "brand_aliases": p.brand_aliases, "engines": p.engines,
            "deploy_config": {k: v for k, v in p.deploy_config.items() if "password" not in k and not k.startswith("_")},
            "brief_version": p.current_brief_version, "kb_version": p.kb_version}


@app.get("/api/engines")
def engines():
    return available_engines()


@app.post("/api/projects")
def create_project(body: ProjectIn):
    bad = [e["name"] for e in body.engines if e["name"] not in available_engines()]
    if bad:
        raise HTTPException(400, f"unknown engines {bad}; available {available_engines()}")
    with session_scope() as s:
        p = Project(name=body.name, domain=body.domain, brand_aliases=body.brand_aliases, engines=body.engines,
                    deploy_config=body.deploy_config)
        s.add(p)
        s.flush()
        audit.record("project.created", "user", {"name": p.name, "domain": p.domain}, project_id=p.id)
        if body.brief:
            briefs.create_version(s, p, body.brief, note="initial brief")
        return _project_out(p)


@app.get("/api/projects")
def list_projects():
    with session_scope() as s:
        return [_project_out(p) for p in s.scalars(select(Project))]


@app.get("/api/projects/{pid}")
def get_project(pid: int):
    with session_scope() as s:
        return _project_out(_404(s.get(Project, pid), "project"))


class BriefIn(BaseModel):
    data: briefs.BriefData
    note: str = ""


@app.post("/api/projects/{pid}/briefs")
def new_brief(pid: int, body: BriefIn):
    with session_scope() as s:
        b = briefs.create_version(s, _404(s.get(Project, pid), "project"), body.data, note=body.note)
        return {"version": b.version}


@app.get("/api/projects/{pid}/briefs/{version}")
def get_brief(pid: int, version: int):
    with session_scope() as s:
        v, data = briefs.get(s, pid, version)
        return {"version": v, "data": data.model_dump()}


@app.get("/api/projects/{pid}/briefs")
def list_briefs(pid: int):
    from ..models import Brief
    with session_scope() as s:
        return [{"version": b.version, "note": b.note, "created_by": b.created_by, "created_at": b.created_at}
                for b in s.scalars(select(Brief).where(Brief.project_id == pid).order_by(Brief.version.desc()))]


class CrawlIn(BaseModel):
    urls: list[str] = []
    html: dict[str, str] = {}  # url -> html, for sites we can't crawl
    source_paths: dict[str, str] = {}


@app.post("/api/projects/{pid}/pages")
def add_pages(pid: int, body: CrawlIn):
    with session_scope() as s:
        p = _404(s.get(Project, pid), "project")
        pages = []
        if body.urls:
            pages += kb.crawl(s, p, body.urls)
        if body.html:
            pages += kb.import_pages(s, p, list(body.html.items()), source="crawl", source_paths=body.source_paths)
        for page in pages:
            if body.source_paths.get(page.url):
                page.source_path = body.source_paths[page.url]
        return [{"id": x.id, "url": x.url} for x in pages]


@app.get("/api/projects/{pid}/pages")
def list_pages(pid: int):
    with session_scope() as s:
        return [{"id": x.id, "url": x.url, "source_path": x.source_path, "live_version_id": x.live_version_id}
                for x in s.scalars(select(Page).where(Page.project_id == pid))]


@app.get("/api/pages/{page_id}/versions")
def page_versions(page_id: int):
    with session_scope() as s:
        return [{"id": v.id, "version_no": v.version_no, "source": v.source, "note": v.note, "parent_id": v.parent_id,
                 "blob_hash": v.blob_hash, "created_at": v.created_at}
                for v in s.scalars(select(PageVersion).where(PageVersion.page_id == page_id).order_by(PageVersion.id.desc()))]


@app.get("/api/versions/{vid}")
def version_content(vid: int):
    with session_scope() as s:
        return {"id": vid, "html": snapshots.version_content(s, vid)}


class FactIn(BaseModel):
    fact: str


@app.post("/api/projects/{pid}/kb/facts")
def add_fact(pid: int, body: FactIn):
    with session_scope() as s:
        kb.add_fact(s, _404(s.get(Project, pid), "project"), body.fact)
    return {"ok": True}


@app.post("/api/projects/{pid}/kb/build")
def build_kb(pid: int, force: bool = False):
    with session_scope() as s:
        return {"kb_version": kb.build(s, _404(s.get(Project, pid), "project"), force=force)}


@app.get("/api/projects/{pid}/kb")
def get_kb(pid: int):
    with session_scope() as s:
        return {"card": kb.card(s, _404(s.get(Project, pid), "project"))}


@app.get("/api/projects/{pid}/personas")
def personas(pid: int):
    with session_scope() as s:
        return [{"id": p.id, "name": p.name, "profile": p.profile, "active": p.active}
                for p in s.scalars(select(Persona).where(Persona.project_id == pid))]


# ---- runs --------------------------------------------------------------------------------------------
def _advance_bg(run_id: int) -> None:
    try:
        orchestrator.advance(run_id)
    except Exception:
        pass  # recorded on the run and audit log


@app.post("/api/projects/{pid}/runs")
def start_run(pid: int, bg: BackgroundTasks):
    try:
        rid = orchestrator.start_run(pid)
    except orchestrator.PipelineError as e:
        raise HTTPException(409, str(e))
    bg.add_task(_advance_bg, rid)
    return {"run_id": rid}


@app.post("/api/runs/{rid}/advance")
def advance_run(rid: int, bg: BackgroundTasks):
    bg.add_task(_advance_bg, rid)
    return {"accepted": True}


@app.get("/api/projects/{pid}/runs")
def list_runs(pid: int):
    with session_scope() as s:
        ids = [r.id for r in s.scalars(select(Run).where(Run.project_id == pid).order_by(Run.id.desc()))]
    return [orchestrator.get_status(i) for i in ids]


@app.get("/api/runs/{rid}")
def get_run(rid: int):
    with session_scope():
        pass
    return orchestrator.get_status(rid)


@app.get("/api/runs/{rid}/proposals")
def run_proposals(rid: int):
    with session_scope() as s:
        out = []
        for cp in s.scalars(select(ChangeProposal).where(ChangeProposal.run_id == rid).order_by(ChangeProposal.id)):
            page = s.get(Page, cp.page_id)
            out.append({"id": cp.id, "page_id": cp.page_id, "url": page.url, "status": cp.status, "ops": cp.ops,
                        "rationale": cp.rationale, "target_questions": cp.target_questions,
                        "guard_report": cp.guard_report, "base_version_id": cp.base_version_id,
                        "candidate_version_id": cp.candidate_version_id})
        return out


class DecideIn(BaseModel):
    proposal_ids: list[int]
    approve: bool


@app.post("/api/runs/{rid}/decide")
def decide(rid: int, body: DecideIn, bg: BackgroundTasks):
    try:
        with session_scope() as s:
            for pid in body.proposal_ids:
                cp = _404(s.get(ChangeProposal, pid), f"proposal {pid}")
                if cp.run_id != rid or cp.status != "candidate":
                    raise orchestrator.PipelineError(f"proposal {pid} is not a pending candidate of run {rid}")
        # apply status changes now, advance in background
        with session_scope() as s:
            for pid in body.proposal_ids:
                s.get(ChangeProposal, pid).status = "approved" if body.approve else "rejected"
            project_id = s.get(Run, rid).project_id
        audit.record("proposal.approved" if body.approve else "proposal.rejected", "user",
                     {"proposal_ids": body.proposal_ids}, project_id=project_id, run_id=rid)
    except orchestrator.PipelineError as e:
        raise HTTPException(409, str(e))
    bg.add_task(_advance_bg, rid)
    return {"ok": True}


@app.get("/api/runs/{rid}/simulations")
def run_sims(rid: int):
    with session_scope() as s:
        return [{"id": b.id, "arm": b.arm, "mode": b.mode, "aggregate": b.aggregate}
                for b in s.scalars(select(SimulationBatch).where(SimulationBatch.run_id == rid))]


# ---- deployments ------------------------------------------------------------------------------------
@app.get("/api/projects/{pid}/deployments")
def deployments(pid: int):
    with session_scope() as s:
        return [{"id": d.id, "run_id": d.run_id, "kind": d.kind, "deployer": d.deployer, "status": d.status,
                 "external_ref": d.external_ref, "versions": d.versions, "details": d.details, "created_at": d.created_at}
                for d in s.scalars(select(Deployment).where(Deployment.project_id == pid).order_by(Deployment.id.desc()))]


@app.post("/api/deployments/{did}/confirm-live")
def confirm_live(did: int, bg: BackgroundTasks):
    try:
        deploy_service.confirm_live(did)
    except deploy_service.DeployError as e:
        raise HTTPException(409, str(e))
    with session_scope() as s:
        run_id = s.get(Deployment, did).run_id
    if run_id:
        bg.add_task(_advance_bg, run_id)
    return {"ok": True}


@app.post("/api/deployments/{did}/rollback")
def rollback(did: int):
    try:
        return {"rollback_id": deploy_service.rollback(did)}
    except deploy_service.DeployError as e:
        raise HTTPException(409, str(e))


# ---- audit / cost / drift / alerts ----------------------------------------------------------------------
@app.get("/api/audit")
def audit_log(project_id: int | None = None, run_id: int | None = None, limit: int = 200, before_id: int | None = None):
    with session_scope() as s:
        q = select(AuditEvent).order_by(AuditEvent.id.desc()).limit(min(limit, 1000))
        if project_id is not None:
            q = q.where(AuditEvent.project_id == project_id)
        if run_id is not None:
            q = q.where(AuditEvent.run_id == run_id)
        if before_id:
            q = q.where(AuditEvent.id < before_id)
        return [{"id": e.id, "ts": e.ts, "actor": e.actor, "action": e.action, "payload": e.payload,
                 "project_id": e.project_id, "run_id": e.run_id, "hash": e.hash} for e in s.scalars(q)]


@app.get("/api/audit/verify")
def audit_verify():
    return audit.verify_chain()


@app.get("/api/usage")
def usage_summary(project_id: int | None = None, run_id: int | None = None):
    rows = usage.summary(project_id, run_id)
    return {"total_usd": round(sum(r["cost_usd"] for r in rows), 4), "rows": rows}


@app.get("/api/drift")
def drift_status():
    with session_scope() as s:
        latest = s.execute(select(func.max(DriftCheck.id)).group_by(DriftCheck.engine, DriftCheck.model)).scalars().all()
        return [{"id": c.id, "engine": c.engine, "model": c.model, "status": c.status, "findings": c.findings,
                 "created_at": c.created_at, "observed": c.observed}
                for c in s.scalars(select(DriftCheck).where(DriftCheck.id.in_(latest)))]


class DriftRun(BaseModel):
    project_id: int | None = None


@app.post("/api/drift/check")
def drift_check_now(body: DriftRun, bg: BackgroundTasks):
    from ..scheduler import drift_job
    bg.add_task(drift_job)
    return {"accepted": True}


class Accept(BaseModel):
    engine: str
    model: str


@app.post("/api/drift/accept")
def drift_accept(body: Accept):
    try:
        monitor.accept_baseline(body.engine, body.model)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return {"ok": True}


@app.get("/api/alerts")
def alerts(unacknowledged: bool = False):
    with session_scope() as s:
        q = select(Alert).order_by(Alert.id.desc()).limit(200)
        if unacknowledged:
            q = q.where(Alert.acknowledged.is_(False))
        return [{"id": a.id, "kind": a.kind, "severity": a.severity, "title": a.title, "body": a.body,
                 "acknowledged": a.acknowledged, "created_at": a.created_at, "project_id": a.project_id}
                for a in s.scalars(q)]


@app.post("/api/alerts/{aid}/ack")
def ack_alert(aid: int):
    with session_scope() as s:
        _404(s.get(Alert, aid), "alert").acknowledged = True
    audit.record("alert.acknowledged", "user", {"alert_id": aid})
    return {"ok": True}
