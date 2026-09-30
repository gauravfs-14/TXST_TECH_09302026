"""Ready-to-use drafts for the improvement plan: files and snippets a person can paste or hand to a developer.

Everything here is built only from facts already known about the site (nothing is invented), so a draft is either
complete and true or it leaves a field out."""

import json
from urllib.parse import urlsplit
from xml.sax.saxutils import escape

ANSWER_BOTS = ["OAI-SearchBot", "ChatGPT-User", "PerplexityBot", "Claude-SearchBot", "Claude-User", "Perplexity-User"]


def robots_allow(bots: list[str], sitemap: str | None = None) -> str:
    out = ["# Let AI answer and search crawlers read the site (they fetch pages to answer people's questions)"]
    for b in bots or ANSWER_BOTS:
        out += [f"User-agent: {b}", "Allow: /", ""]
    if sitemap:
        out.append(f"Sitemap: {sitemap}")
    return "\n".join(out).rstrip() + "\n"


def robots_open(sitemap: str | None = None) -> str:
    return "User-agent: *\nAllow: /\n" + (f"\nSitemap: {sitemap}\n" if sitemap else "")


def sitemap_xml(urls: list[str]) -> str:
    body = "".join(f"  <url><loc>{escape(u)}</loc></url>\n" for u in dict.fromkeys(urls))
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{body}</urlset>\n'


def llms_txt(name: str, summary: str, pages: list[dict], products: list[dict]) -> str:
    """pages: [{"url","title","type","desc"}]. Follows the llms.txt convention: H1, blockquote summary, H2 link lists."""
    lines = [f"# {name}", ""]
    if summary:
        lines += [f"> {summary.strip().splitlines()[0][:300]}", ""]

    def section(title: str, items: list[tuple[str, str, str]]) -> None:
        if items:
            lines.append(f"## {title}")
            lines.extend(f"- [{t}]({u})" + (f": {d[:140]}" if d else "") for t, u, d in items[:10])
            lines.append("")

    by = lambda *types: [(p["title"] or urlsplit(p["url"]).path.strip("/") or "Home", p["url"], p.get("desc", "")) for p in pages if p["type"] in types]
    section("Key pages", by("home", "about", "contact", "faq"))
    section("Products", [(p["name"], p["url"], p.get("description", "")) for p in products if p.get("url")] or by("product", "category"))
    section("Guides and articles", by("blog"))
    return "\n".join(lines).rstrip() + "\n"


def _clean(d: dict) -> dict:
    return {k: v for k, v in d.items() if v not in ("", None, [], {})}


def org_jsonld(name: str, url: str, description: str = "") -> str:
    graph = [_clean({"@type": "Organization", "@id": url.rstrip("/") + "/#organization", "name": name, "url": url, "description": description[:300]}),
             {"@type": "WebSite", "@id": url.rstrip("/") + "/#website", "url": url, "name": name, "publisher": {"@id": url.rstrip("/") + "/#organization"}}]
    return json.dumps({"@context": "https://schema.org", "@graph": graph}, indent=2, ensure_ascii=False)


def product_jsonld(p: dict) -> str:
    price, cur = "", ""
    if p.get("price"):
        parts = str(p["price"]).split()
        price, cur = parts[0], (parts[1] if len(parts) > 1 else "")
    offer = _clean({"@type": "Offer", "price": price, "priceCurrency": cur, "url": p.get("url"), "availability": "https://schema.org/InStock" if price else ""})
    obj = _clean({"@context": "https://schema.org", "@type": "Product", "name": p["name"], "sku": p.get("sku"), "description": (p.get("description") or "")[:300],
                  "category": p.get("category"), "brand": {"@type": "Brand", "name": p["brand"]} if p.get("brand") else "", "url": p.get("url"), "offers": offer if len(offer) > 1 else ""})
    return json.dumps(obj, indent=2, ensure_ascii=False)


def faq_jsonld(items: list[tuple[str, str]]) -> str:
    return json.dumps({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in items]}, indent=2, ensure_ascii=False)


def page_outline(question: str, brand: str, patterns: dict, facts: list[str]) -> str:
    """A markdown brief for a page that answers one question, shaped by what the winning pages do."""
    words = min(max(patterns.get("median_words", 0), 500), 1400) if patterns else 800
    common = patterns.get("common_headings", []) if patterns else []
    out = [f"# Page brief: {question}", "", f"**Goal:** be the page an assistant reads to answer \"{question}\".", f"**Length:** about {words} words.", "",
           "## Structure", f"1. H1: the question, plainly worded (e.g. \"{question.rstrip('?').strip().capitalize()}\")",
           f"2. A 2 to 3 sentence direct answer that names {brand} and states a concrete fact"]
    n = 3
    for h in common[:4]:
        out.append(f"{n}. H2 like \"{h.title()}\" (winning pages include this)")
        n += 1
    out += [f"{n}. H2 \"Frequently asked questions\" with 4 to 6 real questions and short answers", f"{n + 1}. Links to your related pages, and one clear next step", "",
            "## Facts you can use (from your own site)"]
    out += [f"- {f}" for f in facts[:6]] or ["- (Add specific facts: what you offer, for whom, where, since when.)"]
    out += ["", "## Markup", "Add Article or FAQPage JSON-LD that matches the visible content."]
    return "\n".join(out)
