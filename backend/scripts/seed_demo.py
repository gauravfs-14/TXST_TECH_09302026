"""Fill a database with a finished practice round so the web app can be explored without any API keys.
Uses the offline search/engine and a scripted 'optimizer'. NOT real results.

    CONFIANCE_DATABASE_URL=sqlite:///./demo.db CONFIANCE_ALLOW_OFFLINE=true uv run python scripts/seed_demo.py
"""
import os

os.environ.setdefault("CONFIANCE_ALLOW_OFFLINE", "true")
os.environ.setdefault("CONFIANCE_USE_LLM_JUDGE", "false")

from sqlalchemy import select  # noqa: E402

from confiance import brief as briefs, kb, llm  # noqa: E402
from confiance.brief import BriefData, Constraints, TargetQuestion  # noqa: E402
from confiance.db import init_db, session_scope  # noqa: E402
from confiance.models import Page, Project  # noqa: E402
from confiance.pipeline import orchestrator as orch  # noqa: E402
from confiance.search.providers import OfflineCorpusSearch  # noqa: E402

HOME = "<html><head><title>Home</title></head><body><main><h1>Welcome</h1><p>Licensed plumbers in Austin since 1998. We repair leaking pipes and water heaters.</p></main></body></html>"
SERVICES = "<html><head><title>Services</title></head><body><main><h1>Services</h1><p>Leak repair, water heater replacement and drain cleaning for homes in Austin.</p></main></body></html>"
RIVAL = ("https://rivalplumbing.test/", "Rival Plumbing", "Rival plumbing offers cheap leak repair in Austin and emergency pipe repair.")
QUESTIONS = ["who can fix a leaking pipe in Austin", "how much does a water heater replacement cost in Austin", "best plumber near me for a blocked drain"]

init_db()
with session_scope() as s:
    p = Project(name="Riverside Plumbing (demo)", domain="riversideplumbing.test", site_url="https://riversideplumbing.test",
                brand_aliases=["Riverside Plumbing"], engines=[{"name": "offline"}], deploy_config={"type": "export"})
    s.add(p); s.flush()
    briefs.create_version(s, p, BriefData(target_questions=[TargetQuestion(id=f"q{i+1}", text=t) for i, t in enumerate(QUESTIONS)],
                                          competitors=["rivalplumbing.test"], constraints=Constraints(locked_phrases=["Licensed plumbers in Austin since 1998"])))
    kb.import_pages(s, p, [("https://riversideplumbing.test/", HOME), ("https://riversideplumbing.test/services", SERVICES)])
    pid = p.id

def json_call(component, **kw):
    if component == "kb.extract":
        return {"summary": "Riverside Plumbing is a licensed plumber serving Austin since 1998.", "facts": ["Founded 1998", "Repairs leaks", "Replaces water heaters", "Cleans drains"]}
    if component == "persona.generate":
        return {"personas": [{"name": "Urgent homeowner", "background": "b", "goal": "g", "tone": "t", "knowledge_level": "low"}]}
    if component == "persona.phrase":
        return {"prompts": [{"question_id": f"q{i+1}", "prompt": t} for i, t in enumerate(QUESTIONS)]}
    raise AssertionError(component)

with session_scope() as s:
    pages = {p.url.rsplit("/", 1)[-1] or "home": p.id for p in s.scalars(select(Page))}
calls = {"n": 0}
def chat(component, messages, **kw):
    calls["n"] += 1
    n = calls["n"]; T = llm.ToolCall
    if n == 1: c = [T("1", "get_weak_questions", {})]
    elif n == 2: c = [T("2", "propose_change", {"page_id": pages["home"], "target_questions": ["q1"],
        "rationale": "Say the business name and what it fixes right at the top, so assistants can quote it.",
        "ops": [{"type": "set_meta_description", "content": "Riverside Plumbing repairs leaking pipes, water heaters and blocked drains across Austin. Licensed since 1998."},
                {"type": "add_faq", "items": [{"q": "Who can fix a leaking pipe in Austin?", "a": "Riverside Plumbing repairs leaking pipes in Austin. We have been licensed since 1998."}]}]})]
    elif n == 3: c = [T("3", "propose_change", {"page_id": pages["home"], "target_questions": ["q2"], "rationale": "Add customer ratings.",
        "ops": [{"type": "append_section", "html": "<p>Rated 4.9 stars by 2,300 customers.</p>"}]})]
    else: c = [T("4", "finish", {"summary": "Improved the home page."})]
    return llm.LLMResult(tool_calls=c, message={"role": "assistant", "content": None})

llm.json_call, llm.chat = json_call, chat
orch.provider_factory = lambda: OfflineCorpusSearch([("https://riversideplumbing.test/", "Local plumbers", HOME), ("https://riversideplumbing.test/services", "Plumbing services", SERVICES), RIVAL])
rid = orch.start_run(pid)
print(orch.advance(rid)["stage"], "run", rid, "project", pid)
