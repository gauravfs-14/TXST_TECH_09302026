import threading
from dataclasses import dataclass, field
from typing import Protocol

import ipaddress
import socket
from urllib.parse import urljoin, urlparse

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


def _assert_public(url: str) -> None:
    """Refuse non-http(s) URLs and hosts that resolve to private, loopback or link-local addresses.
    Stops a web page the assistant reads from steering its fetch tool at the user's own machine or network."""
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError("Only public http(s) pages can be opened")
    try:
        infos = socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise ValueError(f"Could not resolve {u.hostname}") from e
    for info in infos:
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise ValueError("Pages on private or local networks cannot be opened")


def http_fetch(url: str, timeout: float = 15.0) -> tuple[str, str]:
    headers = {"User-Agent": "CONFIANCE-sandbox/0.1 (+research crawler)"}
    for _ in range(6):  # follow redirects by hand so every hop is checked
        _assert_public(url)
        r = httpx.get(url, timeout=timeout, follow_redirects=False, headers=headers)
        if r.is_redirect and r.headers.get("location"):
            url = urljoin(url, r.headers["location"])
            continue
        r.raise_for_status()
        if "html" in r.headers.get("content-type", "html"):
            return html_to_text(r.text)
        return "", r.text
    raise ValueError("Too many redirects")


@dataclass
class SearchCache:
    """Shares real search/fetch results across the arms of a paired experiment so the only
    difference between baseline and candidate is the client's own page content."""

    searches: dict[tuple[str, int], list[SearchHit]] = field(default_factory=dict)
    fetches: dict[str, tuple[str, str]] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)
