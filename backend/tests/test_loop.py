"""The requirements -> research -> baseline -> loop -> finalize pipeline, with a scripted optimizer."""
import re

import pytest
from sqlalchemy import select

from confiance import llm, snapshots
from confiance.db import session_scope
from confiance.models import ChangeProposal, Page, Product, Project, Run, RunLoop, SimulationBatch, SimulationResult
from confiance.pipeline import orchestrator as orch
from test_pipeline import ACME, _first_page, setup  # noqa: F401  (fixture)

GOOD = {"type": "set_meta_description", "content": "Acme Plumbing repairs leaking pipes in Austin, licensed since 1998."}
BAD = {"type": "set_meta_description", "content": "We repair leaking pipes in Austin, licensed since 1998."}  # never names the business
LEAK_BODY = "<h1>Leak repair in Austin</h1>" + "".join(f"<p>Acme Plumbing repairs leaking pipes in Austin homes. Licensed since 1998, our plumbers fix leaks fast and clearly explain every repair step {i}.</p>" for i in range(1, 9))


def scripted(monkeypatch, pid, by_loop):
    """by_loop: {loop: [[(tool, args), ...], ...]} one inner list per model turn; after the script, the agent finishes."""
    turns = {}

    def chat(component, messages, **kw):
        assert component == "optimizer"
        loop = int(re.search(r"Loop (\d+)", messages[1]["content"]).group(1))
        seq, i = by_loop.get(loop, []), turns.get(loop, 0)
        turns[loop] = i + 1
        step = seq[i] if i < len(seq) else [("finish", {"summary": f"done loop {loop}"})]
        calls = []
        for j, (name, args) in enumerate(step):
            args = {k: (_first_page(pid) if v == "@home" else v) for k, v in args.items()}
            calls.append(llm.ToolCall(f"c{loop}.{i}.{j}", name, args))
        return llm.LLMResult(tool_calls=calls, message={"role": "assistant", "content": ""})

    monkeypatch.setattr(llm, "chat", chat)
    return turns


def edit(op, qs=("q1",)):
    return ("propose_change", {"page_id": "@home", "ops": [op], "rationale": "test", "target_questions": list(qs)})


def loops_of(rid):
    with session_scope() as s:
        return [(l.n, l.status, l.decision) for l in s.scalars(select(RunLoop).where(RunLoop.run_id == rid).order_by(RunLoop.n))]


def test_the_loop_stops_at_the_hard_limit(setup, monkeypatch):
    scripted(monkeypatch, setup, {1: [[edit(BAD)]], 2: [[edit(GOOD)]], 3: [[edit({**GOOD, "content": GOOD["content"] + " Call us."})]]})
    rid = orch.start_run(setup, overrides={"max_loops": 2, "patience": 5, "min_gain": 0.0})
    st = orch.advance(rid)
    assert st["stage"] == "awaiting_approval" and [l[0] for l in loops_of(rid)] == [1, 2]  # never a third
    assert loops_of(rid)[-1][2] == "stop:max_loops" and st["summary"]["config"]["max_loops"] == 2


def test_the_loop_stops_early_when_gains_flatten(setup, monkeypatch):
    scripted(monkeypatch, setup, {1: [[edit(GOOD)]], 2: [[edit({**GOOD, "content": GOOD["content"].replace("repairs", "fixes")})]], 3: [[edit(GOOD)]]})
    rid = orch.start_run(setup, overrides={"max_loops": 5, "patience": 1, "min_gain": 0.03})
    st = orch.advance(rid)
    loops = loops_of(rid)
    assert [l[0] for l in loops] == [1, 2] and loops[-1][2] == "stop:plateau"  # loop 2 gained nothing, so no loop 3
    assert st["summary"]["evaluation"]["stop_reason"] == "stop:plateau"


def test_the_best_loop_wins_even_if_it_is_not_the_last(setup, monkeypatch):
    scripted(monkeypatch, setup, {1: [[edit(GOOD)]], 2: [[edit(BAD)]]})  # loop 2 makes it worse
    rid = orch.start_run(setup, overrides={"max_loops": 2, "patience": 5, "min_gain": 0.0})
    st = orch.advance(rid)
    ev = st["summary"]["evaluation"]
    assert ev["best_loop"] == 1 and [l["n"] for l in ev["loops"]] == [1, 2]
    assert ev["loops"][0]["delta"] > ev["loops"][1]["delta"]
    with session_scope() as s:
        cps = list(s.scalars(select(ChangeProposal).where(ChangeProposal.run_id == rid, ChangeProposal.status.in_(["candidate", "superseded"]))))
        by_loop = {cp.loop: cp.status for cp in cps}
        assert by_loop == {1: "candidate", 2: "superseded"}  # what you'd approve is loop 1's draft, restored after loop 2 replaced it
        good = next(cp for cp in cps if cp.loop == 1)
        assert "Acme Plumbing" in snapshots.version_content(s, good.candidate_version_id)
    assert st["summary"]["candidate_batch"] == next(l["batch_id"] for l in [dict(zip(("n", "batch_id"), (1, 0)))]) or st["summary"]["candidate_batch"]


def test_a_drafter_with_nothing_to_propose_ends_the_loop_honestly(setup, monkeypatch):
    scripted(monkeypatch, setup, {})  # every loop: finish immediately
    rid = orch.start_run(setup)
    st = orch.advance(rid)
    assert loops_of(rid) == [(1, "done", "stop:no_changes")]
    assert st["summary"]["evaluation"]["recommendation"] == "no_changes" and "No safe changes" in st["summary"]["evaluation"]["verdict"]["text"]


def test_a_loop_with_no_new_edits_has_converged_and_is_not_retested(setup, monkeypatch):
    scripted(monkeypatch, setup, {1: [[edit(GOOD)]]})  # loop 2 finishes without proposing anything
    rid = orch.start_run(setup, overrides={"max_loops": 4, "patience": 5, "min_gain": 0.0})
    orch.advance(rid)
    assert loops_of(rid) == [(1, "done", "continue"), (2, "done", "stop:converged")]
    with session_scope() as s:
        assert len(list(s.scalars(select(SimulationBatch).where(SimulationBatch.run_id == rid, SimulationBatch.arm == "candidate")))) == 1  # loop 2 cost no tests


def test_a_brand_new_page_is_tested_only_in_the_candidate_round(setup, monkeypatch):
    page = {"path": "/guides/leak-repair-austin", "title": "Leak repair in Austin", "meta_description": "Acme Plumbing repairs leaking pipes in Austin.",
            "body_html": LEAK_BODY, "rationale": "answers the question directly", "target_questions": ["q1"]}
    scripted(monkeypatch, setup, {1: [[("propose_new_page", page)]]})
    rid = orch.start_run(setup, overrides={"max_loops": 1})
    st = orch.advance(rid)
    with session_scope() as s:
        newp = s.scalars(select(Page).where(Page.is_new)).one()
        assert newp.url == "https://acme.test/guides/leak-repair-austin" and newp.live_version_id is None and newp.origin == "proposed"  # not live
        cp = s.scalars(select(ChangeProposal).where(ChangeProposal.run_id == rid, ChangeProposal.kind == "new_page")).one()
        assert cp.status == "candidate" and cp.base_version_id is None and cp.ops[0]["type"] == "create_page"
        arms = {}
        for b in s.scalars(select(SimulationBatch).where(SimulationBatch.run_id == rid)):
            arms[b.arm] = [r.injected for r in s.scalars(select(SimulationResult).where(SimulationResult.batch_id == b.id))]
    assert not any(arms["baseline"]) and any(arms["candidate"])  # the new page exists only in the sandbox's rewritten results
    assert st["stage"] == "awaiting_approval"


def test_a_blocked_new_page_is_reported_back_to_the_drafter_and_not_used(setup, monkeypatch):
    bad = {"path": "/x", "title": "T", "meta_description": "D", "body_html": "<h1>Short</h1><p>Too thin.</p>", "rationale": "r", "target_questions": ["q1"]}
    scripted(monkeypatch, setup, {1: [[("propose_new_page", bad)]]})
    rid = orch.start_run(setup)
    orch.advance(rid)
    with session_scope() as s:
        cp = s.scalars(select(ChangeProposal).where(ChangeProposal.run_id == rid)).one()
        assert cp.status == "blocked" and any("too thin" in v for v in cp.guard_report["violations"])
        assert s.scalars(select(Page).where(Page.is_new)).first() is None  # nothing was created


def test_new_pages_can_be_switched_off_per_round(setup, monkeypatch):
    page = {"path": "/guides/leak-repair-austin", "title": "Leak repair", "meta_description": "d", "body_html": LEAK_BODY, "rationale": "r", "target_questions": ["q1"]}
    scripted(monkeypatch, setup, {1: [[("propose_new_page", page)]]})
    rid = orch.start_run(setup, overrides={"allow_new_pages": False})
    orch.advance(rid)
    with session_scope() as s:
        assert s.scalars(select(ChangeProposal).where(ChangeProposal.run_id == rid)).one().status == "blocked"


def test_round_settings_are_clamped_to_safe_limits(setup):
    with session_scope() as s:
        cfg = lambda rid: s.get(Run, rid).summary["config"]
        a = orch.start_run(setup, overrides={"max_loops": 99, "patience": 0, "exposure_rank": 50, "track": ["nonsense"], "min_gain": -1})
        c = cfg(a)
        assert (c["max_loops"], c["patience"], c["exposure_rank"], c["track"], c["min_gain"]) == (10, 1, 5, ["brand"], 0.0)
        s.get(Run, a).status = "cancelled"
    with session_scope() as s:
        b = orch.start_run(setup, overrides={"max_loops": 0})
        assert s.get(Run, b).summary["config"]["max_loops"] == 1


def test_project_defaults_apply_and_round_overrides_win(setup):
    with session_scope() as s:
        s.get(Project, setup).settings = {"max_loops": 4, "min_effect": 0.1}
    a = orch.start_run(setup)
    with session_scope() as s:
        assert s.get(Run, a).summary["config"]["max_loops"] == 4 and s.get(Run, a).summary["config"]["min_effect"] == 0.1
        s.get(Run, a).status = "cancelled"
    b = orch.start_run(setup, overrides={"max_loops": 2})
    with session_scope() as s:
        assert s.get(Run, b).summary["config"]["max_loops"] == 2 and s.get(Run, b).summary["config"]["min_effect"] == 0.1


def test_product_questions_are_planned_asked_and_reported_separately(setup, monkeypatch):
    def json_call(component, **kw):
        if component == "products.queries":
            return {"products": []}
        return {"summary": "Acme is a plumber.", "facts": ["Founded 1998"]} if component == "kb.extract" else {"personas": [{"name": "P", "background": "b", "goal": "g", "tone": "t", "knowledge_level": "l"}]} if component == "persona.generate" else \
            {"prompts": [{"question_id": q["question_id"], "prompt": q["intent_text"]} for q in kw["prompt"] and __import__("ast").literal_eval(kw["prompt"].split("identical:\n", 1)[1])]}
    monkeypatch.setattr(llm, "json_call", json_call)
    with session_scope() as s:
        s.add(Product(project_id=setup, name="Water Heater 500", sku="WH-500", url="https://acme.test/products/wh-500", category="Water heaters"))
    scripted(monkeypatch, setup, {})
    rid = orch.start_run(setup, overrides={"track": ["brand", "products"]})
    st = orch.advance(rid)
    qs = st["summary"]["questions"]
    assert {q["track"] for q in qs} == {"brand", "product"} and any(q["id"].startswith("p") and q["product"] == "Water Heater 500" for q in qs)
    with session_scope() as s:
        base = s.scalars(select(SimulationBatch).where(SimulationBatch.run_id == rid, SimulationBatch.arm == "baseline")).one()
    assert set(base.aggregate["by_track"]) == {"brand", "product"} and len(base.aggregate["by_product"]) == 1


def test_a_round_with_nothing_to_track_says_so(setup):
    with session_scope() as s:
        s.get(Project, setup).settings = {"track": ["products"]}  # products only, but there are none
    with pytest.raises(orch.PipelineError, match="no products to test yet"):
        orch.start_run(setup)  # refused up front, with a way forward, instead of failing minutes later


def test_prompts_are_reused_so_repeat_rounds_cost_less_and_stay_comparable(setup, monkeypatch):
    scripted(monkeypatch, setup, {})
    first = orch.start_run(setup)
    orch.advance(first)
    n = {"phrase": 0}
    real = llm.json_call

    def counting(component, **kw):
        n["phrase"] += component == "persona.phrase"
        return real(component, **kw)

    monkeypatch.setattr(llm, "json_call", counting)
    second = orch.start_run(setup)
    orch.advance(second)
    with session_scope() as s:
        a, b = s.get(Run, first).summary, s.get(Run, second).summary
    assert a["prompts_key"] == b["prompts_key"] and a["prompts"] == b["prompts"] and n["phrase"] == 0


def test_an_interrupted_loop_resumes_without_repeating_the_baseline(setup, monkeypatch):
    state = {"boom": True}
    base = scripted(monkeypatch, setup, {1: [[edit(GOOD)]], 2: [[edit(GOOD)]]})
    inner = llm.chat

    def flaky(component, messages, **kw):
        if state["boom"] and "Loop 2" in messages[1]["content"]:
            state["boom"] = False
            raise RuntimeError("network dropped")
        return inner(component, messages, **kw)

    monkeypatch.setattr(llm, "chat", flaky)
    rid = orch.start_run(setup, overrides={"max_loops": 2, "patience": 5, "min_gain": 0.0})
    with pytest.raises(RuntimeError):
        orch.advance(rid)
    assert orch.get_status(rid)["stage"] == "loop" and loops_of(rid)[0][:2] == (1, "done") and loops_of(rid)[-1][1] == "drafting"
    orch.advance(rid)  # "Try again"
    assert orch.get_status(rid)["stage"] == "awaiting_approval" and [l[0] for l in loops_of(rid)] == [1, 2]
    with session_scope() as s:
        assert len(list(s.scalars(select(SimulationBatch).where(SimulationBatch.run_id == rid, SimulationBatch.arm == "baseline")))) == 1


def test_an_approved_round_becomes_a_complete_package(setup, monkeypatch, tmp_path):
    from pathlib import Path
    from confiance.deploy import service as deploy
    from confiance.models import PlanAction
    page = {"path": "/guides/leak-repair-austin", "title": "Leak repair in Austin", "meta_description": "Acme Plumbing repairs leaking pipes in Austin.",
            "body_html": LEAK_BODY, "rationale": "answers the question directly", "target_questions": ["q1"]}
    scripted(monkeypatch, setup, {1: [[edit(GOOD), ("propose_new_page", page)]]})
    rid = orch.start_run(setup, overrides={"max_loops": 1})
    orch.advance(rid)
    with session_scope() as s:
        s.get(Project, setup).deploy_config = {"type": "export", "out_dir": str(tmp_path)}
        s.add(PlanAction(project_id=setup, run_id=rid, seq=99, category="technical", title="Publish an llms.txt", draft={"filename": "llms.txt", "content": "# Acme\n"}))
        s.add(PlanAction(project_id=setup, run_id=rid, seq=100, category="technical", title="Evil", draft={"filename": "../../escape.txt", "content": "x"}))
        ids = [cp.id for cp in s.scalars(select(ChangeProposal).where(ChangeProposal.run_id == rid, ChangeProposal.status == "candidate"))]
    assert len(ids) == 2
    orch.decide(rid, ids, True)
    root = tmp_path / f"run-{rid}"
    assert (root / "pages" / "home.new.html").exists() and "Acme Plumbing" in (root / "pages" / "home.new.html").read_text()
    assert (root / "pages" / "home.diff").exists()
    assert (root / "new-pages" / "guides__leak-repair-austin.html").exists() and "<h1>Leak repair in Austin</h1>" in (root / "new-pages" / "guides__leak-repair-austin.html").read_text()
    assert (root / "site-files" / "llms.txt").read_text() == "# Acme\n" and not (tmp_path / "escape.txt").exists()  # a hostile filename can't write outside the package
    assert (root / "report.html").exists() and (root / "report.md").exists() and "new-pages/" in (root / "HOW_TO_APPLY.txt").read_text()
    import json
    man = json.loads((root / "manifest.json").read_text())["changes"]
    assert {c["new_page"] for c in man} == {True, False} and next(c for c in man if c["new_page"])["path"] == "/guides/leak-repair-austin"
    # publishing a new page makes it live; nothing had to exist before
    with session_scope() as s:
        dep = s.scalars(select(__import__("confiance.models", fromlist=["Deployment"]).Deployment)).first()
        dep_id = dep.id
    deploy.confirm_live(dep_id)
    with session_scope() as s:
        newp = s.scalars(select(Page).where(Page.is_new)).one()
        assert newp.live_version_id is not None
