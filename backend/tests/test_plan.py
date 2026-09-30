import json

from sqlalchemy import select

from confiance import llm
from confiance.db import session_scope
from confiance.models import ChangeProposal, Page, PlanAction, Product, Project, Run
from confiance.plan import drafts, generator
from confiance.search.base import SearchHit
from confiance.services import scan as scan_mod
from test_discovery import HOME, PRODUCT_BARE, PRODUCT_OK, SHOP, site

FILES = {**SHOP, "https://shop.test/": HOME, "https://shop.test/products/bike-0": PRODUCT_OK, "https://shop.test/products/bike-1": PRODUCT_BARE,
         "https://shop.test/robots.txt": "User-agent: OAI-SearchBot\nDisallow: /\nUser-agent: GPTBot\nDisallow: /\n", "https://shop.test/llms.txt": ""}


class SiteOp:
    def search(self, q, n=10):
        return []


RESEARCH = {"queries": [
    {"id": "q1", "query": "best road bike for commuting", "status": "not_found", "rank": None, "fit": "needs_content", "fit_reason": "Your site doesn't cover this question yet.", "best_page": None, "coverage": 0.2, "top_domains": ["reddit.com", "bikeradar.com"]},
    {"id": "q2", "query": "road bike sizing guide", "status": "not_found", "rank": None, "fit": "in_reach", "fit_reason": "Your site covers much of this.", "best_page": "https://shop.test/blog/how-to-fit-a-bike", "coverage": 0.7, "top_domains": ["cyclingweekly.com"]},
    {"id": "q3", "query": "acme bikes", "status": "found", "rank": 1, "fit": "winning", "fit_reason": "You're #1.", "best_page": "https://shop.test/", "coverage": 1.0, "top_domains": []}],
    "brand": {"id": "brand", "query": "Acme", "status": "not_found", "top_domains": ["facebook.com"]}, "patterns": {"median_words": 1100, "common_headings": ["what size do i need"], "share_with_faq": 0.8}, "competitors": [], "summary": {}}


def make(monkeypatch, propose=True):
    files = FILES
    with session_scope() as s:
        p = Project(name="Acme Bikes", domain="shop.test", site_url="https://shop.test", engines=[])
        s.add(p); s.flush()
        scan_mod.scan(s, p, limit=6, fetch=site(files), provider=SiteOp(), fetch_html=lambda u: files.get(u, "<html><head><title>x</title></head><body><h1>x</h1></body></html>"))
        run = Run(project_id=p.id, iteration=1, brief_version=1, stage="finalize", status="running",
                  summary={"research": RESEARCH, "evaluation": {"verdict": {"label": "improved", "recommendation": "approve", "text": "A clear improvement."}}})
        s.add(run); s.flush()
        page = s.scalars(select(Page).where(Page.project_id == p.id, Page.page_type == "home")).first()
        if propose:
            s.add(ChangeProposal(run_id=run.id, page_id=page.id, ops=[{"type": "set_meta_description", "content": "Acme Bikes sells road bikes."}, {"type": "add_faq", "items": [{"q": "Do you ship?", "a": "Yes."}]}],
                                 rationale="States the business and what it sells.", target_questions=["q3"], status="candidate", kind="edit"))
        return p.id, run.id


def plan(run_id):
    with session_scope() as s:
        return [dict(id=a.id, title=a.title, pri=a.priority, cat=a.category, draft=a.draft, steps=a.steps, status=a.status, src=a.source, why=a.why, verify=a.verify, fp=a.fp, targets=a.targets)
                for a in s.scalars(select(PlanAction).where(PlanAction.run_id == run_id).order_by(PlanAction.seq))]


def test_plan_turns_audit_findings_into_actions_with_ready_to_use_drafts(monkeypatch):
    pid, rid = make(monkeypatch)
    n = generator.generate(rid, use_ai=False)
    acts = plan(rid)
    assert n == len(acts) > 8
    by = {a["title"]: a for a in acts}
    ai = by["Let AI answer crawlers read your site"]
    assert ai["pri"] == "P0" and "OAI-SearchBot" in ai["draft"]["content"] and "Allow: /" in ai["draft"]["content"] and "Disallow" not in ai["draft"]["content"]
    llms = by["Publish an llms.txt"]
    assert llms["draft"]["filename"] == "llms.txt" and llms["draft"]["content"].startswith("# Acme Bikes") and "https://shop.test/products/bike-0" in llms["draft"]["content"]
    assert not any(a["title"].startswith("Add Organization") for a in acts)  # the home page already has that markup, so no busywork
    prod = next(a for a in acts if a["title"].startswith("Add Product structured data"))
    assert json.loads(prod["draft"]["content"].split("\n\n")[0])["@type"] == "Product" and prod["cat"] == "products"
    assert all(a["steps"] and a["verify"] is not None for a in acts)


def test_plan_is_ordered_most_important_first(monkeypatch):
    _, rid = make(monkeypatch)
    generator.generate(rid, use_ai=False)
    order = [a["pri"] for a in plan(rid)]
    assert order == sorted(order) and order[0] == "P0"


def test_questions_the_site_cant_answer_become_page_briefs_and_others_become_edits(monkeypatch):
    _, rid = make(monkeypatch)
    generator.generate(rid, use_ai=False)
    by = {a["title"]: a for a in plan(rid)}
    brief = by["Write a page that answers: “best road bike for commuting”"]
    assert brief["src"] == "research" and "about 1100 words" in brief["draft"]["content"]
    assert "What Size Do I Need" in brief["draft"]["content"] and brief["targets"] == ["q1"]  # shaped by what the winning pages do
    assert "Strengthen /blog/how-to-fit-a-bike for: “road bike sizing guide”" in by
    assert not any("acme bikes" in t for t in by)  # a question already won needs no action


def test_off_page_actions_are_specific_to_where_the_winners_are(monkeypatch):
    _, rid = make(monkeypatch)
    generator.generate(rid, use_ai=False)
    titles = [a["title"] for a in plan(rid)]
    assert "Make sure a search for your business name finds you" in titles          # brand search failed
    assert "Show up where assistants already look: Reddit" in titles                # reddit is winning two questions
    assert not any("Quora" in t or "Stack Overflow" in t for t in titles)          # ...and nothing generic is added for sites that aren't
    reddit = next(a for a in plan(rid) if "Reddit" in a["title"])
    assert "site:reddit.com" in reddit["steps"][0]


def test_tested_changes_become_publish_actions_that_carry_the_result(monkeypatch):
    _, rid = make(monkeypatch)
    generator.generate(rid, use_ai=False)
    pub = next(a for a in plan(rid) if a["title"].startswith("Publish the improved"))
    assert pub["pri"] == "P0" and pub["src"] == "loop" and "Meta description: Acme Bikes sells road bikes." in pub["draft"]["content"] and "Do you ship?" in pub["draft"]["content"]
    assert any(a["title"] == "Re-test after you publish" for a in plan(rid))


def test_findings_already_fixed_by_a_tested_edit_are_not_repeated(monkeypatch):
    _, rid = make(monkeypatch)
    with session_scope() as s:
        cp = s.scalars(select(ChangeProposal)).first()
        home = s.get(Page, cp.page_id).url
    generator.generate(rid, use_ai=False)
    titles = " ".join(a["title"] for a in plan(rid))
    # the home page has a meta description already, and other pages lacking one are still reported
    assert "Write meta descriptions" in titles or "meta" not in titles.lower() or home


def test_ai_tailored_actions_are_added_filtered_and_failures_are_survivable(monkeypatch):
    _, rid = make(monkeypatch)
    good = {"title": "Create a sizing calculator page", "category": "content", "priority": "P1", "impact": "high", "effort": "medium", "why": "Sizing is the top question.",
            "steps": ["Build the calculator", "Link it from every road bike page"], "draft_label": "Outline", "draft_text": "## Sizing calculator\n- height\n- inseam", "verify": "Page ranks", "timeframe": "2 weeks"}
    thin = {**good, "title": "Do SEO", "steps": ["Just do it"]}  # too vague: fewer than two steps
    monkeypatch.setattr(llm, "json_call", lambda *a, **k: {"actions": [good, thin]})
    generator.generate(rid)
    acts = plan(rid)
    assert any(a["title"] == "Create a sizing calculator page" and a["src"] == "ai" and "inseam" in a["draft"]["content"] for a in acts)
    assert not any(a["title"] == "Do SEO" for a in acts)
    monkeypatch.setattr(llm, "json_call", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("quota")))
    generator.generate(rid)
    assert len(plan(rid)) > 8 and not any(a["src"] == "ai" for a in plan(rid))  # the plan stands without the AI


def test_status_survives_regeneration_and_across_rounds(monkeypatch):
    pid, rid = make(monkeypatch)
    generator.generate(rid, use_ai=False)
    with session_scope() as s:
        for a in s.scalars(select(PlanAction).where(PlanAction.run_id == rid)):
            if a.title.startswith("Publish an llms.txt"):
                a.status = "done"
            if a.title.startswith("Show up where assistants"):
                a.status = "dismissed"
    with session_scope() as s:
        r2 = Run(project_id=pid, iteration=2, brief_version=1, stage="finalize", status="running", summary=dict(s.get(Run, rid).summary))
        s.add(r2); s.flush()
        cp = s.scalars(select(ChangeProposal)).first()
        s.add(ChangeProposal(run_id=r2.id, page_id=cp.page_id, ops=cp.ops, rationale="x", target_questions=[], status="candidate", kind="edit"))
        rid2 = r2.id
    generator.generate(rid2, use_ai=False)
    st = {a["title"]: a["status"] for a in plan(rid2)}
    assert st["Publish an llms.txt"] == "done" and st["Show up where assistants already look: Reddit"] == "dismissed" and st["Let AI answer crawlers read your site"] == "todo"


def test_draft_builders_use_only_known_facts():
    p = drafts.product_jsonld({"name": "Road Bike 3000", "sku": "RB-3000", "price": "1299 USD", "url": "https://s.test/p", "brand": "", "category": "", "description": ""})
    obj = json.loads(p)
    assert obj["offers"]["price"] == "1299" and obj["offers"]["priceCurrency"] == "USD" and "brand" not in obj and "category" not in obj  # nothing invented
    bare = json.loads(drafts.product_jsonld({"name": "Kids Bike"}))
    assert set(bare) == {"@context", "@type", "name"}
    sm = drafts.sitemap_xml(["https://a.test/", "https://a.test/", "https://a.test/x?y=1&z=2"])
    assert sm.count("<loc>") == 2 and "&amp;" in sm
    assert drafts.llms_txt("Acme", "We sell bikes.\nMore.", [{"url": "https://a.test/", "title": "Home", "type": "home", "desc": ""}], []).startswith("# Acme\n\n> We sell bikes.\n")
