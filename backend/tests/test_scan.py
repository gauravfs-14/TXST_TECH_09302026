from sqlalchemy import select

from confiance.db import session_scope
from confiance.models import Page, Product, Project
from confiance.services import scan as scan_mod
from test_discovery import HOME, PRODUCT_BARE, PRODUCT_OK, ROBOTS, SHOP, site


def test_scan_saves_an_audit_pages_types_and_detected_products():
    files = {**SHOP, "https://shop.test/": HOME, "https://shop.test/products/bike-0": PRODUCT_OK, "https://shop.test/products/bike-1": PRODUCT_BARE}
    html = lambda u: files[u].decode() if isinstance(files[u], bytes) else files[u] if u in files else (_ for _ in ()).throw(KeyError(u))
    fetch = site(files)
    with session_scope() as s:
        p = Project(name="Acme", domain="shop.test", site_url="https://shop.test", engines=[])
        s.add(p); s.flush()
        from confiance.search.base import SearchHit

        class SiteOp:  # answers the site: operator like a real search engine
            def search(self, q, n=10):
                return [SearchHit("https://shop.test/", "Acme", "bikes")] if q.startswith("site:shop.test") else []
        provider = SiteOp()
        phases = []
        r = scan_mod.scan(s, p, limit=6, fetch=fetch, provider=provider, fetch_html=lambda u: files[u] if u in files else "<html><head><title>x</title></head><body><h1>x</h1></body></html>", on_phase=phases.append)
        assert phases == ["finding_pages", "reading_pages", "auditing"]
        assert r["pages"] == 6 and r["urls_known"] > 30 and 0 <= r["score"] <= 100
        rec = scan_mod.latest(s, p.id)
        assert rec.data["discovery"]["llms"]["exists"] and rec.data["discovery"]["robots"]["exists"]
        assert rec.data["indexed"] == {"checked": True, "results": 1}
        types = {pg.page_type for pg in s.scalars(select(Page).where(Page.project_id == p.id))}
        assert "home" in types and "product" in types
        prods = list(s.scalars(select(Product).where(Product.project_id == p.id)))
        assert any(x.sku == "RB-3000" and x.price == "1299 USD" and x.source == "detected" for x in prods)
        n = len(prods)
        scan_mod.scan(s, p, limit=6, fetch=fetch, provider=provider, fetch_html=lambda u: files.get(u, "<html><body><h1>x</h1></body></html>"))
        assert len(list(s.scalars(select(Product).where(Product.project_id == p.id)))) == n  # a rescan doesn't duplicate products


def test_a_failing_search_tool_means_unknown_not_unindexed():
    class Broken:
        def search(self, q, n=10):
            raise TimeoutError()
    assert scan_mod.indexed_check("shop.test", Broken()) == {"checked": False, "results": 0}
