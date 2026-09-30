"""Counterfactual sandbox: real search, real fetches, real models - only the client's own pages are
served from our snapshot store instead of the live web.

Both arms of an experiment go through this layer. The baseline arm serves the *live* version of each
client page, the candidate arm serves the *modified* version, and all third-party results are shared
through a SearchCache. So the measured difference is attributable to the page change, not to search
noise.

Two things are measured separately, because they have different causes and different fixes:

  * FINDABILITY - is the client's site in the real search results at all? Ranking is the provider's; we do not
    fake it. This is checked with plain searches (see sim/findability.py) and reported as-is.
  * USEFULNESS WHEN FOUND - given that an assistant sees the client's page, does the answer use it well? With
    `expose=True` the best-matching client page is guaranteed to be among the results in BOTH arms (same rule,
    same position, snippet derived from whichever version the arm serves), so any difference is caused by
    the page content and nothing else. Without this, a small site that real search rarely returns would
    show "no change" no matter how good the edit was.
"""

import json
import time
from dataclasses import dataclass, field

from .. import activity
from ..textutil import BM25, best_passage, norm_url, same_site
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
    urls: dict[str, str] = field(default_factory=dict)  # norm_url -> the page's real URL
    expose: bool = False  # guarantee the best-matching client page is among the search results (both arms)
    expose_rank: int = 2  # ...at this position (1 = first result). Identical in both arms.
    _index: object = None

    def _client_index(self):
        if self._index is None:
            keys = list(self.pages)
            self._index = (keys, BM25([f"{self.pages[k][0]} {self.pages[k][1]}" for k in keys]) if keys else None)
        return self._index

    def best_client_page(self, query: str) -> tuple[str, str, str] | None:
        """(url, title, snippet) of the client page that best matches the query, if any matches at all."""
        keys, idx = self._client_index()
        if idx is None:
            return None
        top = idx.top(query, 1)
        if not top:
            return None
        key = keys[top[0][0]]
        title, text = self.pages[key]
        return self.urls.get(key, "https://" + key), title, best_passage(text, query, 300)

    def session(self) -> "ToolSession":
        return ToolSession(self)

    def _search(self, query: str) -> list[SearchHit]:
        key = (query.strip().lower(), self.max_results)
        with self.cache.lock:
            if key in self.cache.searches:
                return self.cache.searches[key]
        try:
            hits = self.provider.search(query, self.max_results)
        except Exception as e:
            if "no results" in str(e).lower():  # some providers raise for an empty result set
                hits = []
            else:
                time.sleep(1.5)  # one quick retry for a transient failure
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
    exposed: bool = False  # the assistant was shown a client page (naturally or via expose=True)
    fetched: bool = False  # the assistant actually opened a client page
    last_error: str = ""

    def web_search(self, query: str) -> list[dict]:
        self.queries.append(query)
        activity.emit(f"Searching the web: “{query[:90]}”", "tool")
        try:
            hits = list(self.sandbox._search(query))
        except Exception as e:  # a failing search must not fail the whole conversation
            self.last_error = f"{type(e).__name__}: {e}"[:160]
            activity.emit(f"The search service had a problem ({self.last_error[:80]}); the assistant will try again.", "warn")
            hits = []
        else:
            self.last_error = ""
        sb = self.sandbox
        out = []
        for h in hits:
            snippet, key = h.snippet, norm_url(h.url)
            if same_site(h.url, sb.client_domain) and key in sb.pages:
                # Re-derive the snippet from the served page version (same method in both arms).
                snippet = best_passage(sb.pages[key][1], query, 300)
                self.injected |= key in sb.modified
                self.exposed = True
            self.retrieved.append(h.url)
            out.append({"url": h.url, "title": h.title, "snippet": snippet})
        if sb.expose:
            best = sb.best_client_page(query)  # the page that best answers this query, which may be a brand-new one
            if best and norm_url(best[0]) not in {norm_url(r["url"]) for r in out}:
                url, title, snippet = best
                out.insert(min(max(sb.expose_rank, 1) - 1, len(out)), {"url": url, "title": title, "snippet": snippet})  # same slot in both arms
                self.retrieved.append(url)
                self.exposed = True
                self.injected |= norm_url(url) in sb.modified
        return out

    def fetch_page(self, url: str) -> str:
        key = norm_url(url)
        activity.emit(f"Reading a page: {key[:90]}", "tool")
        self.retrieved.append(url)
        if key in self.sandbox.pages:
            self.injected |= key in self.sandbox.modified
            self.exposed = self.fetched = True
            title, text = self.sandbox.pages[key]
        else:
            try:
                title, text = self.sandbox._fetch(url)
            except Exception as e:  # network / 4xx / not-in-corpus
                return f"ERROR: could not fetch {url}: {e}"
        return f"{title}\n\n{text[:MAX_FETCH_CHARS]}"

    def execute(self, name: str, args: dict) -> str:
        if name == "web_search":
            results = self.web_search(str(args.get("query", "")))
            if not results and self.last_error:
                return json.dumps({"results": [], "note": "The search service had a problem. Try again with a shorter, simpler query."})
            return json.dumps(results)
        if name == "fetch_page":
            return self.fetch_page(str(args.get("url", "")))
        return f"ERROR: unknown tool {name}"
