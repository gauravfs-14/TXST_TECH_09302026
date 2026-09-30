"""Site scan: discovery + crawl + page analysis + audit + product detection, saved as a SiteAudit.

No AI is used here, so a scan is fast, free and repeatable. (Building the knowledge base from the crawled
pages is a separate step because that one does use the AI.)"""

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import activity, audit as auditlog
from .. import kb
from ..discovery import audit as audit_mod, lighthouse as lighthouse_mod, products as product_mod
from ..discovery.pages import analyze_page
from ..discovery.site import Discovery, choose_pages, discover
from ..models import Page, Product, Project, SiteAudit
from ..search.providers import build_provider
from ..textutil import domain_of


def indexed_check(domain: str, provider=None) -> dict:
    """Does a `site:` search return anything? Best effort: a failing search means 'unknown', never 'not indexed'."""
    try:
        provider = provider or build_provider()
        hits = provider.search(f"site:{domain}", 10)
        return {"checked": True, "results": sum(1 for h in hits if domain_of(h.url).endswith(domain_of(domain)))}
    except Exception:
        return {"checked": False, "results": 0}


def scan(s: Session, project: Project, *, limit: int = 12, fetch_html: Callable[[str], str] | None = None,
         fetch: Callable | None = None, provider=None, lighthouse: Callable | None = None, on_phase: Callable[[str], None] | None = None) -> dict:
    phase = on_phase or (lambda p: None)
    phase("finding_pages")
    activity.emit("Looking for robots.txt, your sitemap and llms.txt…", "step")
    d: Discovery = discover(project.site_url or project.domain, **({"fetch": fetch} if fetch else {}))
    urls = choose_pages(d, limit)
    activity.emit(f"Found {len(d.urls)} pages listed on your site. Reading the {len(urls)} that matter most.", "step")

    phase("reading_pages")
    get_html = fetch_html or kb.fetch_html
    fetched, failed = [], {}
    for i, u in enumerate(urls, 1):
        activity.emit(f"Reading page {i} of {len(urls)}: {u.split('//', 1)[-1][:70]}", "tool")
        try:
            fetched.append((u, get_html(u)))
        except Exception as e:
            failed[u] = str(e)[:120]
            activity.emit(f"Couldn't open {u.split('//', 1)[-1][:60]}, skipping it.", "warn")
    if not fetched:
        raise RuntimeError("We could not open your website. Please check the address and try again.")
    pages = kb.import_pages(s, project, fetched)

    phase("auditing")
    activity.emit("Checking titles, headings, structured data and images…", "step")
    analyses = [analyze_page(u, html) for u, html in fetched]
    for row, a in zip(pages, analyses):
        row.page_type = a["type"]
    activity.emit("Asking search whether your site shows up at all…", "step")
    indexed = indexed_check(project.domain, provider)
    result = audit_mod.audit(d.to_dict(), analyses, indexed)
    if lighthouse_mod.enabled() or lighthouse:
        phase("speed_test")
        activity.emit("Running a Lighthouse test on your home page (this takes about a minute)…", "step")
        home = project.site_url or f"https://{project.domain}"
        lh = (lighthouse or lighthouse_mod.run)(home)
        activity.emit("Lighthouse: " + (", ".join(f"{k.replace('_', ' ')} {v}" for k, v in lh["scores"].items()) if lh.get("available") else "couldn't run it, carrying on without."), "step" if lh.get("available") else "warn")
    else:
        lh = {"available": False, "reason": "Lighthouse is turned off."}
    detected = product_mod.detect(analyses, d.to_dict(), d.urls)
    added = 0
    have = {(p.sku or "").lower() or p.url for p in s.scalars(select(Product).where(Product.project_id == project.id))}
    for pr in detected:
        if ((pr["sku"] or "").lower() or pr["url"]) in have:
            continue
        s.add(Product(project_id=project.id, name=pr["name"][:300], sku=pr["sku"][:100], url=pr["url"], category=pr["category"][:200],
                      brand=pr["brand"][:200], price=pr["price"][:50], attributes={"description": pr["description"], "confidence": pr["confidence"]},
                      source="detected", active=pr["confidence"] != "low"))
        added += 1
    record = SiteAudit(project_id=project.id, score=result["score"], data={
        "discovery": d.to_dict(), "audit": result, "indexed": indexed, "lighthouse": lh, "failed_urls": failed,
        "pages": [{k: v for k, v in a.items() if k != "internal_links"} | {"internal_links": len(a["internal_links"])} for a in analyses]})
    s.add(record)
    s.flush()
    auditlog.record("site.scanned", "scanner", {"pages": len(fetched), "score": result["score"], "findings": len(result["findings"]),
                                                "products_detected": added, "sitemap_urls": len(d.urls), "llms_txt": d.llms.get("exists")}, project_id=project.id)
    return {"audit_id": record.id, "score": result["score"], "pages": len(fetched), "urls_known": len(d.urls), "products_detected": added}


def latest(s: Session, project_id: int) -> SiteAudit | None:
    return s.scalars(select(SiteAudit).where(SiteAudit.project_id == project_id).order_by(SiteAudit.id.desc())).first()
