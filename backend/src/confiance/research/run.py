"""Research stage: what the real search results look like for each question, who wins, and what their pages do.

Everything here is deterministic (searches and page reads, no AI), so it is cheap, repeatable and explainable.
The output feeds both the optimizer (what to write) and the plan (what else to do)."""

import statistics
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from ..discovery.pages import analyze_page
from ..sim import findability
from ..textutil import domain_of, same_site, tokens

Fetch = Callable[[str], str]


def coverage(query: str, text: str) -> float:
    """Share of the question's meaningful words that appear on the page (0 to 1)."""
    q = set(tokens(query))
    return len(q & set(tokens(text))) / len(q) if q else 0.0


def question_fit(rank: int | None, best_cov: float) -> tuple[str, str]:
    if rank is not None and rank <= 3:
        return "winning", f"Search already shows you at #{rank}. Protect it and make sure assistants can use the page."
    if rank is not None or best_cov >= 0.5:
        return "in_reach", ("Search shows you at #%d. Strengthening the page can move it up." % rank) if rank is not None else \
            "Your site already covers much of what this asks, but search doesn't show it yet. Sharper content and technical fixes can change that."
    return "needs_content", "Your site doesn't cover this question yet and search doesn't show you. A dedicated page is the most direct fix."


def _fetch_competitors(urls: list[str], fetch_html: Fetch) -> list[dict]:
    def one(u: str) -> dict | None:
        try:
            a = analyze_page(u, fetch_html(u))
        except Exception:
            return None
        return {"url": u, "domain": domain_of(u), "title": a["title"], "words": a["words"], "schema_types": a["schema_types"], "h2": a["h2"][:8],
                "has_faq": "faqpage" in a["schema_types"] or any("faq" in h.lower() or h.strip().endswith("?") for h in a["h2"]),
                "type": a["type"]}

    with ThreadPoolExecutor(4) as pool:
        return [r for r in pool.map(one, urls) if r]


def patterns(comps: list[dict]) -> dict:
    if not comps:
        return {}
    words = [c["words"] for c in comps if c["words"]]
    schema = Counter(t for c in comps for t in set(c["schema_types"]))
    h2 = Counter(h.lower() for c in comps for h in c["h2"])
    n = len(comps)
    return {"pages": n, "median_words": int(statistics.median(words)) if words else 0,
            "share_with_faq": round(sum(c["has_faq"] for c in comps) / n, 2),
            "common_schema": [{"type": t, "share": round(k / n, 2)} for t, k in schema.most_common(5)],
            "common_headings": [h for h, k in h2.most_common(6) if k > 1]}


def run_research(provider, client_domain: str, business_name: str, questions: list[tuple], site_texts: dict[str, str], *,
                 product_urls: dict[str, str] | None = None, fetch_html: Fetch | None = None, max_competitor_pages: int = 6,
                 on_progress: Callable[[str], None] | None = None) -> dict:
    """questions: [(id, text)]; site_texts: {page url: visible text} for the client's live pages."""
    say = on_progress or (lambda m: None)
    hits: dict = {}
    say("Checking which questions real search already finds you for")
    finds = findability.check(provider, client_domain, business_name, questions, product_urls, hits_out=hits)
    by_id = {f["id"]: f for f in finds}

    entries = []
    for qid, text in questions:
        f = by_id.get(qid, {})
        best_url, best_cov = None, 0.0
        for u, t in site_texts.items():
            c = coverage(text, t)
            if c > best_cov:
                best_url, best_cov = u, c
        fit, why = question_fit(f.get("rank"), best_cov)
        entries.append({**f, "id": qid, "query": text, "best_page": best_url, "coverage": round(best_cov, 2), "fit": fit, "fit_reason": why})

    # Competitor pages: prefer questions we don't win yet; at most two distinct domains per question.
    comps: list[dict] = []
    if fetch_html:
        say("Reading the pages that win these questions today")
        want, seen_urls = [], set()
        for e in sorted(entries, key=lambda e: {"needs_content": 0, "in_reach": 1, "winning": 2}[e["fit"]]):
            doms = set()
            for h in hits.get(e["id"], []):
                if same_site(h.url, client_domain) or h.url in seen_urls or domain_of(h.url) in doms:
                    continue
                doms.add(domain_of(h.url))
                seen_urls.add(h.url)
                want.append(h.url)
                if len(doms) == 2:
                    break
            if len(want) >= max_competitor_pages:
                break
        comps = _fetch_competitors(want[:max_competitor_pages], fetch_html)

    checked = [e for e in entries if e["status"] != "unknown"]
    return {"queries": entries, "brand": by_id.get("brand"), "competitors": comps, "patterns": patterns(comps),
            "summary": {"questions": len(entries), "checked": len(checked), "found": sum(e["status"] == "found" for e in checked),
                        "winning": sum(e["fit"] == "winning" for e in entries), "in_reach": sum(e["fit"] == "in_reach" for e in entries),
                        "needs_content": sum(e["fit"] == "needs_content" for e in entries), "brand_found": bool(by_id.get("brand", {}).get("status") == "found")}}
