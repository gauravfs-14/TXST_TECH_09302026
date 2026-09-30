import threading
from dataclasses import dataclass, field
from typing import Protocol

import httpx

from ..textutil import html_to_text


@dataclass
class SearchHit:
    url: str
    title: str
    snippet: str


class SearchProvider(Protocol):
    name: str

    def search(self, query: str, max_results: int = 5) -> list[SearchHit]: ...

    def fetch(self, url: str) -> tuple[str, str]:
        """Return (title, text) for a URL."""
        ...


def http_fetch(url: str, timeout: float = 15.0) -> tuple[str, str]:
    r = httpx.get(url, timeout=timeout, follow_redirects=True,
                  headers={"User-Agent": "CONFIANCE-sandbox/0.1 (+research crawler)"})
    r.raise_for_status()
    if "html" in r.headers.get("content-type", "html"):
        return html_to_text(r.text)
    return "", r.text


@dataclass
class SearchCache:
    """Shares real search/fetch results across the arms of a paired experiment so the only
    difference between baseline and candidate is the client's own page content."""

    searches: dict[tuple[str, int], list[SearchHit]] = field(default_factory=dict)
    fetches: dict[str, tuple[str, str]] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)
