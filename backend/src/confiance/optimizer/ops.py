"""Structured page edits. The optimizer proposes ops, never raw HTML rewrites, so every change is
small, diffable and checkable by the guard."""

import copy
import json
import re
from typing import Any

from bs4 import BeautifulSoup

OP_TYPES = {"set_title", "set_meta_description", "add_jsonld", "add_faq", "insert_after", "append_section",
            "replace_block"}

OP_DOC = """Edit operations. Each one is a JSON object with a "type" and ALL of the fields shown (a missing field is rejected).
Examples of the ops array for propose_change:
  {"type": "set_meta_description", "content": "Short summary shown in search results (under 160 characters)."}
  {"type": "set_title", "text": "Page title"}
  {"type": "add_faq", "items": [{"q": "A real customer question?", "a": "A short, true answer taken from the page or knowledge base."}]}
  {"type": "append_section", "html": "<section><h2>Heading</h2><p>Text.</p></section>"}
  {"type": "insert_after", "selector": "h1", "html": "<p>One new paragraph.</p>"}
  {"type": "replace_block", "selector": "p.intro", "html": "<p>The reworded paragraph.</p>"}
  {"type": "add_jsonld", "json": {"@context": "https://schema.org", "@type": "LocalBusiness", "name": "..."}}
Guidance: prefer ADDING (add_faq, append_section, set_meta_description, add_jsonld). Use replace_block only for ONE
small element, never for the whole page or the <main> element: rewriting most of a page is rejected."""


class OpError(ValueError):
    pass


def _frag(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def _first(soup: BeautifulSoup, selector: str):
    try:
        el = soup.select_one(selector)
    except Exception as e:
        raise OpError(f"invalid selector {selector!r}: {e}") from e
    if el is None:
        raise OpError(f"selector {selector!r} matched nothing")
    return el


def _validate_shape(op: dict[str, Any]) -> None:
    t = op.get("type")
    need = {"set_title": ["text"], "set_meta_description": ["content"], "add_jsonld": ["json"],
            "add_faq": ["items"], "insert_after": ["selector", "html"], "append_section": ["html"],
            "replace_block": ["selector", "html"]}
    if t not in need:
        raise OpError(f"unknown op type {t!r}")
    for k in need[t]:
        if k not in op or op[k] in (None, "", []):
            raise OpError(f"op {t} missing field {k!r}")


def target_selector(op: dict[str, Any]) -> str | None:
    return op.get("selector") if op["type"] in ("insert_after", "replace_block", "append_section") else None


def apply_ops(html: str, ops: list[dict[str, Any]]) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for op in ops:
        _validate_shape(op)
        t = op["type"]
        if t == "set_title":
            if soup.title is None:
                head = soup.head or soup.new_tag("head")
                if soup.head is None:
                    soup.insert(0, head)
                head.append(soup.new_tag("title"))
            soup.title.string = op["text"]
        elif t == "set_meta_description":
            meta = soup.find("meta", attrs={"name": "description"})
            if meta is None:
                meta = soup.new_tag("meta", attrs={"name": "description"})
                (soup.head or soup).append(meta)
            meta["content"] = op["content"]
        elif t == "add_jsonld":
            data = op["json"]
            data = json.loads(data) if isinstance(data, str) else data
            tag = soup.new_tag("script", attrs={"type": "application/ld+json"})
            tag.string = json.dumps(data, ensure_ascii=False)
            (soup.head or soup).append(tag)
        elif t == "add_faq":
            items = op["items"]
            sec = _frag("<section data-confiance='faq'><h2>Frequently asked questions</h2>"
                        + "".join(f"<h3>{i['q']}</h3><p>{i['a']}</p>" for i in items) + "</section>")
            (soup.select_one("main") or soup.body or soup).append(sec)
            ld = {"@context": "https://schema.org", "@type": "FAQPage",
                  "mainEntity": [{"@type": "Question", "name": i["q"],
                                  "acceptedAnswer": {"@type": "Answer", "text": i["a"]}} for i in items]}
            tag = soup.new_tag("script", attrs={"type": "application/ld+json"})
            tag.string = json.dumps(ld, ensure_ascii=False)
            (soup.head or soup).append(tag)
        elif t == "insert_after":
            _first(soup, op["selector"]).insert_after(_frag(op["html"]))
        elif t == "append_section":
            target = _first(soup, op["selector"]) if op.get("selector") else (soup.select_one("main") or soup.body or soup)
            target.append(_frag(op["html"]))
        elif t == "replace_block":
            _first(soup, op["selector"]).replace_with(_frag(op["html"]))
    return str(soup)


def visible_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript", "template"]):
        t.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True))


def clone_ops(ops: list[dict]) -> list[dict]:
    return copy.deepcopy(ops)
