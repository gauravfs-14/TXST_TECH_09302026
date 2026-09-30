"""AI personas: simulated users who phrase the brief's target questions the way real people would."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, llm
from ..brief import BriefData
from ..models import Persona, Project

PERSONA_SCHEMA = {
    "type": "object",
    "properties": {"personas": {"type": "array", "items": {
        "type": "object",
        "properties": {"name": {"type": "string"}, "background": {"type": "string"},
                       "goal": {"type": "string"}, "tone": {"type": "string"},
                       "knowledge_level": {"type": "string"}},
        "required": ["name", "background", "goal", "tone", "knowledge_level"],
        "additionalProperties": False}}},
    "required": ["personas"], "additionalProperties": False,
}
PHRASE_SCHEMA = {
    "type": "object",
    "properties": {"prompts": {"type": "array", "items": {
        "type": "object",
        "properties": {"question_id": {"type": "string"}, "prompt": {"type": "string"}},
        "required": ["question_id", "prompt"], "additionalProperties": False}}},
    "required": ["prompts"], "additionalProperties": False,
}


def generate(s: Session, project: Project, brief: BriefData, kb_card: str, n: int = 4) -> list[Persona]:
    data = llm.json_call(
        "persona.generate", system=llm.cached_system(kb_card),
        prompt=f"Create {n} distinct, realistic people who would be searching for what this business offers. "
               f"Audience notes: {brief.audience}. Goals of the business: {brief.goals}. "
               "Vary background, urgency, tone and expertise. They are potential customers, not employees.",
        schema=PERSONA_SCHEMA, max_tokens=2000)
    for p in s.scalars(select(Persona).where(Persona.project_id == project.id, Persona.active)):
        p.active = False
    out = []
    for p in data["personas"][:n]:
        row = Persona(project_id=project.id, name=p["name"], profile=p)
        s.add(row)
        out.append(row)
    s.flush()
    audit.record("personas.generated", "persona_agent", {"names": [p.name for p in out]}, project_id=project.id)
    return out


def phrase_prompts(persona: Persona, brief: BriefData) -> dict[str, str]:
    """One call per persona phrases every target question in that persona's voice (cheap model)."""
    qs = [{"question_id": q.id, "intent_text": q.text} for q in brief.target_questions]
    data = llm.json_call(
        "persona.phrase",
        system="You role-play a real person typing questions to an AI assistant. Write exactly what they would "
               "type: natural, specific, sometimes imperfect. Never mention any brand unless the question does.",
        prompt=f"Persona: {persona.profile}\n\nRewrite each question in this person's own words, keeping the "
               f"underlying information need identical:\n{qs}",
        schema=PHRASE_SCHEMA, max_tokens=2000)
    got = {p["question_id"]: p["prompt"] for p in data["prompts"]}
    return {q.id: got.get(q.id) or q.text for q in brief.target_questions}
