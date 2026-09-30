"""HTML -> text extraction, URL normalization, and a small BM25 used by the KB and offline search."""

import math
import re
from collections import Counter
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

_WORD = re.compile(r"[a-z0-9]+")
_STOP = set("a an the and or of to in on for with is are was were be by as at it this that from how what which who why "
            "do does can i you we our your my me best vs".split())


def tokens(text: str) -> list[str]:
    return [t for t in _WORD.findall(text.lower()) if t not in _STOP]


def norm_url(url: str) -> str:
    p = urlsplit(url.strip())
    host = (p.hostname or "").lower().removeprefix("www.")
    path = p.path.rstrip("/") or "/"
    return f"{host}{path}"


def domain_of(url: str) -> str:
    return (urlsplit(url if "//" in url else f"//{url}").hostname or "").lower().removeprefix("www.")


def same_site(url: str, domain: str) -> bool:
    d = domain_of(url)
    base = domain_of(domain)
    return d == base or d.endswith("." + base)


def html_to_text(html: str) -> tuple[str, str]:
    """Returns (title, visible text). JSON-LD is kept because engines' crawlers read it."""
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.title.string or "").strip() if soup.title and soup.title.string else ""
    jsonld = [t.get_text() for t in soup.find_all("script", attrs={"type": "application/ld+json"})]
    for t in soup(["script", "style", "noscript", "template", "svg"]):
        t.decompose()
    meta = soup.find("meta", attrs={"name": "description"})
    desc = meta.get("content", "") if meta else ""
    body = soup.get_text(" ", strip=True)
    parts = [p for p in [desc, body, *(f"[structured data] {j.strip()}" for j in jsonld)] if p]
    return title, re.sub(r"\s+", " ", " ".join(parts)).strip()


def passages(text: str, size: int = 450) -> list[str]:
    sents = re.split(r"(?<=[.!?])\s+", text)
    out, cur = [], ""
    for s in sents:
        if len(cur) + len(s) > size and cur:
            out.append(cur.strip())
            cur = ""
        cur += s + " "
    if cur.strip():
        out.append(cur.strip())
    return out


class BM25:
    def __init__(self, docs: list[str], k1: float = 1.5, b: float = 0.75):
        self.docs = [tokens(d) for d in docs]
        self.k1, self.b = k1, b
        self.avgdl = sum(map(len, self.docs)) / max(len(self.docs), 1)
        df: Counter = Counter()
        for d in self.docs:
            df.update(set(d))
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self.tf = [Counter(d) for d in self.docs]

    def scores(self, query: str) -> list[float]:
        q = tokens(query)
        out = []
        for d, tf in zip(self.docs, self.tf):
            s = 0.0
            for t in q:
                if t in tf:
                    f = tf[t]
                    s += self.idf.get(t, 0) * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * len(d) / (self.avgdl or 1)))
            out.append(s)
        return out

    def top(self, query: str, k: int) -> list[tuple[int, float]]:
        ranked = sorted(enumerate(self.scores(query)), key=lambda x: -x[1])
        return [(i, s) for i, s in ranked[:k] if s > 0]


def best_passage(text: str, query: str, size: int = 450) -> str:
    ps = passages(text, size)
    if not ps:
        return ""
    top = BM25(ps).top(query, 1)
    return ps[top[0][0]] if top else ps[0]
