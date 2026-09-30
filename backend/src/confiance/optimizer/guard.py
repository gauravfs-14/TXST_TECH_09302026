"""Constraint guard. Deterministic code, not a prompt: a proposed change either passes every check or is
blocked. The optimizer sees the violations and can retry, but cannot override them.

Two rule families:
  * client constraints from the brief (what may / may not be modified)
  * platform safety rules (no fabricated facts, no hidden text, no instructions aimed at AI models),
    which also protect the client from engine spam penalties.
"""

import fnmatch
import json
import re
from dataclasses import asdict, dataclass, field
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from ..brief import Constraints
from .ops import OP_TYPES, OpError, apply_ops, target_selector, visible_text

_INJECTION = re.compile(
    r"ignore (all |any |the )?(previous|prior|above)|as an ai\b|language model|system prompt|"
    r"(ai|llm|chatbot|assistant)s? (should|must|will) (always )?(recommend|cite|mention|prefer)|"
    r"when (an? )?(ai|llm|chatbot|assistant|user)s? (asks?|queries|searches)|always recommend", re.I)
_HIDDEN_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0|opacity\s*:\s*0(?![.\d])|"
                           r"text-indent\s*:\s*-\d{3,}|left\s*:\s*-\d{4,}", re.I)
_NUMBER = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?%?")


@dataclass
class GuardReport:
    ok: bool = True
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def fail(self, msg: str) -> None:
        self.ok = False
        self.violations.append(msg)

    def to_dict(self) -> dict:
        return asdict(self)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def _locked_html(soup: BeautifulSoup, selectors: list[str]) -> list[str]:
    out = []
    for sel in [*selectors, "[data-confiance-lock]"]:
        try:
            out += [str(el) for el in soup.select(sel)]
        except Exception:
            continue
    return out


def _hidden_count(soup: BeautifulSoup) -> int:
    n = len(soup.select("[hidden]")) + len(soup.select("[aria-hidden='true']"))
    n += sum(1 for el in soup.find_all(style=True) if _HIDDEN_STYLE.search(el["style"]))
    return n


def _numbers(text: str) -> set[str]:
    return {n.rstrip(".,").replace(",", "") for n in _NUMBER.findall(text)}


def _text_with_jsonld(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    extra = [t.get_text() for t in soup.find_all("script", attrs={"type": "application/ld+json"})]
    meta = soup.find("meta", attrs={"name": "description"})
    return " ".join([visible_text(html), meta.get("content", "") if meta else "", soup.title.get_text() if soup.title else "", *extra])


def check(old_html: str, ops: list[dict], url: str, c: Constraints, *, kb_text: str = "") -> tuple[GuardReport, str | None]:
    """Returns (report, new_html). new_html is None when ops can't be applied at all."""
    r = GuardReport()
    path = urlsplit(url).path or "/"

    if c.editable_url_globs and not any(fnmatch.fnmatch(path, g) for g in c.editable_url_globs):
        r.fail(f"page path {path} is not in editable_url_globs {c.editable_url_globs}")
    if not ops:
        r.fail("no operations proposed")
        return r, None

    allowed = set(c.allowed_ops) & OP_TYPES
    for op in ops:
        if op.get("type") not in allowed:
            r.fail(f"op type {op.get('type')!r} is not allowed (allowed: {sorted(allowed)})")
    if not r.ok:
        return r, None

    old_soup = BeautifulSoup(old_html, "html.parser")
    locked_targets = []
    for op in ops:
        sel = target_selector(op)
        if sel:
            try:
                for el in old_soup.select(sel)[:1]:
                    for lsel in [*c.locked_selectors, "[data-confiance-lock]"]:
                        for lock in old_soup.select(lsel):
                            if el is lock or lock in el.parents or el in lock.descendants:
                                locked_targets.append(f"{op['type']} on {sel!r} touches locked region {lsel!r}")
            except Exception:
                pass
    for v in dict.fromkeys(locked_targets):
        r.fail(v)

    try:
        new_html = apply_ops(old_html, ops)
    except (OpError, json.JSONDecodeError, KeyError, TypeError) as e:
        r.fail(f"ops could not be applied: {e}")
        return r, None
    new_soup = BeautifulSoup(new_html, "html.parser")

    # 1. locked regions byte-identical (multiset compare so reordering of others doesn't matter)
    before, after = _locked_html(old_soup, c.locked_selectors), _locked_html(new_soup, c.locked_selectors)
    if sorted(before) != sorted(after):
        r.fail("a locked region was modified")

    old_text, new_text = visible_text(old_html), visible_text(new_html)
    old_all, new_all = _text_with_jsonld(old_html), _text_with_jsonld(new_html)

    # 2. locked phrases preserved
    for ph in c.locked_phrases:
        if _norm(ph) in _norm(old_all) and _norm(ph) not in _norm(new_all):
            r.fail(f"locked phrase removed or altered: {ph!r}")

    # 3. no hidden text / cloaking, no instructions to AI models
    if _hidden_count(new_soup) > _hidden_count(old_soup):
        r.fail("change adds hidden content (display:none / hidden / aria-hidden / zero-size), which is cloaking")
    added_blob = " ".join(json.dumps(op, ensure_ascii=False) for op in ops)
    if _INJECTION.search(added_blob):
        r.fail("added content contains instructions aimed at AI models (prompt-injection style); content must be written for humans")

    # 4. forbidden claims
    for claim in c.forbidden_claims:
        if _norm(claim) in _norm(new_all) and _norm(claim) not in _norm(old_all):
            r.fail(f"forbidden claim introduced: {claim!r}")

    # 5. numbers must be grounded
    if c.require_grounded_numbers:
        ungrounded = _numbers(new_all) - _numbers(old_all) - _numbers(kb_text)
        if ungrounded:
            r.fail(f"numbers not found on the page or in the knowledge base (possible fabrication): {sorted(ungrounded)[:8]}")

    # 6. JSON-LD must parse
    for tag in new_soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            json.loads(tag.get_text())
        except json.JSONDecodeError:
            r.fail("invalid JSON-LD block")
            break

    # 7. bounded removal
    old_sents = {_norm(s) for s in re.split(r"(?<=[.!?])\s+", old_text) if s.strip()}
    new_sents = {_norm(s) for s in re.split(r"(?<=[.!?])\s+", new_text) if s.strip()}
    removed = len(old_sents - new_sents) / max(len(old_sents), 1)
    r.stats = {"removed_ratio": round(removed, 3), "old_chars": len(old_text), "new_chars": len(new_text)}
    if removed > c.max_change_ratio:
        r.fail(f"changes {removed:.0%} of existing text, above max_change_ratio {c.max_change_ratio:.0%}")

    # 8. warnings (not blocking)
    old_links = {a["href"] for a in old_soup.select("a[href]")}
    new_links = {a["href"] for a in new_soup.select("a[href]")}
    if old_links - new_links:
        r.warnings.append(f"{len(old_links - new_links)} link(s) removed")
    if new_html == old_html:
        r.fail("change produced no difference")
    return r, new_html
