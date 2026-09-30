"""Technical audit: what stops a site being found, crawled and understood by search engines and AI assistants.

Every finding names the evidence and what to do about it, and carries a severity so the plan can be ordered.
The checks are deterministic (no AI involved), so the same site gives the same audit."""

from collections import Counter
from urllib.parse import urlsplit

SEVERITY_COST = {"high": 12, "medium": 6, "low": 2, "info": 0}


def _f(fid: str, severity: str, area: str, title: str, detail: str, fix: str, evidence: list | None = None, urls: list | None = None) -> dict:
    return {"id": fid, "severity": severity, "area": area, "title": title, "detail": detail, "fix": fix,
            "evidence": evidence or [], "urls": (urls or [])[:12]}


def audit(discovery: dict, pages: list[dict], indexed: dict | None = None) -> dict:
    """discovery: Discovery.to_dict(); pages: analyze_page() results; indexed: {"checked": bool, "results": int}"""
    out: list[dict] = []
    origin = discovery.get("origin", "")
    n = max(len(pages), 1)

    # --- crawlability
    robots = discovery.get("robots", {})
    if not robots.get("exists"):
        out.append(_f("robots-missing", "low", "crawl", "No robots.txt", "Crawlers find no instructions, so every bot uses its own defaults.",
                      "Add a robots.txt that allows search and AI-answer crawlers and points to your sitemap."))
    elif robots.get("blocks_all"):
        out.append(_f("robots-blocks-all", "high", "crawl", "robots.txt blocks all crawlers", "Search engines and AI assistants are told to stay away from the whole site.",
                      "Remove the blanket Disallow: / rule (or restrict it to private areas)."))
    else:
        bots = robots.get("ai_bots", {})
        blocked = {b: v for b, v in bots.items() if not v["allowed"]}
        answer_blocked = sorted(b for b, v in blocked.items() if v["purpose"] in ("search", "user"))
        train_blocked = sorted(b for b, v in blocked.items() if v["purpose"] == "training")
        if answer_blocked:
            out.append(_f("robots-blocks-ai-search", "high", "geo", "AI answer crawlers are blocked",
                          f"robots.txt blocks {', '.join(answer_blocked)}. These bots fetch pages to answer people's questions, so blocked pages can't be cited.",
                          "Allow these bots in robots.txt (blocking training-only bots is a separate choice).", answer_blocked))
        if train_blocked:
            out.append(_f("robots-blocks-ai-training", "info", "geo", "AI training crawlers are blocked",
                          f"robots.txt blocks {', '.join(train_blocked)}. This keeps your content out of model training and doesn't stop citations by search-based assistants.",
                          "No action needed if intentional.", train_blocked))

    sm_ok = [s for s in discovery.get("sitemaps", []) if s.get("status") == 200 and (s.get("urls") or s.get("children"))]
    if not sm_ok:
        out.append(_f("sitemap-missing", "high", "indexing", "No working sitemap found", "Without a sitemap, crawlers only find pages by following links, and new or deep pages are found slowly or never.",
                      "Publish an XML sitemap and reference it from robots.txt."))
    else:
        if robots.get("exists") and not robots.get("sitemaps"):
            out.append(_f("sitemap-not-in-robots", "low", "indexing", "Sitemap isn't listed in robots.txt", "Crawlers can still find /sitemap.xml, but listing it is the standard way to advertise it.",
                          "Add a 'Sitemap: <url>' line to robots.txt."))
        urls = discovery.get("url_count", 0)
        if urls and pages and urls < 3:
            out.append(_f("sitemap-tiny", "medium", "indexing", f"Sitemap lists only {urls} URL(s)", "Most of your pages are missing from the sitemap.", "Regenerate the sitemap so it includes every public page."))

    # --- AI-specific
    llms = discovery.get("llms", {})
    if not llms.get("exists"):
        out.append(_f("llms-missing", "medium", "geo", "No llms.txt", "llms.txt is an emerging convention that gives AI assistants a curated map of your most important pages. It is not guaranteed to be used, but it is cheap and harmless.",
                      "Publish /llms.txt with a short summary and links to your key pages (a draft is generated for you)."))
    elif not llms.get("links"):
        out.append(_f("llms-empty", "low", "geo", "llms.txt has no links", "The file exists but doesn't point assistants to any pages.", "List your key pages as markdown links under H2 sections."))

    # --- indexation (does a site: search return anything?)
    if indexed and indexed.get("checked"):
        if indexed["results"] == 0:
            out.append(_f("not-indexed", "high", "indexing", "The search tool shows no pages from your site", "A site: search returned nothing, so search-based assistants are unlikely to know your pages exist.",
                          "Submit the sitemap to Google Search Console and Bing Webmaster Tools, and earn a few links from indexed sites.", [f"site:{urlsplit(origin).netloc}"]))

    # --- transport
    if origin.startswith("http://"):
        out.append(_f("no-https", "medium", "crawl", "Site isn't served over HTTPS", "Browsers warn users and search engines prefer secure pages.", "Install a certificate and redirect http to https."))

    # --- per-page
    def bad(pred) -> list[str]:
        return [p["url"] for p in pages if pred(p)]

    checks = [
        ("noindex", "high", "indexing", "Pages tell search engines not to index them", lambda p: p["noindex"], "Remove the noindex directive from pages you want found."),
        ("title-missing", "high", "content", "Pages without a title", lambda p: not p["title"], "Give every page a unique, descriptive <title>."),
        ("title-length", "low", "content", "Titles too long or too short", lambda p: p["title"] and not 15 <= len(p["title"]) <= 65, "Aim for 30 to 60 characters that state the page's topic."),
        ("meta-missing", "medium", "content", "Pages without a meta description", lambda p: not p["meta_description"], "Write a 120 to 160 character summary that answers what the page is about."),
        ("h1-missing", "medium", "content", "Pages without an H1 heading", lambda p: not p["h1"], "Add one clear H1 that matches the page's main topic."),
        ("h1-multiple", "low", "content", "Pages with several H1 headings", lambda p: len(p["h1"]) > 1, "Keep a single H1 and use H2/H3 for sections."),
        ("canonical-missing", "low", "indexing", "Pages without a canonical link", lambda p: not p["canonical"], "Add <link rel=\"canonical\"> so duplicates don't split ranking."),
        ("thin", "medium", "content", "Thin pages (under 250 words)", lambda p: p["words"] < 250 and p["type"] not in ("contact",), "Add substantive, specific content that answers the questions people ask."),
        ("no-alt", "low", "content", "Images without alt text", lambda p: p["images"] and p["images_no_alt"] / p["images"] > 0.5, "Describe images with alt text; assistants and search read it."),
        ("no-viewport", "low", "crawl", "Pages missing a mobile viewport", lambda p: not p["viewport"], "Add <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">."),
    ]
    for fid, sev, area, title, pred, fix in checks:
        hit = bad(pred)
        if hit:
            share = len(hit) / n
            severity = sev if share >= 0.3 or sev == "high" else ("low" if sev != "low" else "low")
            out.append(_f(fid, severity, area, f"{title} ({len(hit)} of {len(pages)})", f"Found on {len(hit)} of the {len(pages)} pages checked.", fix, urls=hit))

    # --- structured data
    home = next((p for p in pages if p["type"] == "home"), None)
    if home is not None:
        want = {"organization", "localbusiness", "website"} & set(home["schema_types"])
        if not want:
            out.append(_f("schema-org-missing", "medium", "structured_data", "Home page has no Organization/WebSite structured data",
                          "Structured data tells search engines and AI assistants who you are, so they can attribute answers correctly.",
                          "Add Organization (or LocalBusiness) and WebSite JSON-LD to the home page (a draft is generated).", urls=[home["url"]]))
    prods = [p for p in pages if p["type"] == "product"]
    no_schema = [p["url"] for p in prods if "product" not in {t for t in p["schema_types"]}]
    if no_schema:
        out.append(_f("schema-product-missing", "high", "products", f"Product pages without Product structured data ({len(no_schema)} of {len(prods)})",
                      "Without Product markup, price, availability and specs are hard for search and shopping assistants to read.",
                      "Add Product JSON-LD (name, sku, brand, offers) to each product page (drafts are generated).", urls=no_schema))
    no_offer = [p["url"] for p in prods for pr in p["products"] if not pr["has_offers"]]
    if no_offer:
        out.append(_f("schema-offer-missing", "medium", "products", "Products without price/availability (Offer) data", "Shopping-oriented answers lean on price and stock.", "Add an Offer with price, currency and availability.", urls=no_offer))
    blogs = [p for p in pages if p["type"] == "blog"]
    no_article = [p["url"] for p in blogs if not ({"article", "blogposting", "newsarticle"} & set(p["schema_types"]))]
    if no_article:
        out.append(_f("schema-article-missing", "low", "structured_data", f"Articles without Article structured data ({len(no_article)} of {len(blogs)})", "Article markup states author and dates, which supports trust.", "Add Article/BlogPosting JSON-LD.", urls=no_article))
    faqs = [p for p in pages if p["type"] == "faq" or any("faq" in h.lower() for h in p["h2"])]
    no_faq = [p["url"] for p in faqs if "faqpage" not in set(p["schema_types"])]
    if no_faq:
        out.append(_f("schema-faq-missing", "low", "structured_data", "FAQ content without FAQPage markup", "Question-and-answer content is easiest for assistants to reuse when it is marked up.", "Add FAQPage JSON-LD.", urls=no_faq))

    # --- internal linking
    linked = Counter(l.rstrip("/") for p in pages for l in p["internal_links"])
    orphans = [p["url"] for p in pages if p["type"] != "home" and linked[p["url"].rstrip("/")] == 0]
    if orphans and len(pages) > 3:
        out.append(_f("orphans", "medium", "indexing", f"Pages nothing links to ({len(orphans)})", "Pages with no internal links pointing at them are hard for crawlers to reach.", "Link to them from the home page, category pages or related articles.", urls=orphans))

    score = max(0, 100 - sum(SEVERITY_COST[f["severity"]] for f in out))
    counts = Counter(f["severity"] for f in out)
    order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    out.sort(key=lambda f: order[f["severity"]])
    types = Counter(p["type"] for p in pages)
    return {"score": score, "findings": out, "counts": dict(counts), "pages_checked": len(pages), "page_types": dict(types),
            "schema_coverage": dict(Counter(t for p in pages for t in p["schema_types"]))}
