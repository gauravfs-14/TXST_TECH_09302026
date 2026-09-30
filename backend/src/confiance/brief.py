"""The client brief: goals + constraints. Versioned and immutable; every run pins a brief version."""

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import audit
from .models import Brief, Project


class TargetQuestion(BaseModel):
    id: str
    text: str
    priority: int = Field(default=1, ge=1, le=5)
    intent: str = ""  # e.g. "comparison", "how-to", "best-of"


class Constraints(BaseModel):
    # Which pages may be touched (glob on URL path, e.g. "/blog/*"). Empty = all crawled pages.
    editable_url_globs: list[str] = Field(default_factory=list)
    # CSS selectors whose subtree must stay byte-identical (legal, pricing, testimonials...).
    locked_selectors: list[str] = Field(default_factory=list)
    # Phrases that must remain on the page verbatim (claims, disclaimers, prices).
    locked_phrases: list[str] = Field(default_factory=list)
    allowed_ops: list[str] = Field(default_factory=lambda: [
        "set_title", "set_meta_description", "add_jsonld", "add_faq", "insert_after", "append_section", "replace_block"])
    # Claims we must never make.
    forbidden_claims: list[str] = Field(default_factory=list)
    # Max share of visible text an iteration may change on one page.
    max_change_ratio: float = Field(default=0.35, ge=0.0, le=1.0)
    # Numbers in added text must be traceable to the page or KB (no invented statistics).
    require_grounded_numbers: bool = True


class BriefData(BaseModel):
    business_summary: str = ""
    goals: str = ""
    target_questions: list[TargetQuestion] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    competitors: list[str] = Field(default_factory=list)  # domains
    audience: list[str] = Field(default_factory=list)  # free-text audience descriptions
    brand_voice: str = ""
    constraints: Constraints = Field(default_factory=Constraints)


def create_version(s: Session, project: Project, data: BriefData, *, note: str = "", by: str = "user") -> Brief:
    version = project.current_brief_version + 1
    b = Brief(project_id=project.id, version=version, data=data.model_dump(), note=note, created_by=by)
    s.add(b)
    project.current_brief_version = version
    s.flush()
    audit.record("brief.version_created", by, {"version": version, "note": note,
                                              "questions": len(data.target_questions)}, project_id=project.id)
    return b


def get(s: Session, project_id: int, version: int | None = None) -> tuple[int, BriefData]:
    q = select(Brief).where(Brief.project_id == project_id)
    q = q.where(Brief.version == version) if version else q.order_by(Brief.version.desc()).limit(1)
    b = s.scalars(q).first()
    if b is None:
        raise LookupError(f"no brief for project {project_id}")
    return b.version, BriefData.model_validate(b.data)
