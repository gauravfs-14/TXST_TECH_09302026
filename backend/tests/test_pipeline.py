"""End-to-end loop with the offline engine/search and a scripted optimizer model (no network, no keys)."""
from types import SimpleNamespace as NS

import pytest
from sqlalchemy import select

from confiance import audit, brief as briefs, kb, llm, snapshots
from confiance.brief import BriefData, Constraints, TargetQuestion
from confiance.db import session_scope
from confiance.deploy import service as deploy
from confiance.models import ChangeProposal, Deployment, Page, Project
from confiance.pipeline import orchestrator as orch
from confiance.search.providers import OfflineCorpusSearch

ACME = "<html><head><title>Home</title></head><body><main><h1>Welcome</h1><p>Licensed plumbers in Austin since 1998. We repair leaking pipes and water heaters.</p></main></body></html>"
RIVAL = ("https://rival.test/", "Rival", "Rival plumbing offers cheap leak repair in Austin and emergency pipe repair.")


@pytest.fixture
def setup(monkeypatch):
    def json_call(component, **kw):
        if component == "kb.extract":
            return {"summary": "Acme Plumbing is a licensed Austin plumber.", "facts": ["Founded 1998", "Repairs leaks"]}
        if component == "persona.generate":
            return {"personas": [{"name": "Homeowner", "background": "b", "goal": "g", "tone": "t", "knowledge_level": "low"}]}
        if component == "persona.phrase":
            return {"prompts": [{"question_id": "q1", "prompt": "my pipe is leaking in austin who can fix it"}]}
        raise AssertionError(component)

    monkeypatch.setattr(llm, "json_call", json_call)
    orch.provider_factory = lambda: OfflineCorpusSearch([("https://acme.test/", "Local plumbers", ACME), RIVAL])

    with session_scope() as s:
        p = Project(name="Acme Plumbing", domain="acme.test", engines=[{"name": "offline"}], deploy_config={"type": "export", "out_dir": str(s.bind.url.database) + "-exports"})
        s.add(p)
        s.flush()
        briefs.create_version(s, p, BriefData(target_questions=[TargetQuestion(id="q1", text="who can fix a leaking pipe in Austin")],
                                              competitors=["rival.test"], constraints=Constraints()))
        kb.import_pages(s, p, [("https://acme.test/", ACME)])
        pid = p.id
    return pid


def scripted_optimizer(monkeypatch, page_lookup):
    calls = {"n": 0}

    def chat(component, messages, **kwargs):
        assert component == "optimizer"
        calls["n"] += 1
        n = calls["n"]
        tc = llm.ToolCall
        if n == 1:
            c = [tc("t1", "get_weak_questions", {})]
        elif n == 2:
            c = [tc("t2", "propose_change", {
                "page_id": page_lookup(), "rationale": "state brand and service directly", "target_questions": ["q1"],
                "ops": [{"type": "set_meta_description", "content": "Acme Plumbing repairs leaking pipes in Austin, licensed since 1998."}]})]
        elif n == 3:  # a blocked attempt is part of the loop too
            c = [tc("t3", "propose_change", {
                "page_id": page_lookup(), "rationale": "x", "target_questions": ["q1"],
                "ops": [{"type": "append_section", "html": "<p>Rated 4.9 by 900 customers</p>"}]})]
        else:
            c = [tc("t4", "finish", {"summary": "done"})]
        return llm.LLMResult(tool_calls=c, message={"role": "assistant", "content": None})

    monkeypatch.setattr(llm, "chat", chat)


def test_full_loop_deploy_and_rollback(setup, monkeypatch):
    pid = setup
    scripted_optimizer(monkeypatch, lambda: _first_page(pid))

    rid = orch.start_run(pid)
    st = orch.advance(rid)
    assert st["stage"] == "awaiting_approval" and st["status"] == "waiting", st
    ev = st["summary"]["evaluation"]
    assert ev["overall"]["delta"] > 0 and ev["recommendation"] in ("approve", "review")

    with session_scope() as s:
        props = list(s.scalars(select(ChangeProposal).where(ChangeProposal.run_id == rid)))
        assert sorted(p.status for p in props) == ["blocked", "candidate"]  # fabricated stats were blocked
        cand = next(p for p in props if p.status == "candidate")
        live_before = s.get(Page, cand.page_id).live_version_id
        cand_id = cand.id

    # nothing ships without approval
    with pytest.raises(deploy.DeployError):
        deploy.deploy_run(rid)
    orch.decide(rid, [cand_id], True)

    with session_scope() as s:
        st = orch.get_status(rid)
        assert st["stage"] == "awaiting_live", st  # export deployer leaves a package for a human
        dep = s.scalars(select(Deployment)).first()
        assert dep.status == "draft_open"
        assert s.get(Page, _first_page(pid)).live_version_id == live_before  # live pointer unchanged until confirmed
        dep_id = dep.id

    deploy.confirm_live(dep_id)
    with session_scope() as s:
        page = s.get(Page, _first_page(pid))
        assert page.live_version_id != live_before
        assert "leaking pipes in Austin" in snapshots.live_content(s, page)

    rb = deploy.rollback(dep_id)
    deploy.confirm_live(rb)
    with session_scope() as s:
        page = s.get(Page, _first_page(pid))
        assert snapshots.live_content(s, page) == ACME  # original content restored
        # original version is still in history: nothing was destroyed
        assert len(list(s.execute(select(Page.id)))) == 1
    assert audit.verify_chain()["ok"]


def test_stale_base_refused(setup, monkeypatch):
    pid = setup
    scripted_optimizer(monkeypatch, lambda: _first_page(pid))
    rid = orch.start_run(pid)
    orch.advance(rid)
    with session_scope() as s:
        cand = s.scalars(select(ChangeProposal).where(ChangeProposal.status == "candidate")).first()
        cid = cand.id
        page = s.get(Page, cand.page_id)
        v = snapshots.new_version(s, page, ACME + "<!-- edited by client -->", "crawl", parent_id=page.live_version_id)
        page.live_version_id = v.id  # client edited the live page after the proposal was made
        s.get(ChangeProposal, cid).status = "approved"
    with pytest.raises(deploy.DeployError, match="changed since"):
        deploy.deploy_run(rid)


def _first_page(pid):
    with session_scope() as s:
        return s.scalars(select(Page).where(Page.project_id == pid)).first().id
