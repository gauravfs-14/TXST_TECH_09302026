"""Reads one page the way a crawler would: metadata, headings, structured data, links, and any products."""

import json
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from .site import classify_url

PRODUCT_TYPES = {"product", "productgroup", "individualproduct"}
ARTICLE_TYPES = {"article", "blogposting", "newsarticle", "techarticle"}


def _walk_jsonld(node, out: list[dict]) -> None:
    if isinstance(node, list):
        for n in node:
            _walk_jsonld(n, out)
    elif isinstance(node, dict):
        if "@graph" in node:
            _walk_jsonld(node["@graph"], out)
        if "@type" in node:
            out.append(node)
        for v in node.values():
            if isinstance(v, (dict, list)) and v is not node.get("@graph"):
                _walk_jsonld(v, out)


def jsonld_items(soup: BeautifulSoup) -> list[dict]:
    items: list[dict] = []
    for tag in soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)}):
        try:
            _walk_jsonld(json.loads(tag.string or tag.get_text() or ""), items)
        except (ValueError, TypeError):
            continue
    return items


def _types(item: dict) -> list[str]:
    t = item.get("@type")
    return [str(x).lower() for x in (t if isinstance(t, list) else [t])] if t else []


def _first(v):
    return v[0] if isinstance(v, list) and v else v


def _price(offers) -> tuple[str, str]:
    o = _first(offers)
    if isinstance(o, dict):
        return str(o.get("price") or o.get("lowPrice") or ""), str(o.get("priceCurrency") or "")
    return "", ""


def analyze_page(url: str, html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    items = jsonld_items(soup)
    types = sorted({t for i in items for t in _types(i)})
    title = soup.title.get_text(strip=True) if soup.title else ""
    meta = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    robots_meta = soup.find("meta", attrs={"name": re.compile("^robots$", re.I)})
    canonical = soup.find("link", rel="canonical")
    og = {m.get("property"): m.get("content") for m in soup.find_all("meta", property=re.compile("^(og|product):"))}
    for t in soup(["script", "style", "noscript", "template", "svg"]):
        t.decompose()
    text = soup.get_text(" ", strip=True)
    host = urlsplit(url).netloc
    links = {urljoin(url, a["href"]).split("#")[0] for a in soup.select("a[href]") if not a["href"].startswith(("mailto:", "tel:", "javascript:"))}
    internal = sorted(l for l in links if urlsplit(l).netloc == host)
    imgs = soup.find_all("img")
    products = []
    for i in items:
        if set(_types(i)) & PRODUCT_TYPES:
            price, cur = _price(i.get("offers"))
            brand = i.get("brand")
            brand = brand.get("name") if isinstance(brand, dict) else brand
            products.append({"name": str(i.get("name") or "").strip(), "sku": str(i.get("sku") or i.get("mpn") or i.get("gtin13") or i.get("gtin") or ""),
                             "url": str(i.get("url") or url), "category": str(i.get("category") or ""), "brand": str(brand or ""),
                             "price": (f"{price} {cur}".strip() if price else ""), "description": str(i.get("description") or "")[:400],
                             "has_offers": bool(i.get("offers")), "has_rating": bool(i.get("aggregateRating")), "confidence": "high"})
    if not products and og.get("og:type") == "product" and (og.get("og:title") or title):
        products.append({"name": og.get("og:title") or title, "sku": "", "url": url, "category": "", "brand": og.get("og:site_name") or "",
                         "price": og.get("product:price:amount") or "", "description": (og.get("og:description") or "")[:400],
                         "has_offers": bool(og.get("product:price:amount")), "has_rating": False, "confidence": "medium"})
    # The URL gives a first guess; what the page declares about itself overrides it.
    page_type = classify_url(url)
    tset = set(types)
    if tset & PRODUCT_TYPES or og.get("og:type") == "product":
        page_type = "product"
    elif "faqpage" in tset and page_type == "other":
        page_type = "faq"
    elif tset & ARTICLE_TYPES and page_type == "other":
        page_type = "blog"
    return {
        "url": url, "type": page_type, "title": title, "meta_description": (meta.get("content", "").strip() if meta else ""),
        "h1": [h.get_text(strip=True) for h in soup.find_all("h1")][:5], "h2": [h.get_text(strip=True) for h in soup.find_all("h2")][:12],
        "canonical": canonical.get("href") if canonical else "", "noindex": bool(robots_meta and "noindex" in robots_meta.get("content", "").lower()),
        "lang": (soup.html.get("lang") if soup.html else "") or "", "viewport": bool(soup.find("meta", attrs={"name": "viewport"})),
        "schema_types": types, "og": bool(og), "words": len(text.split()), "images": len(imgs),
        "images_no_alt": sum(1 for i in imgs if not (i.get("alt") or "").strip()), "internal_links": internal[:200],
        "products": products, "text_sample": text[:1500],
    }
