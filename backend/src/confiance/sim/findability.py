"""Findability: is the client's site in the real search results at all?

No AI model is involved (plain searches, so it is fast and costs no AI requests). It answers the question that
page edits cannot: for a small site, most broad questions are dominated by big sites, and no wording change on
one page moves that. Reporting it honestly is what lets the product say what *will* help.
"""

from ..textutil import domain_of, same_site

DEPTH = 10


def check(provider, client_domain: str, business_name: str, questions: list[tuple], product_urls: dict[str, str] | None = None,
          hits_out: dict | None = None) -> list[dict]:
    """questions: [(id, text)]. Returns one entry per question plus one for the business name itself.
    For product questions, `product_urls` (question id -> product page URL) adds the rank of that exact page."""
    out = []
    for qid, text in [*[(q[0], q[1]) for q in questions], ("brand", business_name)]:
        entry = {"id": qid, "query": text, "rank": None, "status": "unknown", "top_domains": []}
        try:
            hits = provider.search(text, DEPTH)
        except Exception as e:
            if "no results" in str(e).lower():
                hits = []
            else:
                out.append(entry)
                continue
        if hits_out is not None:
            hits_out[qid] = hits  # so research can reuse the same results instead of searching twice
        domains = [domain_of(h.url) for h in hits]
        rank = next((i + 1 for i, h in enumerate(hits) if same_site(h.url, client_domain)), None)
        purl = (product_urls or {}).get(qid)
        if purl:
            from ..textutil import norm_url
            entry["product_rank"] = next((i + 1 for i, h in enumerate(hits) if norm_url(h.url) == norm_url(purl)), None)
        entry.update(rank=rank, status="found" if rank else "not_found",
                     top_domains=[d for d in dict.fromkeys(domains) if d and not same_site(d, client_domain)][:4])
        out.append(entry)
    return out


def summarize(items: list[dict]) -> dict:
    asked = [i for i in items if i["id"] != "brand" and i["status"] != "unknown"]
    found = [i for i in asked if i["status"] == "found"]
    brand = next((i for i in items if i["id"] == "brand"), None)
    return {"questions_checked": len(asked), "questions_found": len(found),
            "brand_found": bool(brand and brand["status"] == "found")}
