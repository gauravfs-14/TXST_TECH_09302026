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
    orch.html_fetcher = lambda u: "<html><head><title>Rival</title></head><body><h1>Rival plumbing</h1><h2>What we fix</h2><p>Leaks and pipes.</p></body></html>"  # no network in tests

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
        elif n == 4:
            c = [tc("t5", "get_findability", {}), tc("t6", "recommend", {"title": "Write a page for the specific topic",
                 "action": "Create a dedicated page about leak repair in Austin.", "why": "Broad questions are dominated by large sites."})]
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
    assert set(st["summary"]["findability_summary"]) == {"questions_checked", "questions_found", "brand_found"}
    assert {i["id"] for i in st["summary"]["findability"]} == {"q1", "brand"}
    assert st["summary"]["recommendations"][0]["title"].startswith("Write a page")
    from fastapi.testclient import TestClient
    from confiance.api.app import app
    with TestClient(app) as tc_:
        j = tc_.get(f"/api/runs/{rid}/summary").json()
        assert j["recommendations"] and j["findability"][0]["status"] in ("found", "not_found", "unknown")
    from confiance import activity
    live = activity.snapshot(rid)
    kinds = {e["kind"] for e in live["events"]}
    assert live["pct"] == 100.0 and {"step", "ask", "tool"} <= kinds  # real progress and a real feed, from a real run
    assert any("Blocked an idea" in e["text"] for e in live["events"])  # the guard's veto is visible live
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


def test_plans_and_estimates(setup):
    from confiance.pipeline import plans
    q = plans.estimate_calls(6, "quick")["now"], plans.estimate_calls(6, "standard")["now"], plans.estimate_calls(6, "thorough")["now"]
    assert q[0] < q[1] < q[2] and q[0] < 150  # a quick check stays small enough for a free tier
    assert plans.estimate_calls(6, "nonsense") == plans.estimate_calls(6, "quick")  # unknown -> safe default
    assert plans.estimate_calls(6, "quick", judge=True)["now"] > plans.estimate_calls(6, "quick")["now"]
    from fastapi.testclient import TestClient
    from confiance.api.app import app
    with TestClient(app) as c:
        r = c.get(f"/api/projects/{setup}/plans").json()
        assert r["questions"] == 1 and [p["id"] for p in r["plans"]] == ["quick", "standard", "thorough"]
    rid = orch.start_run(setup, "standard")
    from confiance.models import Run
    with session_scope() as s:
        assert s.get(Run, rid).summary["plan"] == "standard"


def test_only_targeted_questions_are_reasked_and_comparisons_stay_fair(setup, monkeypatch):
    from confiance import brief as briefs2
    with session_scope() as s:
        p = s.get(Project, setup)
        briefs2.create_version(s, p, BriefData(target_questions=[TargetQuestion(id="q1", text="who can fix a leaking pipe in Austin"),
                                                                 TargetQuestion(id="q2", text="who repairs water heaters in Austin")],
                                               competitors=["rival.test"], constraints=Constraints()))
    monkeypatch.setattr("confiance.sim.personas.phrase_prompts", lambda persona, brief: {q.id: q.text for q in brief.target_questions})
    scripted_optimizer(monkeypatch, lambda: _first_page(setup))  # its proposal targets q1 only
    rid = orch.start_run(setup)
    st = orch.advance(rid)
    assert st["stage"] == "awaiting_approval", st
    assert st["summary"]["candidate_questions"] == ["q1"]
    from confiance.models import SimulationBatch, SimulationResult
    with session_scope() as s:
        arms = {b.arm: {r.question_id for r in s.scalars(select(SimulationResult).where(SimulationResult.batch_id == b.id))}
                for b in s.scalars(select(SimulationBatch).where(SimulationBatch.run_id == rid))}
    assert arms["baseline"] == {"q1", "q2"} and arms["candidate"] == {"q1"}  # fewer conversations, same evidence for q1
    from fastapi.testclient import TestClient
    from confiance.api.app import app
    with TestClient(app) as c:
        j = c.get(f"/api/runs/{rid}/summary").json()
        assert {q["id"]: q["retested"] for q in j["questions"]} == {"q1": True, "q2": False}
        base_q1 = next(q for q in j["questions"] if q["id"] == "q1")["before"]["mentioned"]
        assert j["before"]["mentioned"] == base_q1  # headline "before" covers only the re-asked question
        live = c.get(f"/api/runs/{rid}/live").json()
        assert {"concurrency", "rpm", "max_concurrency"} <= set(live["pace"])


def test_a_running_round_can_be_stopped_and_a_new_one_started(setup, monkeypatch):
    from confiance import activity
    pressed = {"n": 0}

    def chat(component, messages, **kw):  # the person presses Stop while the optimizer is thinking
        pressed["n"] += 1
        activity.request_cancel(rid)
        return llm.LLMResult(tool_calls=[llm.ToolCall("1", "get_weak_questions", {})], message={"role": "assistant", "content": ""})

    monkeypatch.setattr(llm, "chat", chat)
    rid = orch.start_run(setup)
    st = orch.advance(rid)
    assert st["status"] == "cancelled" and st["stage"] == "loop" and pressed["n"] == 1
    rid2 = orch.start_run(setup)  # 'cancelled' never blocks a new round
    assert rid2 != rid


def test_starting_a_new_round_replaces_one_still_waiting_for_approval(setup, monkeypatch):
    scripted_optimizer(monkeypatch, lambda: _first_page(setup))
    old = orch.start_run(setup)
    assert orch.advance(old)["stage"] == "awaiting_approval"
    new = orch.start_run(setup, "standard")
    with session_scope() as s:
        from confiance.models import Run
        assert s.get(Run, old).status == "cancelled"
        assert {p.status for p in s.scalars(select(ChangeProposal).where(ChangeProposal.run_id == old))} <= {"rejected", "blocked"}
        assert s.get(Run, new).summary["plan"] == "standard"


def test_cancel_endpoint_discards_a_waiting_round_and_refuses_finished_ones(setup, monkeypatch):
    from fastapi.testclient import TestClient
    from confiance.api.app import app
    scripted_optimizer(monkeypatch, lambda: _first_page(setup))
    rid = orch.start_run(setup)
    orch.advance(rid)
    with TestClient(app) as c:
        assert c.post(f"/api/runs/{rid}/cancel").json() == {"result": "cancelled"}
        assert c.post(f"/api/runs/{rid}/cancel").status_code == 409
        assert c.get(f"/api/runs/{rid}").json()["status"] == "cancelled"


def test_a_quick_round_uses_only_the_first_questions(setup, monkeypatch):
    from confiance import brief as briefs2
    from confiance.models import SimulationBatch, SimulationResult
    qs = [TargetQuestion(id=f"q{i}", text=f"who can fix pipe problem number {i} in Austin") for i in range(1, 7)]
    with session_scope() as s:
        briefs2.create_version(s, s.get(Project, setup), BriefData(target_questions=qs, competitors=["rival.test"], constraints=Constraints()))
    monkeypatch.setattr("confiance.sim.personas.phrase_prompts", lambda persona, brief: {q.id: q.text for q in brief.target_questions})
    scripted_optimizer(monkeypatch, lambda: _first_page(setup))
    rid = orch.start_run(setup, "quick")
    st = orch.advance(rid)
    assert st["summary"]["question_ids"] == ["q1", "q2", "q3", "q4"]
    with session_scope() as s:
        asked = {r.question_id for b in s.scalars(select(SimulationBatch).where(SimulationBatch.run_id == rid, SimulationBatch.arm == "baseline"))
                 for r in s.scalars(select(SimulationResult).where(SimulationResult.batch_id == b.id))}
    assert asked == {"q1", "q2", "q3", "q4"}
    from confiance.pipeline import plans
    assert plans.estimate_calls(4, "quick")["now"] < plans.estimate_calls(4, "thorough")["now"]
    assert plans.estimate_calls(4, "quick", loops=1)["now"] < plans.estimate_calls(4, "quick", loops=3)["now"]  # more loops can cost more, never less
    from fastapi.testclient import TestClient
    from confiance.api.app import app
    with TestClient(app) as c:  # the API caps a Quick round at its first 4 questions
        p = c.get(f"/api/projects/{setup}/plans?loops=2").json()
        quick = next(x for x in p["plans"] if x["id"] == "quick")
        assert p["questions"] == 6 and quick["now"] == plans.estimate_calls(4, "quick", loops=2)["now"]
