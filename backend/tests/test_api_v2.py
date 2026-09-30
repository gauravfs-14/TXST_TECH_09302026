from fastapi.testclient import TestClient
from sqlalchemy import select

from confiance import llm
from confiance.api.app import app
from confiance.db import session_scope
from confiance.models import PlanAction, Product, Project
from test_report import full_round

CSV = "name,sku,url,category,price\nRoad Bike 3000,RB-3000,https://shop.test/p/rb,Road bikes,1299 USD\nGravel Bike 9,GB-9,,Gravel,\nGravel Bike 9,GB-9,,,\n,,,,\n"


def client():
    return TestClient(app)


def test_audit_endpoint_reports_findings_discovery_and_history(monkeypatch):
    pid, _ = full_round(monkeypatch)
    with client() as c:
        a = c.get(f"/api/projects/{pid}/audit").json()
        assert a["scanned"] and 0 < a["score"] <= 100 and a["findings"][0]["severity"] == "high" and a["discovery"]["llms"]["exists"] is False
        assert a["page_types"] and a["history"][-1]["score"] == a["score"]
        assert c.get("/api/projects/999/audit").status_code == 404
    with session_scope() as s:
        p = Project(name="Empty", domain="e.test", engines=[])
        s.add(p); s.flush()
        eid = p.id
    with client() as c:
        assert c.get(f"/api/projects/{eid}/audit").json() == {"scanned": False, "history": []}


def test_products_can_be_added_imported_edited_and_removed(monkeypatch):
    pid, _ = full_round(monkeypatch)
    with client() as c:
        r = c.post(f"/api/projects/{pid}/products/import", json={"csv": CSV}).json()
        assert r == {"added": 1, "skipped": 3}  # RB-3000 was already detected by the scan; Gravel Bike is new; a repeat and a blank row are skipped
        assert c.post(f"/api/projects/{pid}/products/import", json={"csv": "sku,url\nA,B"}).status_code == 400
        assert c.post(f"/api/projects/{pid}/products", json={"name": "  "}).status_code == 400
        p = c.post(f"/api/projects/{pid}/products", json={"name": "Helmet X", "sku": "HX-1", "category": "Helmets"}).json()
        assert p["source"] == "manual" and p["active"]
        assert c.patch(f"/api/products/{p['id']}", json={"active": False}).json()["active"] is False
        c.patch(f"/api/products/{p['id']}", json={"name": "Helmet Y"})
        listed = c.get(f"/api/projects/{pid}/products").json()
        assert any(x["name"] == "Helmet Y" for x in listed) and listed[-1]["active"] is False  # inactive ones sort last
        assert c.delete(f"/api/products/{p['id']}").json() == {"ok": True}
        assert c.delete(f"/api/products/{p['id']}").status_code == 404


def test_product_queries_are_generated_on_demand(monkeypatch):
    pid, _ = full_round(monkeypatch)
    monkeypatch.setattr(llm, "json_call", lambda *a, **k: {"products": []})
    with client() as c:
        c.post(f"/api/projects/{pid}/products", json={"name": "Helmet X", "category": "Helmets"})
        assert c.post(f"/api/projects/{pid}/products/queries").json()["products_updated"] >= 1
        helmet = next(p for p in c.get(f"/api/projects/{pid}/products").json() if p["name"] == "Helmet X")
        assert len(helmet["queries"]) >= 2 and helmet["queries"][0]["id"].startswith(f"p{helmet['id']}.")


def test_settings_are_validated_and_clamped_before_saving(monkeypatch):
    pid, _ = full_round(monkeypatch)
    with client() as c:
        g = c.get(f"/api/projects/{pid}/settings").json()
        assert g["settings"]["max_loops"] == 3 and g["limits"]["max_loops"] == [1, 10] and g["defaults"]["patience"] == 2
        r = c.put(f"/api/projects/{pid}/settings", json={"max_loops": 500, "min_gain": 9, "track": ["products", "junk"], "unknown": 1}).json()["settings"]
        assert r["max_loops"] == 10 and r["min_gain"] == 0.5 and r["track"] == ["products"] and "unknown" not in r
        assert c.get(f"/api/projects/{pid}/settings").json()["settings"]["max_loops"] == 10  # saved
    with session_scope() as s:
        assert s.get(Project, pid).settings["max_loops"] == 10


def test_plan_status_is_tracked_and_validated(monkeypatch):
    pid, rid = full_round(monkeypatch)
    with client() as c:
        plan = c.get(f"/api/projects/{pid}/plan").json()
        assert plan["run_id"] == rid and plan["actions"][0]["priority"] == "P0" and plan["actions"][0]["status"] == "todo"
        aid = plan["actions"][0]["id"]
        assert c.patch(f"/api/plan/{aid}", json={"status": "done"}).json() == {"ok": True}
        assert c.patch(f"/api/plan/{aid}", json={"status": "finished"}).status_code == 400
        assert c.get(f"/api/runs/{rid}/plan").json()[0]["status"] == "done"
        ov = c.get(f"/api/projects/{pid}/overview").json()
        assert ov["plan_done"] == 1 and ov["plan_total"] == len(plan["actions"])


def test_report_endpoints_serve_json_html_and_markdown(monkeypatch):
    _, rid = full_round(monkeypatch)
    with client() as c:
        assert c.get(f"/api/runs/{rid}/report").json()["meta"]["business"] == "Acme Bikes"
        h = c.get(f"/api/runs/{rid}/report.html")
        assert h.headers["content-type"].startswith("text/html") and "Improvement plan" in h.text and "attachment" not in h.headers.get("content-disposition", "")
        assert "attachment" in c.get(f"/api/runs/{rid}/report.html?download=1").headers["content-disposition"]
        md = c.get(f"/api/runs/{rid}/report.md")
        assert md.headers["content-type"].startswith("text/markdown") and md.text.startswith("# Optimization report")
        assert c.get("/api/runs/999/report").status_code == 404 and c.get("/api/runs/999/report.html").status_code == 404


def test_loops_endpoint_and_full_untruncated_answers(monkeypatch):
    _, rid = full_round(monkeypatch)
    with client() as c:
        lp = c.get(f"/api/runs/{rid}/loops").json()
        assert lp["best_loop"] == 1 and lp["loops"][0]["verdict"]["label"] == "improved" and lp["loops"][0]["funnel_now"]["used_page"] == 0.5 and lp["config"]["max_loops"] == 3
        s = c.get(f"/api/runs/{rid}/summary").json()
        assert s["verdict"]["label"] == "improved" and s["best_loop"] == 1
    from confiance.models import SimulationBatch, SimulationResult
    long_answer = "Sentence one. " * 400  # ~5,600 characters: the old screen clipped answers at 900
    with session_scope() as st:
        b = st.scalars(select(SimulationBatch).where(SimulationBatch.run_id == rid, SimulationBatch.arm == "candidate")).one()
        b.aggregate = {**b.aggregate, "by_question": {"q3": {"n": 1, "mentioned_rate": 1.0}}}
        base = st.scalars(select(SimulationBatch).where(SimulationBatch.run_id == rid, SimulationBatch.arm == "baseline")).one()
        base.aggregate = {**base.aggregate, "by_question": {"q3": {"n": 1, "mentioned_rate": 0.0}}}
        r = st.scalars(select(SimulationResult).where(SimulationResult.batch_id == b.id)).first()
        r.answer = long_answer
    with client() as c:
        q = next(x for x in c.get(f"/api/runs/{rid}/summary").json()["questions"] if x["id"] == "q3")
        assert q["after_answer"] == long_answer and len(q["after_answer"]) > 5000


def test_overview_summarises_everything_the_dashboard_needs(monkeypatch):
    pid, rid = full_round(monkeypatch)
    with client() as c:
        ov = c.get(f"/api/projects/{pid}/overview").json()
        assert ov["business"] == "Acme Bikes" and ov["site_score"] and ov["findability"] is not None
        assert ov["latest_round"]["id"] == rid and ov["last_finished_round"]["verdict"]["label"] == "improved"
        assert ov["plan_open"]["P0"] >= 1 and len(ov["top_actions"]) == 4 and ov["pages"] >= 1 and ov["products"]["active"] >= 1
        assert isinstance(ov["history"], list)
    with session_scope() as s:
        p = Project(name="Fresh", domain="f.test", engines=[])
        s.add(p); s.flush()
        fid = p.id
    with client() as c:
        fresh = c.get(f"/api/projects/{fid}/overview").json()
        assert fresh["site_score"] is None and fresh["history"] == [] and fresh["latest_round"] is None and fresh["top_actions"] == []  # a new project doesn't crash the dashboard


def test_start_a_round_with_loop_limits_from_the_api(monkeypatch):
    pid, _ = full_round(monkeypatch)
    with session_scope() as s:
        s.get(Project, pid).current_brief_version = 1
        from confiance.brief import BriefData, TargetQuestion
        from confiance import brief as briefs
        briefs.create_version(s, s.get(Project, pid), BriefData(target_questions=[TargetQuestion(id="q1", text="who sells bikes")]))
    monkeypatch.setattr("confiance.api.app._advance_bg", lambda rid: None)  # don't actually run it here
    with client() as c:
        r = c.post(f"/api/projects/{pid}/runs", json={"intensity": "standard", "overrides": {"max_loops": 2, "min_gain": 0.05}})
        assert r.status_code == 200
        from confiance.models import Run
        with session_scope() as s:
            cfg = s.get(Run, r.json()["run_id"]).summary["config"]
        assert cfg["max_loops"] == 2 and cfg["min_gain"] == 0.05 and cfg["plan"] == "standard"


def test_changing_the_website_sets_old_pages_and_detected_products_aside():
    from confiance.models import Page

    with client() as c:
        pid = c.post("/api/simple/projects", json={"business_name": "Shop", "website": "old-shop.com"}).json()["id"]
        with session_scope() as s:
            s.add(Page(project_id=pid, url="https://old-shop.com/a"))
            s.add(Product(project_id=pid, name="Detected", source="detected"))
            s.add(Product(project_id=pid, name="Mine", source="manual"))
        assert c.patch(f"/api/projects/{pid}", json={"website": "www.new-shop.com/"}).json()["site_changed"] is True
        assert c.get(f"/api/projects/{pid}").json()["site_url"] == "https://www.new-shop.com"
        assert [p["name"] for p in c.get(f"/api/projects/{pid}/products").json()] == ["Mine"]
        with session_scope() as s:
            assert s.scalars(select(Page).where(Page.project_id == pid)).one().kind == "archived"
        assert c.patch(f"/api/projects/{pid}", json={"website": "nope"}).status_code == 400
        assert c.patch(f"/api/projects/{pid}", json={"website": "https://www.new-shop.com"}).json()["site_changed"] is False


def test_editing_only_the_questions_keeps_the_rules():
    with client() as c:
        pid = c.post("/api/simple/projects", json={"business_name": "Shop", "website": "shop-rules.com"}).json()["id"]
        c.put(f"/api/projects/{pid}/simple-brief", json={"questions": ["one?"], "never_say": ["cheapest"], "never_change": ["Free returns"]})
        assert c.put(f"/api/projects/{pid}/questions", json={"questions": ["a?", " ", "b?"]}).status_code == 200
        b = c.get(f"/api/projects/{pid}/simple-brief").json()
        assert b["questions"] == ["a?", "b?"] and b["never_say"] == ["cheapest"] and b["never_change"] == ["Free returns"]
        assert c.put(f"/api/projects/{pid}/questions", json={"questions": [" "]}).status_code == 400
