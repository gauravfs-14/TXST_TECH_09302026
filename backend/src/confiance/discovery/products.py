"""Product / SKU detection from what the site already publishes."""

import re
from urllib.parse import urlsplit

from .site import classify_url


def _slug_name(url: str) -> str:
    slug = [s for s in urlsplit(url).path.split("/") if s][-1] if urlsplit(url).path.strip("/") else ""
    slug = re.sub(r"\.\w+$", "", slug)
    return re.sub(r"[-_]+", " ", slug).strip().title()


def detect(pages: list[dict], discovery: dict | None = None, sitemap_urls: list[dict] | None = None, limit: int = 60) -> list[dict]:
    """Structured data first (high confidence), then product-looking pages, then product-looking sitemap URLs (low)."""
    found: dict[str, dict] = {}

    def key(p: dict) -> str:
        return (p.get("sku") or "").lower() or urlsplit(p.get("url", "")).path.rstrip("/").lower() or p["name"].lower()

    for pg in pages:
        for pr in pg.get("products", []):
            if pr["name"]:
                found.setdefault(key(pr), {**pr, "source": "detected"})
        if pg["type"] == "product" and not pg.get("products"):
            name = (pg["h1"][0] if pg["h1"] else pg["title"]).strip()
            if name:
                found.setdefault(urlsplit(pg["url"]).path.rstrip("/").lower(), {"name": name, "sku": "", "url": pg["url"], "category": "", "brand": "", "price": "",
                                                                                 "description": pg["meta_description"][:300], "confidence": "medium", "source": "detected"})
    known_paths = {urlsplit(v["url"]).path.rstrip("/").lower() for v in found.values()}
    for u in sitemap_urls or []:
        if classify_url(u["url"]) == "product" and urlsplit(u["url"]).path.rstrip("/").lower() not in known_paths and len(found) < limit:
            found.setdefault(urlsplit(u["url"]).path.rstrip("/").lower(), {"name": _slug_name(u["url"]), "sku": "", "url": u["url"], "category": "", "brand": "", "price": "",
                                                                            "description": "", "confidence": "low", "source": "detected"})
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(found.values(), key=lambda p: order[p["confidence"]])[:limit]
