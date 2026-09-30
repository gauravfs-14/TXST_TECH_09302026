"""Real web search providers plus the offline corpus provider (tests/demos only)."""

import httpx

from ..config import get_settings
from ..textutil import BM25, best_passage
from .base import SearchHit, http_fetch


class TavilySearch:
    name = "tavily"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
        r = httpx.post("https://api.tavily.com/search", timeout=30,
                       headers={"Authorization": f"Bearer {self.api_key}"},
                       json={"query": query, "max_results": max_results, "search_depth": "basic"})
        r.raise_for_status()
        return [SearchHit(x["url"], x.get("title", ""), x.get("content", "")) for x in r.json().get("results", [])]

    def fetch(self, url: str) -> tuple[str, str]:
        return http_fetch(url)


class BraveSearch:
    name = "brave"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
        r = httpx.get("https://api.search.brave.com/res/v1/web/search", timeout=30,
                      params={"q": query, "count": max_results},
                      headers={"X-Subscription-Token": self.api_key, "Accept": "application/json"})
        r.raise_for_status()
        res = r.json().get("web", {}).get("results", [])
        return [SearchHit(x["url"], x.get("title", ""), x.get("description", "")) for x in res]

    def fetch(self, url: str) -> tuple[str, str]:
        return http_fetch(url)


class DuckDuckGoSearch:
    """Keyless web search through the `ddgs` package. Good for testing and small volumes; results are noisier
    than a paid search API and can be rate-limited."""

    name = "duckduckgo"

    def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
        from ddgs import DDGS

        res = DDGS().text(query, max_results=max_results) or []
        return [SearchHit(r.get("href") or r.get("url", ""), r.get("title", ""), r.get("body", "")) for r in res if r.get("href") or r.get("url")]

    def fetch(self, url: str) -> tuple[str, str]:
        return http_fetch(url)


class SearxngSearch:
    """Your own SearXNG instance (JSON output must be enabled in its settings)."""

    name = "searxng"

    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")

    def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
        r = httpx.get(f"{self.base}/search", params={"q": query, "format": "json"}, timeout=30)
        r.raise_for_status()
        return [SearchHit(x["url"], x.get("title", ""), x.get("content", "")) for x in r.json().get("results", [])[:max_results]]

    def fetch(self, url: str) -> tuple[str, str]:
        return http_fetch(url)


class OfflineCorpusSearch:
    """BM25 over a fixed corpus of (url, title, text). NOT a real engine - for tests and keyless demos."""

    name = "offline"

    def __init__(self, docs: list[tuple[str, str, str]]):
        self.docs = docs
        self.index = BM25([f"{t} {x}" for _, t, x in docs])

    def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
        return [SearchHit(self.docs[i][0], self.docs[i][1], best_passage(self.docs[i][2], query, 300))
                for i, _ in self.index.top(query, max_results)]

    def fetch(self, url: str) -> tuple[str, str]:
        from ..textutil import norm_url

        for u, t, x in self.docs:
            if norm_url(u) == norm_url(url):
                return t, x
        raise LookupError(f"not in offline corpus: {url}")


def build_provider(name: str | None = None, offline_docs: list[tuple[str, str, str]] | None = None):
    s = get_settings()
    name = name or s.search_provider
    if name == "tavily":
        if not s.tavily_api_key:
            raise RuntimeError("CONFIANCE_TAVILY_API_KEY is not set")
        return TavilySearch(s.tavily_api_key)
    if name == "brave":
        if not s.brave_api_key:
            raise RuntimeError("CONFIANCE_BRAVE_API_KEY is not set")
        return BraveSearch(s.brave_api_key)
    if name == "duckduckgo":
        return DuckDuckGoSearch()
    if name == "searxng":
        if not s.searxng_url:
            raise RuntimeError("CONFIANCE_SEARXNG_URL is not set")
        return SearxngSearch(s.searxng_url)
    if name == "offline":
        if not s.allow_offline:
            raise RuntimeError("offline search requires CONFIANCE_ALLOW_OFFLINE=true")
        return OfflineCorpusSearch(offline_docs or [])
    raise ValueError(f"unknown search provider {name}")
