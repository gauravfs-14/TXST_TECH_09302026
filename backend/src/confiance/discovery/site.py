"""Site discovery: what a crawler or an AI assistant learns about a site before it reads a single page.

Reads robots.txt (and who it blocks), sitemaps (including sitemap indexes and .gz), and llms.txt / llms-full.txt,
then chooses which pages are worth crawling. Everything goes through an injectable `fetch`, so it is testable
without a network.
"""

import gzip
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

import httpx

UA = "CONFIANCE-crawler/0.2 (+site audit)"
Fetch = Callable[[str], tuple[int, bytes, dict]]

# AI-related crawlers and what blocking each one means.
AI_BOTS = {
    "GPTBot": "training", "OAI-SearchBot": "search", "ChatGPT-User": "user", "ClaudeBot": "training",
    "Claude-SearchBot": "search", "Claude-User": "user", "anthropic-ai": "training", "PerplexityBot": "search",
    "Perplexity-User": "user", "Google-Extended": "training", "Applebot-Extended": "training", "CCBot": "training",
    "Bytespider": "training", "cohere-ai": "training", "Amazonbot": "search",
}


def http_fetch(url: str) -> tuple[int, bytes, dict]:
    try:
        r = httpx.get(url, timeout=12, follow_redirects=True, headers={"User-Agent": UA})
        return r.status_code, r.content[:3_000_000], dict(r.headers)
    except Exception:
        return 0, b"", {}


def _text(body: bytes) -> str:
    return body.decode("utf-8", errors="replace")


# ---- robots.txt ---------------------------------------------------------------------------------------------------

def parse_robots(text: str) -> dict:
    groups: list[dict] = []
    sitemaps: list[str] = []
    cur: dict | None = None
    last_was_agent = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key, val = key.strip().lower(), val.strip()
        if key == "user-agent":
            if cur is None or not last_was_agent:
                cur = {"agents": [], "rules": []}
                groups.append(cur)
            cur["agents"].append(val.lower())
            last_was_agent = True
            continue
        last_was_agent = False
        if key == "sitemap":
            sitemaps.append(val)
        elif key in ("allow", "disallow") and cur is not None:
            cur["rules"].append((key, val))
    return {"groups": groups, "sitemaps": sitemaps}


def can_fetch(robots: dict, agent: str, path: str = "/") -> bool:
    """Longest matching rule wins; Allow beats Disallow on ties. A group naming the agent beats '*'."""
    agent = agent.lower()
    named = [g for g in robots["groups"] if any(a != "*" and a in agent for a in g["agents"])]
    star = [g for g in robots["groups"] if "*" in g["agents"]]
    groups = named or star
    best, allowed = -1, True
    for g in groups:
        for kind, pattern in g["rules"]:
            if not pattern:
                continue
            rx = re.escape(pattern).replace(r"\*", ".*").replace(r"\$", "$")
            if re.match(rx, path) and len(pattern) > best:
                best, allowed = len(pattern), kind == "allow"
            elif re.match(rx, path) and len(pattern) == best and kind == "allow":
                allowed = True
    return allowed


# ---- sitemaps ------------------------------------------------------------------------------------------------------

_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)
_URL_BLOCK = re.compile(r"<url>(.*?)</url>", re.I | re.S)
_SM_BLOCK = re.compile(r"<sitemap>(.*?)</sitemap>", re.I | re.S)
_LASTMOD = re.compile(r"<lastmod>\s*([^<\s]+)\s*</lastmod>", re.I)


def parse_sitemap(xml: str) -> dict:
    """-> {"index": [child sitemap urls], "urls": [{"url", "lastmod"}]}"""
    index = [m.group(1) for b in _SM_BLOCK.findall(xml) for m in [_LOC.search(b)] if m]
    urls = []
    for b in _URL_BLOCK.findall(xml):
        loc = _LOC.search(b)
        if loc:
            lm = _LASTMOD.search(b)
            urls.append({"url": loc.group(1), "lastmod": lm.group(1) if lm else None})
    return {"index": index, "urls": urls}


def _body(url: str, body: bytes) -> str:
    if url.endswith(".gz") or body[:2] == b"\x1f\x8b":
        try:
            return _text(gzip.decompress(body))
        except Exception:
            return ""
    return _text(body)


# ---- llms.txt ------------------------------------------------------------------------------------------------------

_LINK = re.compile(r"^\s*[-*]\s*\[([^\]]+)\]\(([^)\s]+)\)\s*:?\s*(.*)$")


def parse_llms(text: str) -> dict:
    """The llms.txt convention: an H1 title, a blockquote summary, then H2 sections of markdown links."""
    title, summary, sections, cur = "", "", [], None
    for line in text.splitlines():
        if line.startswith("# ") and not title:
            title = line[2:].strip()
        elif line.startswith(">") and not summary:
            summary = line.lstrip("> ").strip()
        elif line.startswith("## "):
            cur = {"name": line[3:].strip(), "links": []}
            sections.append(cur)
        else:
            m = _LINK.match(line)
            if m and cur is not None:
                cur["links"].append({"title": m.group(1), "url": m.group(2), "desc": m.group(3).strip()})
    return {"title": title, "summary": summary, "sections": sections, "links": sum(len(s["links"]) for s in sections)}


# ---- URL classification --------------------------------------------------------------------------------------------

_PRODUCT = re.compile(r"/(products?|p|item|items|dp|shop/[^/]+/[^/]+|catalog/[^/]+/[^/]+)/[^/]+/?$", re.I)
_CATEGORY = re.compile(r"/(category|categories|collections?|c|shop|catalog|department)(/[^/]+)?/?$", re.I)
_BLOG = re.compile(r"/(blogs?|news|articles?|posts?|guides?|learn|resources|insights|stories)(/|$)|/20\d\d/\d\d/", re.I)


def classify_url(url: str) -> str:
    path = urlsplit(url).path or "/"
    if path == "/":
        return "home"
    if re.search(r"/about|/our-story|/company", path, re.I):
        return "about"
    if re.search(r"/contact", path, re.I):
        return "contact"
    if re.search(r"/faq|/help|/support", path, re.I):
        return "faq"
    if _PRODUCT.search(path) and not re.search(r"/products?/?$", path, re.I):
        return "product"
    if _CATEGORY.search(path) or re.search(r"/products?/?$", path, re.I):
        return "category"
    if _BLOG.search(path):
        return "blog"
    return "other"


# ---- the discovery itself ----------------------------------------------------------------------------------------------

@dataclass
class Discovery:
    origin: str
    robots: dict = field(default_factory=dict)      # {"exists", "sitemaps", "ai_bots": {bot: {"purpose", "allowed"}}, "blocks_all"}
    sitemaps: list[dict] = field(default_factory=list)  # [{"url", "status", "urls", "children"}]
    urls: list[dict] = field(default_factory=list)  # [{"url", "lastmod", "type"}]
    llms: dict = field(default_factory=dict)        # {"exists", "url", "title", "summary", "sections", "links", "size"}
    llms_full: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"origin": self.origin, "robots": self.robots, "sitemaps": self.sitemaps, "url_count": len(self.urls),
                "types": _count_types(self.urls), "llms": self.llms, "llms_full": self.llms_full, "notes": self.notes}


def _count_types(urls: list[dict]) -> dict:
    out: dict[str, int] = {}
    for u in urls:
        out[u["type"]] = out.get(u["type"], 0) + 1
    return out


def discover(site_url: str, fetch: Fetch = http_fetch, max_urls: int = 3000, depth: int = 2) -> Discovery:
    root = site_url if "//" in site_url else f"https://{site_url}"
    p = urlsplit(root)
    origin = f"{p.scheme}://{p.netloc}"
    d = Discovery(origin=origin)

    # robots.txt
    status, body, _ = fetch(origin + "/robots.txt")
    if status == 200 and body.strip():
        robots = parse_robots(_text(body))
        ai = {bot: {"purpose": purpose, "allowed": can_fetch(robots, bot, "/")} for bot, purpose in AI_BOTS.items()}
        d.robots = {"exists": True, "url": origin + "/robots.txt", "sitemaps": robots["sitemaps"], "ai_bots": ai,
                    "blocks_all": not can_fetch(robots, "*", "/"), "groups": len(robots["groups"]), "raw": _text(body)[:6000]}
    else:
        d.robots = {"exists": False, "url": origin + "/robots.txt", "sitemaps": [], "ai_bots": {}, "blocks_all": False}

    # sitemaps: those robots.txt names, else the usual places
    candidates = list(d.robots["sitemaps"]) or [origin + "/sitemap.xml", origin + "/sitemap_index.xml", origin + "/sitemap-index.xml"]
    seen: set[str] = set()
    seen_urls: dict[str, dict] = {}

    def walk(url: str, level: int) -> None:
        if url in seen or len(seen_urls) >= max_urls:
            return
        seen.add(url)
        st, bd, _ = fetch(url)
        entry = {"url": url, "status": st, "urls": 0, "children": 0}
        if st == 200 and bd:
            parsed = parse_sitemap(_body(url, bd))
            entry.update(urls=len(parsed["urls"]), children=len(parsed["index"]))
            for u in parsed["urls"]:
                if len(seen_urls) < max_urls:
                    seen_urls.setdefault(u["url"], u)
            if level < depth:
                for child in parsed["index"][:40]:
                    walk(urljoin(url, child), level + 1)
        d.sitemaps.append(entry)

    for c in candidates:
        walk(c, 0)
        if any(e["status"] == 200 and (e["urls"] or e["children"]) for e in d.sitemaps) and not d.robots["sitemaps"]:
            break  # found the default one; don't keep guessing
    d.urls = [{"url": u["url"], "lastmod": u["lastmod"], "type": classify_url(u["url"])} for u in seen_urls.values()]

    # llms.txt
    for name, key in (("llms.txt", "llms"), ("llms-full.txt", "llms_full")):
        st, bd, _ = fetch(f"{origin}/{name}")
        txt = _text(bd) if st == 200 else ""
        looks_like_html = txt.lstrip()[:15].lower().startswith(("<!doctype", "<html"))
        if st == 200 and txt.strip() and not looks_like_html:
            setattr(d, key, {"exists": True, "url": f"{origin}/{name}", "size": len(txt), **parse_llms(txt)})
        else:
            setattr(d, key, {"exists": False, "url": f"{origin}/{name}"})
    if d.llms.get("exists"):  # pages the site itself calls important are worth crawling even if the sitemap lacks them
        known = {u["url"] for u in d.urls}
        for sec in d.llms["sections"]:
            for link in sec["links"]:
                full = urljoin(origin + "/", link["url"])
                if full not in known and urlsplit(full).netloc == p.netloc:
                    d.urls.append({"url": full, "lastmod": None, "type": classify_url(full), "from": "llms.txt"})
    return d


def choose_pages(d: Discovery, limit: int = 12) -> list[str]:
    """Which pages to actually crawl: the home page first, then a spread across page types so one type
    (usually blog posts) doesn't crowd out the pages that matter for products and trust."""
    quota = {"home": 1, "about": 1, "contact": 1, "faq": 1, "category": 2, "product": 4, "blog": 3, "other": 2}
    by_type: dict[str, list[str]] = {}
    for u in d.urls:
        by_type.setdefault(u["type"], []).append(u["url"])
    chosen: list[str] = [d.origin + "/"]
    for typ, n in quota.items():
        for url in by_type.get(typ, [])[:n]:
            if url.rstrip("/") not in {c.rstrip("/") for c in chosen}:
                chosen.append(url)
    for u in d.urls:  # top up with whatever is left, llms.txt-listed pages first
        if len(chosen) >= limit:
            break
        if u["url"].rstrip("/") not in {c.rstrip("/") for c in chosen}:
            chosen.append(u["url"])
    return chosen[:limit]
