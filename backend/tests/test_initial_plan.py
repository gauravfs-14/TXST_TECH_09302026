from sqlalchemy import select

from confiance.db import session_scope
from confiance.discovery import lighthouse
from confiance.models import PlanAction, Project
from confiance.plan import generator
from confiance.services import scan as scan_mod
from test_discovery import SHOP, HOME, PRODUCT_OK, PRODUCT_BARE, site
from test_plan import FILES, SiteOp, make

LH = {"lighthouseVersion": "12", "categories": {
    "performance": {"score": 0.42}, "accessibility": {"score": 0.8, "auditRefs": [{"id": "color-contrast", "weight": 7}]},
    "best-practices": {"score": 1, "auditRefs": []}, "seo": {"score": 0.7, "auditRefs": [{"id": "meta-description", "weight": 1}, {"id": "is-crawlable", "weight": 4}]}},
    "audits": {"largest-contentful-paint": {"numericValue": 5200, "displayValue": "5.2 s", "score": 0.1},
               "uses-optimized-images": {"title": "Efficiently encode images", "score": 0.2, "displayValue": "Potential savings of 900 KiB", "details": {"type": "opportunity", "overallSavingsMs": 1400}},
               "render-blocking": {"title": "Eliminate render-blocking resources", "score": 0.5, "details": {"type": "opportunity", "overallSavingsMs": 300}},
               "color-contrast": {"title": "Text needs more contrast", "score": 0, "scoreDisplayMode": "binary"},
               "meta-description": {"title": "Document has a meta description", "score": 0, "scoreDisplayMode": "binary"},
               "is-crawlable": {"title": "Page is not blocked from indexing", "score": 1, "scoreDisplayMode": "binary"}}}


def test_lighthouse_summary_is_short_and_actionable():
    r = lighthouse.summarize(LH, "local", "mobile", "https://x.test")
    assert r["scores"] == {"performance": 42, "accessibility": 80, "best_practices": 100, "seo": 70}
    assert [o["id"] for o in r["opportunities"]] == ["uses-optimized-images", "render-blocking"]
    assert r["failed"]["seo"] == [{"id": "meta-description", "title": "Document has a meta description", "weight": 1}]
    assert r["metrics"]["lcp"]["display"] == "5.2 s"


def test_lighthouse_failure_never_raises_and_falls_back():
    boom = lambda *a: (_ for _ in ()).throw(RuntimeError("no chrome"))
    import os
    os.environ["CONFIANCE_LIGHTHOUSE"] = "auto"
    try:
        assert lighthouse.run("https://x.test", local=boom, remote=boom)["available"] is False
        assert lighthouse.run("https://x.test", local=boom, remote=lambda *a: LH)["source"] == "pagespeed"
    finally:
        os.environ["CONFIANCE_LIGHTHOUSE"] = "off"


def test_scan_stores_lighthouse_and_the_starting_plan_uses_it(monkeypatch):
    files = FILES
    with session_scope() as s:
        p = Project(name="Acme Bikes", domain="shop.test", site_url="https://shop.test", engines=[])
        s.add(p); s.flush()
        scan_mod.scan(s, p, limit=6, fetch=site(files), provider=SiteOp(), fetch_html=lambda u: files.get(u, "<html><body><h1>x</h1></body></html>"),
                      lighthouse=lambda url: lighthouse.summarize(LH, "local", "mobile", url))
        pid = p.id
        assert scan_mod.latest(s, pid).data["lighthouse"]["scores"]["performance"] == 42
    n = generator.generate_initial(pid)
    with session_scope() as s:
        acts = generator.current(s, pid)
        assert n == len(acts) > 5 and all(a.run_id is None for a in acts)
        titles = [a.title for a in acts]
        assert "Run your first round" in titles and "Make the site faster" in titles and "Fix Lighthouse SEO issues" in titles
        assert next(a for a in acts if a.title == "Make the site faster").priority == "P0"  # under 50 is urgent
    # regenerating keeps what the person already did
    with session_scope() as s:
        next(a for a in generator.current(s, pid) if a.title == "Publish an llms.txt").status = "done"
    generator.generate_initial(pid)
    with session_scope() as s:
        assert next(a for a in generator.current(s, pid) if a.title == "Publish an llms.txt").status == "done"


def test_a_round_plan_supersedes_the_starting_plan_and_keeps_statuses(monkeypatch):
    pid, rid = make(monkeypatch)
    generator.generate_initial(pid)
    with session_scope() as s:
        next(a for a in generator.current(s, pid) if a.title == "Publish an llms.txt").status = "done"
    generator.generate(rid, use_ai=False)
    with session_scope() as s:
        cur = generator.current(s, pid)
        assert all(a.run_id == rid for a in cur)
        assert next(a for a in cur if a.title == "Publish an llms.txt").status == "done"


def test_ensure_initial_backfills_a_project_scanned_before_starting_plans_existed(monkeypatch):
    pid, rid = make(monkeypatch)
    with session_scope() as s:
        assert s.scalars(select(PlanAction)).first() is None
    generator.ensure_initial(pid)
    with session_scope() as s:
        assert len(generator.current(s, pid)) > 5
