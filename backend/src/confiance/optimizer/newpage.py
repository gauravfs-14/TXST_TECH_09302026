"""Brand-new pages: the main lever for questions a site's existing pages can't answer.

A new page is assembled from a title, description, body HTML and optional JSON-LD, then checked by the same
kind of code guard as edits, plus rules that only make sense for new content (a real URL that doesn't collide,
enough substance, not a near-copy of an existing page, a cap on how many a round may add)."""

import html as htmllib
import json
import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from ..brief import Constraints
from ..textutil import norm_url, shingles
from .guard import _INJECTION, GuardReport, _hidden_count, _norm, _numbers
from .ops import visible_text

PATH_RE = re.compile(r"^/[a-z0-9][a-z0-9\-/]{0,98}$")
MIN_WORDS = 150


def build_page(title: str, meta_description: str, body_html: str, url: str, jsonld: dict | list | None = None, lang: str = "en") -> str:
    ld = "".join(f'<script type="application/ld+json">{json.dumps(j, ensure_ascii=False)}</script>' for j in ([jsonld] if isinstance(jsonld, dict) else (jsonld or [])))
    return ("<!doctype html>\n" f'<html lang="{htmllib.escape(lang)}"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{htmllib.escape(title)}</title>"
            f'<meta name="description" content="{htmllib.escape(meta_description, quote=True)}">'
            f'<link rel="canonical" href="{htmllib.escape(url, quote=True)}">{ld}</head>'
            f"<body><main>{body_html}</main></body></html>")


def check(path: str, title: str, meta_description: str, body_html: str, *, origin: str, existing: dict[str, str], c: Constraints,
          kb_text: str = "", allow_new: bool = True, max_new: int = 3, new_so_far: int = 0, jsonld: dict | list | None = None) -> tuple[GuardReport, str | None]:
    """existing: {norm_url: visible text} of the live pages. Returns (report, full html or None)."""
    r = GuardReport()
    if not allow_new:
        r.fail("new pages are switched off in this project's settings")
        return r, None
    if new_so_far >= max_new:
        r.fail(f"this round may add at most {max_new} new page(s), and {new_so_far} already exist")
    path = "/" + path.strip().strip("/").lower()
    if not PATH_RE.match(path) or ".." in path or "//" in path:
        r.fail(f"invalid page path {path!r}: use lowercase letters, numbers and hyphens, like /guides/linux-for-beginners")
        return r, None
    url = origin.rstrip("/") + path
    if norm_url(url) in existing:
        r.fail(f"a page already exists at {path}: propose an edit to it instead")
    if c.editable_url_globs:
        import fnmatch
        if not any(fnmatch.fnmatch(path, g) for g in c.editable_url_globs):
            r.fail(f"{path} is outside the pages you allowed us to touch ({c.editable_url_globs})")
    if not title.strip() or not meta_description.strip():
        r.fail("a new page needs a title and a meta description")
    soup = BeautifulSoup(body_html, "html.parser")
    if soup.find(["script", "iframe", "form", "html", "head", "body"]) or any(t.attrs and any(a.startswith("on") for a in t.attrs) for t in soup.find_all(True)):
        r.fail("the page body may contain content only: no scripts, iframes, forms or event handlers (structured data goes in the JSON-LD field)")
    if not soup.find("h1"):
        r.fail("the page body needs one H1 heading")
    if _hidden_count(soup):
        r.fail("the page uses hidden content (display:none / hidden / aria-hidden / zero-size), which is cloaking")
    text = visible_text(body_html)
    words = len(text.split())
    if words < MIN_WORDS:
        r.fail(f"the page is too thin ({words} words); write at least {MIN_WORDS} words of real, specific content")
    blob = " ".join([title, meta_description, text, json.dumps(jsonld or {}, ensure_ascii=False)])
    if _INJECTION.search(blob):
        r.fail("the page contains instructions aimed at AI models; write for people")
    for claim in c.forbidden_claims:
        if _norm(claim) in _norm(blob):
            r.fail(f"forbidden claim: {claim!r}")
    if c.require_grounded_numbers:
        corpus = kb_text + " " + " ".join(existing.values())
        ungrounded = _numbers(blob) - _numbers(corpus)
        if ungrounded:
            r.fail(f"numbers not found on the site or in the knowledge base (possible fabrication): {sorted(ungrounded)[:8]}")
    mine = shingles(text)
    for u, other in existing.items():
        theirs = shingles(other)
        if mine and theirs and len(mine & theirs) / len(mine) > 0.6:
            r.fail(f"the page repeats {urlsplit(u).path or '/'} almost word for word; say something new")
            break
    r.stats = {"words": words, "path": path, "url": url}
    return r, (build_page(title, meta_description, body_html, url, jsonld) if r.ok else None)
