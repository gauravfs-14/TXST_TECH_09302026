import gzip
import json

from confiance.discovery import audit as audit_mod, products
from confiance.discovery.pages import analyze_page
from confiance.discovery.site import can_fetch, choose_pages, classify_url, discover, parse_llms, parse_robots, parse_sitemap

ROBOTS = """
User-agent: *
Disallow: /admin/
Allow: /admin/public/

User-agent: GPTBot
Disallow: /

User-agent: PerplexityBot
User-agent: OAI-SearchBot
Disallow: /private/

Sitemap: https://shop.test/sitemap_index.xml
"""


def test_robots_rules_longest_match_and_named_agents():
    r = parse_robots(ROBOTS)
    assert r["sitemaps"] == ["https://shop.test/sitemap_index.xml"]
    assert can_fetch(r, "Googlebot", "/") and not can_fetch(r, "Googlebot", "/admin/x")
    assert can_fetch(r, "Googlebot", "/admin/public/a")  # the longer Allow beats the shorter Disallow
    assert not can_fetch(r, "GPTBot", "/") and not can_fetch(r, "GPTBot", "/anything")
    assert can_fetch(r, "PerplexityBot", "/") and not can_fetch(r, "OAI-SearchBot", "/private/x")  # grouped user-agents share rules


def test_sitemap_parsing_index_and_urlset():
    idx = parse_sitemap("<sitemapindex><sitemap><loc>https://a.test/s1.xml</loc></sitemap><sitemap><loc>https://a.test/s2.xml</loc></sitemap></sitemapindex>")
    assert idx["index"] == ["https://a.test/s1.xml", "https://a.test/s2.xml"] and idx["urls"] == []
    us = parse_sitemap("<urlset><url><loc>https://a.test/x</loc><lastmod>2026-01-02</lastmod></url><url><loc>https://a.test/y</loc></url></urlset>")
    assert us["urls"] == [{"url": "https://a.test/x", "lastmod": "2026-01-02"}, {"url": "https://a.test/y", "lastmod": None}]


def test_llms_txt_parsing():
    r = parse_llms("# Shop\n> We sell bikes.\n\n## Products\n- [Road bike](https://shop.test/p/road): fast\n- [Kids bike](/p/kids)\n\n## About\n- [Story](https://shop.test/about)\n")
    assert r["title"] == "Shop" and r["summary"] == "We sell bikes." and r["links"] == 3
    assert r["sections"][0]["links"][0] == {"title": "Road bike", "url": "https://shop.test/p/road", "desc": "fast"}


def test_url_classification():
    c = classify_url
    assert [c(u) for u in ["https://x.test/", "https://x.test/about-us", "https://x.test/products/road-bike", "https://x.test/collections/bikes",
                            "https://x.test/blog/how-to-fit", "https://x.test/2026/03/post", "https://x.test/faq", "https://x.test/products", "https://x.test/zzz"]] == \
           ["home", "about", "product", "category", "blog", "blog", "faq", "category", "other"]


def site(files: dict):
    def fetch(url):
        if url in files:
            body = files[url]
            return 200, body if isinstance(body, bytes) else body.encode(), {}
        return 404, b"", {}
    return fetch


SHOP = {
    "https://shop.test/robots.txt": ROBOTS,
    "https://shop.test/sitemap_index.xml": "<sitemapindex><sitemap><loc>https://shop.test/sm-products.xml</loc></sitemap><sitemap><loc>https://shop.test/sm-blog.xml.gz</loc></sitemap></sitemapindex>",
    "https://shop.test/sm-products.xml": "<urlset>" + "".join(f"<url><loc>https://shop.test/products/bike-{i}</loc></url>" for i in range(30)) + "<url><loc>https://shop.test/collections/bikes</loc></url></urlset>",
    "https://shop.test/sm-blog.xml.gz": gzip.compress(b"<urlset><url><loc>https://shop.test/blog/how-to-fit-a-bike</loc></url><url><loc>https://shop.test/about</loc></url></urlset>"),
    "https://shop.test/llms.txt": "# Shop\n> Bikes.\n\n## Key\n- [Guide](https://shop.test/guides/buying)\n",
}


def test_discovery_follows_robots_to_a_sitemap_index_with_gz_children_and_llms_links():
    d = discover("shop.test", fetch=site(SHOP))
    assert d.robots["exists"] and d.robots["ai_bots"]["GPTBot"]["allowed"] is False and d.robots["ai_bots"]["ClaudeBot"]["allowed"] is True
    assert len(d.urls) == 30 + 1 + 2 + 1  # products + category + blog/about (gz) + the page llms.txt names
    assert d.llms["exists"] and d.llms["links"] == 1 and not d.llms_full["exists"]
    assert {u["type"] for u in d.urls} >= {"product", "category", "blog", "about"}
    assert any(u.get("from") == "llms.txt" for u in d.urls)
    pick = choose_pages(d, limit=12)
    assert pick[0] == "https://shop.test/" and len(pick) == 12
    types = {classify_url(u) for u in pick}
    assert {"home", "about", "category", "blog", "product"} <= types  # a spread across page types, not 12 products
    assert sum("/products/" in u for u in pick) >= 4
    small = choose_pages(d, limit=6)
    assert {"home", "product"} <= {classify_url(u) for u in small} and sum("/products/" in u for u in small) <= 4  # quotas hold when space is tight


def test_discovery_of_a_bare_site_reports_absences_instead_of_failing():
    d = discover("bare.test", fetch=site({}))
    assert d.robots["exists"] is False and d.urls == [] and d.llms["exists"] is False
    assert all(s["status"] == 404 for s in d.sitemaps)


def test_a_soft_404_html_page_is_not_mistaken_for_llms_txt():
    d = discover("soft.test", fetch=site({"https://soft.test/llms.txt": "<!DOCTYPE html><html>Not found</html>"}))
    assert d.llms["exists"] is False


HOME = """<html lang="en"><head><title>Acme Bikes - Road and kids bikes</title><meta name="description" content="Bikes for everyone.">
<meta name="viewport" content="width=device-width"><link rel="canonical" href="https://shop.test/">
<script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"Organization","name":"Acme"},{"@type":"WebSite","url":"https://shop.test"}]}</script></head>
<body><h1>Acme Bikes</h1><a href="/products/road">Road</a><a href="/blog/how-to-fit">Fit</a><p>""" + "word " * 300 + "</p></body></html>"
PRODUCT_OK = """<html><head><title>Road Bike 3000 | Acme</title><meta name="description" content="Fast road bike.">
<script type="application/ld+json">{"@type":"Product","name":"Road Bike 3000","sku":"RB-3000","brand":{"@type":"Brand","name":"Acme"},"category":"Road bikes","offers":{"@type":"Offer","price":"1299","priceCurrency":"USD"},"aggregateRating":{"@type":"AggregateRating","ratingValue":"4.8"}}</script>
</head><body><h1>Road Bike 3000</h1><p>""" + "spec " * 300 + "</p></body></html>"
PRODUCT_BARE = "<html><head><title>Kids Bike</title></head><body><h1>Kids Bike</h1><img src='a.png'><img src='b.png'><p>Short.</p></body></html>"


def test_page_analysis_reads_metadata_schema_and_products():
    p = analyze_page("https://shop.test/", HOME)
    assert p["type"] == "home" and p["title"].startswith("Acme") and p["canonical"] and p["viewport"] and p["lang"] == "en"
    assert p["schema_types"] == ["organization", "website"] and p["words"] > 250 and "https://shop.test/products/road" in p["internal_links"]
    q = analyze_page("https://shop.test/products/road-bike-3000", PRODUCT_OK)
    assert q["type"] == "product" and q["products"][0] == {**q["products"][0], "name": "Road Bike 3000", "sku": "RB-3000", "brand": "Acme", "price": "1299 USD", "has_offers": True, "has_rating": True}
    z = analyze_page("https://shop.test/whatever", PRODUCT_OK)
    assert z["type"] == "product"  # the page's own markup overrides the URL guess


def test_audit_finds_the_problems_and_explains_them():
    d = discover("shop.test", fetch=site({**SHOP, "https://shop.test/llms.txt": ""})).to_dict()
    pages = [analyze_page("https://shop.test/", HOME), analyze_page("https://shop.test/products/road-bike-3000", PRODUCT_OK), analyze_page("https://shop.test/products/kids-bike", PRODUCT_BARE)]
    a = audit_mod.audit(d, pages, indexed={"checked": True, "results": 0})
    ids = {f["id"]: f for f in a["findings"]}
    assert "llms-missing" in ids and ids["llms-missing"]["severity"] == "medium"
    assert "robots-blocks-ai-training" in ids and "robots-blocks-ai-search" not in ids  # GPTBot is training-only; Perplexity/OAI-Search are allowed
    assert ids["schema-product-missing"]["severity"] == "high" and ids["schema-product-missing"]["urls"] == ["https://shop.test/products/kids-bike"]
    assert "not-indexed" in ids and "meta-missing" in ids and "thin" in ids
    assert all(f["fix"] and f["detail"] for f in a["findings"])
    assert a["findings"][0]["severity"] == "high" and 0 <= a["score"] < 100  # worst first
    clean = audit_mod.audit(discover("shop.test", fetch=site(SHOP)).to_dict(), [analyze_page("https://shop.test/", HOME)])
    assert "robots-blocks-ai-search" not in {f["id"] for f in clean["findings"]}


def test_blocking_ai_search_bots_is_flagged_as_high():
    r = "User-agent: OAI-SearchBot\nDisallow: /\nUser-agent: PerplexityBot\nDisallow: /\n"
    d = discover("x.test", fetch=site({"https://x.test/robots.txt": r})).to_dict()
    f = {x["id"]: x for x in audit_mod.audit(d, [])["findings"]}
    assert f["robots-blocks-ai-search"]["severity"] == "high" and set(f["robots-blocks-ai-search"]["evidence"]) == {"OAI-SearchBot", "PerplexityBot"}


def test_product_detection_prefers_structured_data_then_page_then_sitemap():
    pages = [analyze_page("https://shop.test/products/road-bike-3000", PRODUCT_OK), analyze_page("https://shop.test/products/kids-bike", PRODUCT_BARE)]
    sm = [{"url": "https://shop.test/products/bike-1"}, {"url": "https://shop.test/products/road-bike-3000"}, {"url": "https://shop.test/blog/x"}]
    found = products.detect(pages, None, sm)
    assert [(p["name"], p["confidence"]) for p in found] == [("Road Bike 3000", "high"), ("Kids Bike", "medium"), ("Bike 1", "low")]
    assert found[0]["sku"] == "RB-3000" and found[0]["price"] == "1299 USD"
