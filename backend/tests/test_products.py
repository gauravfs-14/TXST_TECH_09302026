from sqlalchemy import select

from confiance import llm
from confiance.db import session_scope
from confiance.engines.base import EngineAnswer
from confiance.models import Product, Project
from confiance.sim import products as pm, stats
from confiance.sim.metrics import Target, score, visibility_score

P = {"id": 3, "name": "Acme Road Bike 3000", "sku": "RB-3000", "brand": "Acme", "url": "https://shop.test/products/road-bike-3000"}


def test_track_and_product_ids_from_question_ids():
    assert pm.track_of("p3.2") == "product" and pm.track_of("q1") == "brand" and pm.track_of("brand") == "brand"
    assert pm.product_id_of("p12.1") == 12 and pm.product_id_of("q1") is None


def test_default_queries_are_specific_to_the_product():
    qs = pm.default_queries(P | {"category": "Road bikes"})
    assert [q["id"] for q in qs] == ["p3.1", "p3.2", "p3.3"]
    assert "Acme Road Bike 3000" in qs[0]["text"] and "road bikes" in qs[1]["text"].lower() and "RB-3000" in qs[2]["text"]


def test_product_metrics_name_link_and_list_position():
    text = "Here are good options:\n1. **Trek Domane** - solid\n2. Road Bike 3000 from Acme - great value\n3. Giant TCR\n\nMore reading."
    m = pm.metrics(text, ["https://shop.test/products/road-bike-3000/", "https://other.test/"], P)
    assert m == {"product_mentioned": True, "product_cited": True, "product_rank": 2, "list_len": 3}  # brand prefix dropped, url with trailing slash
    n = pm.metrics("Try the Trek Domane or the Giant TCR.", ["https://shop.test/"], P)
    assert n["product_mentioned"] is False and n["product_cited"] is False and n["product_rank"] is None  # the homepage is not the product page
    assert pm.metrics("The RB-3000 is out of stock.", [], P)["product_mentioned"]  # a SKU alone counts


def test_a_product_answer_scores_on_product_terms_not_brand_terms():
    t = Target("shop.test", ["Acme"], [])
    good = EngineAnswer(text="1. Road Bike 3000 - best\n2. Other", citations=["https://shop.test/products/road-bike-3000"], queries=["q"], exposed=True)
    poor = EngineAnswer(text="1. Other\n2. Another\n3. Third\n4. Fourth", citations=["https://big.test/"], queries=["q"], exposed=True)
    mg, mp = score(good, t, product=P, page_texts=[""]), score(poor, t, product=P, page_texts=[""])
    assert mg["product_mentioned"] and mg["product_rank"] == 1 and not mp["product_mentioned"]
    assert visibility_score(mg) > visibility_score(mp) + 0.4


def test_aggregation_splits_brand_from_products_and_by_product():
    row = lambda qid, ment: {"engine": "e", "question_id": qid, "score": 1.0 if ment else 0.0, "metrics": {"answered": True, "mentioned": ment, "product_mentioned": ment}}
    agg = stats.aggregate([row("q1", True), row("q2", False), row("p3.1", True), row("p3.2", True), row("p4.1", False)])
    assert set(agg["by_track"]) == {"brand", "product"} and agg["by_track"]["product"]["n"] == 3
    assert agg["by_track"]["brand"]["mentioned_rate"] == 0.5 and set(agg["by_product"]) == {"3", "4"}
    assert agg["by_product"]["3"]["product_mentioned_rate"] == 1.0 and agg["by_product"]["4"]["product_mentioned_rate"] == 0.0


def test_generate_queries_uses_the_ai_but_never_depends_on_it(monkeypatch):
    with session_scope() as s:
        pr = Project(name="Acme", domain="shop.test", engines=[])
        s.add(pr); s.flush()
        s.add_all([Product(project_id=pr.id, name="Road Bike 3000", category="Road bikes"), Product(project_id=pr.id, name="Kids Bike")])
        s.flush()
        monkeypatch.setattr(llm, "json_call", lambda *a, **k: {"products": [{"index": 0, "use_case": "best bike for a 40 km commute", "comparison": "Road Bike 3000 vs a carbon frame"}]})
        assert pm.generate_queries(s, pr.id, "Acme") == 2
        a, b = list(s.scalars(select(Product).where(Product.project_id == pr.id).order_by(Product.id)))
        assert [q["kind"] for q in a.queries] == ["specific", "category", "use_case", "comparison"] and len(b.queries) == 2  # the AI only reached product 0
        monkeypatch.setattr(llm, "json_call", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("quota")))
        b.queries = []
        pm.generate_queries(s, pr.id, "Acme")
        assert len(b.queries) == 2  # the AI failed; the deterministic questions were still written
        sel = pm.select_queries([a, b], 3)
        assert [q["product_id"] for q in sel] == [a.id, b.id, a.id]  # spread across products first
