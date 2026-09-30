"""Company knowledge base: built once per content change, then shared by every agent.

Token economics: agents never re-read the site. They receive a compact "card" (summary + key facts)
as a cached system-prefix, and pull extra passages on demand through BM25 retrieval. The expensive
extraction call is skipped entirely when page content is unchanged (content-hash cache).
"""

import hashlib

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, llm, snapshots
from ..models import KnowledgeItem, Page, Project
from ..textutil import BM25, html_to_text, norm_url, passages

EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "facts": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "facts"],
    "additionalProperties": False,
}

MAX_EXTRACT_CHARS = 60_000


def fetch_html(url: str) -> str:
    r = httpx.get(url, timeout=20, follow_redirects=True, headers={"User-Agent": "CONFIANCE-crawler/0.1"})
    r.raise_for_status()
    return r.text


def import_pages(s: Session, project: Project, pages: list[tuple[str, str]], *, source: str = "crawl",
                 source_paths: dict[str, str] | None = None) -> list[Page]:
    """Store (url, html) pairs as new page versions. Unchanged content does not create a new version."""
    out = []
    for url, html in pages:
        page = s.scalars(select(Page).where(Page.project_id == project.id, Page.url == url)).first()
        if page is None:
            page = Page(project_id=project.id, url=url, source_path=(source_paths or {}).get(url))
            s.add(page)
            s.flush()
        elif page.kind == "archived":
            page.kind = "page"  # the site address came back
        cur = snapshots.live_content(s, page)
        if cur != html:
            v = snapshots.new_version(s, page, html, source, parent_id=page.live_version_id, note="imported")
            page.live_version_id = v.id
        out.append(page)
    audit.record("pages.imported", "system", {"urls": [p[0] for p in pages], "source": source}, project_id=project.id)
    return out


def crawl(s: Session, project: Project, urls: list[str]) -> list[Page]:
    fetched, errors = [], {}
    for u in urls:
        try:
            fetched.append((u, fetch_html(u)))
        except Exception as e:
            errors[u] = str(e)
    if errors:
        audit.record("pages.crawl_errors", "system", errors, project_id=project.id)
    return import_pages(s, project, fetched)


def _vh(s: Session, p: Page) -> str:
    from ..models import PageVersion
    return s.get(PageVersion, p.live_version_id).blob_hash


def build(s: Session, project: Project, *, force: bool = False) -> int:
    pages = list(s.scalars(select(Page).where(Page.project_id == project.id, Page.kind != "archived")))
    if not pages:
        raise ValueError("no pages to build a knowledge base from; crawl or import pages first")
    fingerprint = hashlib.sha256("".join(sorted(_vh(s, p) for p in pages if p.live_version_id)).encode()).hexdigest()
    last = s.scalars(select(KnowledgeItem).where(KnowledgeItem.project_id == project.id,
                                                 KnowledgeItem.kb_version == project.kb_version,
                                                 KnowledgeItem.kind == "fingerprint")).first()
    if last and last.content == fingerprint and not force:
        audit.record("kb.skipped_unchanged", "system", {"kb_version": project.kb_version}, project_id=project.id)
        return project.kb_version

    texts = []
    for p in pages:
        title, text = html_to_text(snapshots.live_content(s, p) or "")
        texts.append((p.url, title, text))
    corpus = "\n\n".join(f"## {u} ({t})\n{x}" for u, t, x in texts)[:MAX_EXTRACT_CHARS]
    data = llm.json_call(
        "kb.extract", system="You extract verifiable business facts from website content. Only state what the "
        "pages explicitly say. No marketing language, no inference.",
        prompt=f"Website content:\n\n{corpus}\n\nReturn a 3-5 sentence factual summary of the business and a list of "
               "specific, atomic facts (offerings, prices, locations, differentiators, credentials, numbers).",
        schema=EXTRACT_SCHEMA, max_tokens=4000)
    version = project.kb_version + 1
    s.add(KnowledgeItem(project_id=project.id, kb_version=version, kind="summary", content=data["summary"]))
    for f in data["facts"]:
        s.add(KnowledgeItem(project_id=project.id, kb_version=version, kind="fact", content=f))
    for u, t, x in texts:
        for ps in passages(x):
            s.add(KnowledgeItem(project_id=project.id, kb_version=version, kind="chunk", content=ps, source_url=u))
    s.add(KnowledgeItem(project_id=project.id, kb_version=version, kind="fingerprint", content=fingerprint))
    project.kb_version = version
    s.flush()
    audit.record("kb.built", "kb_builder", {"kb_version": version, "facts": len(data["facts"]), "pages": len(pages)},
                 project_id=project.id)
    return version


def add_fact(s: Session, project: Project, fact: str) -> None:
    """User-supplied facts join the current KB version and count as grounding for numeric claims."""
    s.add(KnowledgeItem(project_id=project.id, kb_version=project.kb_version, kind="fact", content=fact))
    audit.record("kb.fact_added", "user", {"fact": fact}, project_id=project.id)


def _items(s: Session, project: Project, kind: str) -> list[KnowledgeItem]:
    return list(s.scalars(select(KnowledgeItem).where(
        KnowledgeItem.project_id == project.id, KnowledgeItem.kb_version == project.kb_version,
        KnowledgeItem.kind == kind).order_by(KnowledgeItem.id)))


def card(s: Session, project: Project, max_facts: int = 40) -> str:
    """Compact, stable text block used as the cached system prefix for all agents."""
    summary = next(iter(_items(s, project, "summary")), None)
    facts = [f.content for f in _items(s, project, "fact")][:max_facts]
    return (f"# {project.name} ({project.domain})\n" + (summary.content if summary else "") +
            "\n\nKey facts:\n" + "\n".join(f"- {f}" for f in facts))


def grounding_text(s: Session, project: Project) -> str:
    return " ".join(f.content for f in _items(s, project, "fact") + _items(s, project, "summary"))


def search(s: Session, project: Project, query: str, k: int = 4) -> list[dict]:
    chunks = _items(s, project, "chunk")
    if not chunks:
        return []
    idx = BM25([c.content for c in chunks])
    return [{"url": chunks[i].source_url, "text": chunks[i].content} for i, _ in idx.top(query, k)]


def page_by_norm(s: Session, project: Project) -> dict[str, Page]:
    return {norm_url(p.url): p for p in s.scalars(select(Page).where(Page.project_id == project.id, Page.kind != "archived"))}


_SKIP_EXT = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".zip", ".mp4", ".mp3", ".css", ".js", ".xml", ".ico")


def discover(site_url: str, limit: int = 8) -> list[str]:
    """Find a site's main pages from just its address: sitemap first, then links from the home page."""
    import re
    from urllib.parse import urldefrag, urljoin, urlsplit

    from ..textutil import same_site

    root = site_url if "//" in site_url else f"https://{site_url}"
    origin = "{0.scheme}://{0.netloc}".format(urlsplit(root))
    found: list[str] = [origin + "/"]

    def add(u: str) -> None:
        u = urldefrag(u)[0].split("?")[0]
        p = urlsplit(u)
        if p.scheme not in ("http", "https") or not same_site(u, origin) or p.path.lower().endswith(_SKIP_EXT):
            return
        norm = u.rstrip("/") + "/" if not p.path or p.path == "/" else u.rstrip("/")
        if norm not in found and len(found) < limit:
            found.append(norm)

    try:
        for loc in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", fetch_html(origin + "/sitemap.xml"))[:60]:
            if not loc.endswith(".xml"):
                add(loc)
    except Exception:
        pass
    if len(found) < limit:
        try:
            from bs4 import BeautifulSoup

            for a in BeautifulSoup(fetch_html(origin + "/"), "html.parser").select("a[href]"):
                add(urljoin(origin + "/", a["href"]))
        except Exception:
            pass
    return found[:limit]
