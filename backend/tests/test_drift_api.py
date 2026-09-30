import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from confiance import notify
from confiance.db import session_scope
from confiance.drift import monitor
from confiance.engines import base
from confiance.engines.base import Engine, EngineAnswer, register
from confiance.models import Alert

STATE = {"model": "fake-1", "shape": ["text"], "search": True, "fail": False, "listed": ["fake-1"]}


@register("fakedrift")
class FakeDrift(Engine):
    provider = "fake"

    def controlled(self, convo, tools):
        raise NotImplementedError

    def native(self, convo):
        if STATE["fail"]:
            raise RuntimeError("404 model not found")
        return EngineAnswer(text="answer " * 40, citations=["https://x.test"], queries=["q"] if STATE["search"] else [],
                            model_id=STATE["model"], raw_shape=STATE["shape"])

    def list_models(self):
        return STATE["listed"]


@pytest.fixture(autouse=True)
def reset_state():
    STATE.update(model="fake-1", shape=["text"], search=True, fail=False, listed=["fake-1"])
    yield
    base._REGISTRY.pop("fakedrift", None) if False else None


def test_drift_lifecycle():
    assert monitor.check_engine("fakedrift", "fake-1")["status"] == "baseline"
    assert monitor.check_engine("fakedrift", "fake-1")["status"] == "ok"

    STATE.update(model="fake-2", shape=["text", "new_field"], search=False)
    res = monitor.check_engine("fakedrift", "fake-1")
    kinds = {f["kind"] for f in res["findings"]}
    assert res["status"] == "drift" and {"model_changed", "api_shape_changed", "behavior_shift"} <= kinds
    with session_scope() as s:
        assert s.scalars(select(Alert).where(Alert.kind == "drift.model_changed")).first()

    STATE.update(listed=[])  # model deprecated
    assert "model_missing" in {f["kind"] for f in monitor.check_engine("fakedrift", "fake-1")["findings"]}

    STATE.update(fail=True)
    assert "error_rate" in {f["kind"] for f in monitor.check_engine("fakedrift", "fake-1")["findings"]}


def test_alert_dedupe():
    assert notify.alert("k", "info", "t") is not None
    assert notify.alert("k", "info", "t") is None


def test_baseline_only_moves_on_human_accept():
    monitor.check_engine("fakedrift", "fake-1")
    STATE.update(model="fake-2")
    assert monitor.check_engine("fakedrift", "fake-1")["status"] == "drift"
    assert monitor.check_engine("fakedrift", "fake-1")["status"] == "drift"  # persists until acknowledged
    monitor.accept_baseline("fakedrift", "fake-1")
    assert monitor.check_engine("fakedrift", "fake-1")["status"] == "ok"


def test_api_smoke():
    from confiance.api.app import app

    with TestClient(app) as c:
        assert set(c.get("/api/engines").json()) >= {"claude", "openai", "gemini"}
        p = c.post("/api/projects", json={"name": "Acme", "domain": "acme.test", "engines": [{"name": "offline"}],
                                          "brief": {"target_questions": [{"id": "q1", "text": "who fixes pipes"}]}}).json()
        assert p["brief_version"] == 1
        assert c.post("/api/projects", json={"name": "x", "domain": "x", "engines": [{"name": "nope"}]}).status_code == 400
        c.post(f"/api/projects/{p['id']}/briefs", json={"data": {"goals": "more leads"}, "note": "v2"})
        assert [b["version"] for b in c.get(f"/api/projects/{p['id']}/briefs").json()] == [2, 1]
        assert c.get(f"/api/projects/{p['id']}/briefs/1").json()["data"]["target_questions"][0]["id"] == "q1"  # v1 preserved
        pages = c.post(f"/api/projects/{p['id']}/pages", json={"html": {"https://acme.test/": "<html><body>hi</body></html>"}}).json()
        assert len(c.get(f"/api/pages/{pages[0]['id']}/versions").json()) == 1
        assert c.get("/api/audit/verify").json()["ok"] is True
        assert c.get("/api/usage").json()["total_usd"] == 0
