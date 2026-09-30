"""Lighthouse scores (performance, accessibility, best practices, SEO) for a site's home page.

Lighthouse is the score most people already know, so we show it next to our own site health check. It is a
supplement: if it can't run, the scan carries on without it.

Two ways to run it, tried in order:
  1. locally: the `lighthouse` command (or `npx lighthouse`) with Google Chrome installed. Free, private, reliable.
  2. Google's PageSpeed Insights API (runs the same Lighthouse remotely). Free but rate-limited without a key;
     set CONFIANCE_PAGESPEED_API_KEY for reliable use.
Set CONFIANCE_LIGHTHOUSE=off to skip it entirely."""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import httpx

CATEGORIES = ("performance", "accessibility", "best-practices", "seo")
KEY = {"performance": "performance", "accessibility": "accessibility", "best-practices": "best_practices", "seo": "seo"}
METRICS = {"first-contentful-paint": "fcp", "largest-contentful-paint": "lcp", "total-blocking-time": "tbt", "cumulative-layout-shift": "cls", "speed-index": "speed_index"}
PSI = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"


def enabled() -> bool:
    return os.environ.get("CONFIANCE_LIGHTHOUSE", "auto").lower() not in ("off", "false", "0", "no")


def _command() -> list[str] | None:
    if shutil.which("lighthouse"):
        return ["lighthouse"]
    if shutil.which("npx"):
        return ["npx", "-y", "lighthouse"]
    return None


def summarize(lh: dict, source: str, strategy: str, url: str) -> dict:
    """Boil the (huge) Lighthouse report down to what a person can act on."""
    cats, audits = lh.get("categories", {}), lh.get("audits", {})
    scores = {KEY[c]: round((cats.get(c, {}).get("score") or 0) * 100) for c in CATEGORIES if c in cats}
    metrics = {}
    for aid, name in METRICS.items():
        a = audits.get(aid)
        if a:
            metrics[name] = {"value": a.get("numericValue"), "display": a.get("displayValue", ""), "score": a.get("score")}
    opportunities = []
    for aid, a in audits.items():
        d = a.get("details") or {}
        if d.get("type") == "opportunity" and (a.get("score") is not None and a["score"] < 0.9):
            opportunities.append({"id": aid, "title": a.get("title", ""), "detail": a.get("displayValue", ""), "savings_ms": round(d.get("overallSavingsMs") or 0)})
    opportunities.sort(key=lambda o: -o["savings_ms"])
    failed = {}
    for c in ("seo", "accessibility", "best-practices"):
        rows = []
        for ref in cats.get(c, {}).get("auditRefs", []):
            a = audits.get(ref["id"], {})
            if a.get("scoreDisplayMode") in ("binary", "numeric") and a.get("score") is not None and a["score"] < 0.9:
                rows.append({"id": ref["id"], "title": a.get("title", ""), "weight": ref.get("weight", 0)})
        failed[KEY[c]] = sorted(rows, key=lambda r: -r["weight"])[:8]
    return {"available": True, "source": source, "strategy": strategy, "url": url, "scores": scores, "metrics": metrics,
            "opportunities": opportunities[:6], "failed": failed, "version": lh.get("lighthouseVersion", "")}


def _run_local(url: str, strategy: str, timeout: int) -> dict:
    cmd = _command()
    if not cmd:
        raise RuntimeError("Node.js isn't installed, so Lighthouse can't run on this computer.")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "lh.json"
        args = [*cmd, url, "--output=json", f"--output-path={out}", "--quiet", "--chrome-flags=--headless=new --no-sandbox",
                f"--only-categories={','.join(CATEGORIES)}", f"--form-factor={strategy}"]
        if strategy == "desktop":
            args.append("--preset=desktop")
        try:
            proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise RuntimeError("Lighthouse took too long.")
        if not out.exists():
            raise RuntimeError((proc.stderr or proc.stdout or "Lighthouse produced no report").strip().splitlines()[-1][:200])
        return json.loads(out.read_text())


def _run_psi(url: str, strategy: str, timeout: int) -> dict:
    params = [("url", url), ("strategy", strategy), *[("category", c.upper().replace("-", "_")) for c in CATEGORIES]]
    key = os.environ.get("CONFIANCE_PAGESPEED_API_KEY")
    if key:
        params.append(("key", key))
    r = httpx.get(PSI, params=params, timeout=timeout)
    body = r.json()
    if r.status_code != 200:
        raise RuntimeError(body.get("error", {}).get("message", f"PageSpeed error {r.status_code}")[:200])
    return body["lighthouseResult"]


def run(url: str, strategy: str = "mobile", timeout: int = 180, local=None, remote=None) -> dict:
    """Never raises: returns {"available": False, "reason": ...} when neither runner works. `local`/`remote` are test seams."""
    if not enabled():
        return {"available": False, "reason": "Lighthouse is turned off."}
    errors = []
    for name, fn in (("local", local or _run_local), ("pagespeed", remote or _run_psi)):
        try:
            return summarize(fn(url, strategy, timeout), name, strategy, url)
        except Exception as e:
            errors.append(f"{name}: {str(e)[:150]}")
    return {"available": False, "reason": " · ".join(errors)}
