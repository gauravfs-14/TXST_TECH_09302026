"""The live progress view: counters, the activity feed, and honesty about waiting."""
from fastapi.testclient import TestClient

from confiance import activity
from confiance.context import scope


def test_percent_moves_through_stages_and_never_hits_100_early():
    rid = 901
    activity.reset(rid)
    seen = []
    for stage, total in [("requirements", 0), ("research", 4), ("baseline", 10), ("loop", 0), ("finalize", 0)]:
        activity.set_stage(rid, stage, total)
        with scope(None, rid):
            if stage == "loop":
                activity.set_loop(rid, 2, 3, "test")
            if total:
                activity.tick(total // 2)
        seen.append(activity.snapshot(rid)["pct"])
    assert seen == sorted(seen) and seen[0] == 0 and 70 < seen[-1] < 100
    activity.set_stage(rid, "awaiting_approval")
    assert activity.snapshot(rid)["pct"] == 100.0


def test_half_way_through_a_batch_is_half_of_that_stage():
    rid = 902
    activity.reset(rid)
    activity.set_stage(rid, "baseline", 10)
    with scope(None, rid):
        activity.tick(5)
    s = activity.snapshot(rid)
    assert (s["stage_done"], s["stage_total"]) == (5, 10) and round(s["pct"], 1) == round(6 + 12 + 22 * 0.5, 1)


def test_events_are_incremental_and_bounded():
    rid = 903
    activity.reset(rid)
    with scope(None, rid):
        for i in range(600):
            activity.emit(f"e{i}")
    first = activity.snapshot(rid)
    assert len(first["events"]) == activity.MAX_EVENTS and first["events"][-1]["text"] == "e599"
    with scope(None, rid):
        activity.emit("later")
    later = activity.snapshot(rid, after=first["last_seq"])
    assert [e["text"] for e in later["events"]] == ["later"]


def test_emit_outside_a_run_is_a_harmless_noop():
    activity.emit("nobody is listening")  # no run in context: must not raise or leak into another run
    assert activity.snapshot(999_999)["known"] is False


def test_waiting_is_visible_and_llm_in_flight_is_counted():
    rid = 904
    activity.reset(rid)
    with scope(None, rid):
        h = activity.llm_started()
        s = activity.snapshot(rid)
        assert s["in_flight"] == 1
        activity.waiting(30, "The AI service asked us to slow down.")
        w = activity.snapshot(rid)["waiting"]
        assert 25 <= w["seconds_left"] <= 30 and "slow down" in w["reason"]
        activity.llm_finished(h)
    done = activity.snapshot(rid)
    assert done["in_flight"] == 0 and done["llm_calls"] == 1
    assert any(e["kind"] == "wait" for e in done["events"])


def test_unknown_run_is_reported_as_unknown_not_an_error():
    from confiance.api.app import app
    with TestClient(app) as c:
        with __import__("confiance.db", fromlist=["x"]).session_scope() as s:
            from confiance.models import Project, Run
            p = Project(name="x", domain="x.test", engines=[])
            s.add(p); s.flush()
            r = Run(project_id=p.id, iteration=1, brief_version=1)
            s.add(r); s.flush()
            rid = r.id
        j = c.get(f"/api/runs/{rid}/live").json()
        assert j["known"] is False and j["events"] == [] and "status" in j


def test_a_run_interrupted_by_a_restart_can_be_resumed():
    from confiance.db import session_scope
    from confiance.models import Project, Run
    from confiance.pipeline import orchestrator as orch
    with session_scope() as s:
        p = Project(name="x", domain="x.test", engines=[])
        s.add(p); s.flush()
        r = Run(project_id=p.id, iteration=1, brief_version=1, stage="baseline", status="running")
        s.add(r); s.flush()
        rid = r.id
    assert orch.recover_interrupted() == 1
    st = orch.get_status(rid)
    assert st["status"] == "failed" and st["stage"] == "baseline" and "interrupted" in st["error"]
    orch._claim(rid)  # resuming is allowed again (it would be refused while 'running')


def test_the_loop_stage_advances_loop_by_loop_and_reports_where_it_is():
    rid = 905
    activity.reset(rid)
    activity.set_stage(rid, "loop")
    activity.set_loop(rid, 1, 4, "draft")
    a = activity.snapshot(rid)
    activity.set_loop(rid, 3, 4, "test")
    with scope(None, rid):
        activity.set_total(10)
        activity.tick(5)
    b = activity.snapshot(rid)
    assert a["loop"] == {"n": 1, "max": 4, "phase": "draft"} and b["loop"]["n"] == 3 and b["pct"] > a["pct"] + 15
