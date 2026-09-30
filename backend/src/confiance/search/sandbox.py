"""Counterfactual sandbox: real search, real fetches, real models - only the client's own pages are
served from our snapshot store instead of the live web.

Both arms of an experiment go through this layer. The baseline arm serves the *live* version of each
client page, the candidate arm serves the *modified* version, and all third-party results are shared
through a SearchCache. So the measured difference is attributable to the page change, not to search
noise. We never insert a client page into results where the real search did not return it: ranking is
left to the real provider, and "retrieval coverage" is reported separately.
"""

import json
from dataclasses import dataclass, field

from ..textutil import best_passage, norm_url, same_site
from .base import SearchCache, SearchHit, SearchProvider

MAX_FETCH_CHARS = 8000

WEB_SEARCH_SCHEMA = {
    "type": "object",
    "properties": {"query": {"type": "string", "description": "Search query"}},
    "required": ["query"],
    "additionalProperties": False,
}
FETCH_PAGE_SCHEMA = {
    "type": "object",
    "properties": {"url": {"type": "string", "description": "Absolute URL from a search result"}},
    "required": ["url"],
    "additionalProperties": False,
}
TOOL_SPECS = [
    ("web_search", "Search the web. Returns a JSON list of results with url, title and snippet.", WEB_SEARCH_SCHEMA),
    ("fetch_page", "Fetch the readable text of a web page by URL.", FETCH_PAGE_SCHEMA),
]


@dataclass
class Sandbox:
    provider: SearchProvider
    client_domain: str
    pages: dict[str, tuple[str, str]]  # norm_url -> (title, text) served for client pages
    modified: set[str] = field(default_factory=set)  # norm_urls whose served content differs from live
    cache: SearchCache = field(default_factory=SearchCache)
    max_results: int = 5

    def session(self) -> "ToolSession":
        return ToolSession(self)

    def _search(self, query: str) -> list[SearchHit]:
        key = (query.strip().lower(), self.max_results)
        with self.cache.lock:
            if key in self.cache.searches:
                return self.cache.searches[key]
        hits = self.provider.search(query, self.max_results)
        with self.cache.lock:
            self.cache.searches.setdefault(key, hits)
            return self.cache.searches[key]

    def _fetch(self, url: str) -> tuple[str, str]:
        key = norm_url(url)
        with self.cache.lock:
            if key in self.cache.fetches:
                return self.cache.fetches[key]
        res = self.provider.fetch(url)
        with self.cache.lock:
            self.cache.fetches.setdefault(key, res)
            return self.cache.fetches[key]


@dataclass
class ToolSession:
    sandbox: Sandbox
    queries: list[str] = field(default_factory=list)
    retrieved: list[str] = field(default_factory=list)
    injected: bool = False

    def web_search(self, query: str) -> list[dict]:
        self.queries.append(query)
        out = []
        for h in self.sandbox._search(query):
            snippet, key = h.snippet, norm_url(h.url)
            if same_site(h.url, self.sandbox.client_domain) and key in self.sandbox.pages:
                # Re-derive the snippet from the served page version (same method in both arms).
                snippet = best_passage(self.sandbox.pages[key][1], query, 300)
                self.injected |= key in self.sandbox.modified
            self.retrieved.append(h.url)
            out.append({"url": h.url, "title": h.title, "snippet": snippet})
        return out

    def fetch_page(self, url: str) -> str:
        key = norm_url(url)
        self.retrieved.append(url)
        if key in self.sandbox.pages:
            self.injected |= key in self.sandbox.modified
            title, text = self.sandbox.pages[key]
        else:
            try:
                title, text = self.sandbox._fetch(url)
            except Exception as e:  # network / 4xx / not-in-corpus
                return f"ERROR: could not fetch {url}: {e}"
        return f"{title}\n\n{text[:MAX_FETCH_CHARS]}"

    def execute(self, name: str, args: dict) -> str:
        if name == "web_search":
            return json.dumps(self.web_search(str(args.get("query", ""))))
        if name == "fetch_page":
            return self.fetch_page(str(args.get("url", "")))
        return f"ERROR: unknown tool {name}"
