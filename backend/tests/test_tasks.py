from fastapi.testclient import TestClient

from confiance import activity
from confiance.api.app import app
from confiance.context import task_scope


def test_events_attribute_to_task_not_run():
    tid = activity.begin_task("t:one")
    with task_scope(tid):
        activity.emit("hello", "step")
        activity.tick()
    snap = activity.snapshot(tid)
    assert snap["known"] and [e["text"] for e in snap["events"]] == ["hello"]
    assert tid < 0  # never collides with a run id


def test_begin_task_resets():
    tid = activity.begin_task("t:two")
    with task_scope(tid):
        activity.emit("old")
    assert activity.begin_task("t:two") == tid
    assert not activity.snapshot(tid)["known"]


def test_x_task_header_and_endpoint():
    c = TestClient(app)
    r = c.get("/api/tasks/nothing-yet/live")
    assert r.status_code == 200 and r.json()["known"] is False
    c.get("/api/setup/status", headers={"X-Task": "abc"})  # header is accepted on any request
