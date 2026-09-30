"""Persistent data model.

Immutability rules (enforced by the service layer, not the DB):
  * Brief rows are never updated; a change creates a new version.
  * PageVersion rows are never updated; content lives in the content-addressed blob store.
  * AuditEvent rows are append-only and hash-chained.
"""

from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, utcnow


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    domain: Mapped[str] = mapped_column(String(255))
    site_url: Mapped[str] = mapped_column(String(500), default="")
    brand_aliases: Mapped[list] = mapped_column(default=list)
    engines: Mapped[list] = mapped_column(default=list)  # [{"name": "claude", "model": "..."}]
    deploy_config: Mapped[dict] = mapped_column(default=dict)
    current_brief_version: Mapped[int] = mapped_column(default=0)
    kb_version: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Brief(Base):
    __tablename__ = "briefs"
    __table_args__ = (UniqueConstraint("project_id", "version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    version: Mapped[int]
    data: Mapped[dict]
    note: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(100), default="user")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Page(Base):
    __tablename__ = "pages"
    __table_args__ = (UniqueConstraint("project_id", "url"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    url: Mapped[str] = mapped_column(String(1000))
    source_path: Mapped[str | None] = mapped_column(String(1000), default=None)  # file in client repo
    live_version_id: Mapped[int | None] = mapped_column(default=None)


class PageVersion(Base):
    __tablename__ = "page_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("pages.id"))
    version_no: Mapped[int]
    blob_hash: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(20))  # crawl | candidate | deployed | rollback
    parent_id: Mapped[int | None] = mapped_column(default=None)
    run_id: Mapped[int | None] = mapped_column(default=None)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class KnowledgeItem(Base):
    __tablename__ = "knowledge_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    kb_version: Mapped[int]
    kind: Mapped[str] = mapped_column(String(20))  # summary | fact | chunk
    content: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(String(1000), default=None)


class Persona(Base):
    __tablename__ = "personas"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    name: Mapped[str] = mapped_column(String(200))
    profile: Mapped[dict]
    active: Mapped[bool] = mapped_column(default=True)


class Run(Base):
    """One iteration of the optimize -> sandbox -> deploy -> measure loop."""

    __tablename__ = "runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    iteration: Mapped[int]
    brief_version: Mapped[int]
    stage: Mapped[str] = mapped_column(String(40), default="created")
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|running|waiting|done|failed
    error: Mapped[str | None] = mapped_column(Text, default=None)
    summary: Mapped[dict] = mapped_column(default=dict)
    measure_after: Mapped[datetime | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class SimulationBatch(Base):
    __tablename__ = "simulation_batches"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), default=None)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"), default=None)
    arm: Mapped[str] = mapped_column(String(40))
    mode: Mapped[str] = mapped_column(String(20))  # controlled | native
    aggregate: Mapped[dict] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class SimulationResult(Base):
    __tablename__ = "simulation_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("simulation_batches.id"))
    engine: Mapped[str] = mapped_column(String(40))
    model_id: Mapped[str] = mapped_column(String(100), default="")
    persona_id: Mapped[int | None] = mapped_column(default=None)
    question_id: Mapped[str] = mapped_column(String(64))
    prompt: Mapped[str] = mapped_column(Text)
    sample_idx: Mapped[int] = mapped_column(default=0)
    answer: Mapped[str] = mapped_column(Text, default="")
    citations: Mapped[list] = mapped_column(default=list)
    retrieved_urls: Mapped[list] = mapped_column(default=list)
    queries: Mapped[list] = mapped_column(default=list)
    injected: Mapped[bool] = mapped_column(default=False)
    metrics: Mapped[dict] = mapped_column(default=dict)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    latency_ms: Mapped[int] = mapped_column(default=0)


class ChangeProposal(Base):
    __tablename__ = "change_proposals"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"))
    page_id: Mapped[int] = mapped_column(ForeignKey("pages.id"))
    ops: Mapped[list]
    rationale: Mapped[str] = mapped_column(Text, default="")
    target_questions: Mapped[list] = mapped_column(default=list)
    # proposed | blocked | candidate | approved | rejected | deployed
    status: Mapped[str] = mapped_column(String(20), default="proposed")
    guard_report: Mapped[dict] = mapped_column(default=dict)
    base_version_id: Mapped[int | None] = mapped_column(default=None)
    candidate_version_id: Mapped[int | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Deployment(Base):
    __tablename__ = "deployments"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"), default=None)
    kind: Mapped[str] = mapped_column(String(20))  # deploy | rollback
    deployer: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20))  # pending | applied | draft_open | failed
    external_ref: Mapped[str | None] = mapped_column(String(1000), default=None)
    versions: Mapped[dict] = mapped_column(default=dict)  # page_id -> {"from": id, "to": id}
    details: Mapped[dict] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class DriftBaseline(Base):
    __tablename__ = "drift_baselines"
    id: Mapped[int] = mapped_column(primary_key=True)
    engine: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(100))
    fingerprint: Mapped[dict]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class DriftCheck(Base):
    __tablename__ = "drift_checks"
    id: Mapped[int] = mapped_column(primary_key=True)
    engine: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20))  # ok | drift | error | baseline
    findings: Mapped[list] = mapped_column(default=list)
    observed: Mapped[dict] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(default=None)
    kind: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(10))  # info | warning | critical
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text, default="")
    acknowledged: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(default=utcnow)
    project_id: Mapped[int | None] = mapped_column(default=None)
    run_id: Mapped[int | None] = mapped_column(default=None)
    actor: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict] = mapped_column(default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


class UsageRecord(Base):
    __tablename__ = "usage_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(default=utcnow)
    project_id: Mapped[int | None] = mapped_column(default=None)
    run_id: Mapped[int | None] = mapped_column(default=None)
    component: Mapped[str] = mapped_column(String(60))
    provider: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(100))
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    cache_read_tokens: Mapped[int] = mapped_column(default=0)
    cache_write_tokens: Mapped[int] = mapped_column(default=0)
    cost_usd: Mapped[float] = mapped_column(default=0.0)
