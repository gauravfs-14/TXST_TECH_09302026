"""Per-project optimization settings. Every value has a safe default and a hard limit, so a typo in the UI can't
start an unbounded (and expensive) loop."""

DEFAULTS = {
    "max_loops": 3,          # hard cap on draft -> test -> decide passes in one round
    "min_gain": 0.03,        # a loop must beat the best so far by this much to count as progress
    "patience": 2,           # stop after this many loops in a row without progress
    "min_effect": 0.05,      # smallest improvement (out of 1) worth recommending; smaller is treated as noise
    "exposure_rank": 1,      # sandbox: where the page is placed in search results (1 = first)
    "track": ["brand", "products"],  # what to measure
    "plan": "quick",         # default round size
    "allow_new_pages": True,
    "max_new_pages": 3,
}
LIMITS = {"max_loops": (1, 10), "patience": (1, 5), "exposure_rank": (1, 5), "max_new_pages": (0, 10)}


def clamp(cfg: dict) -> dict:
    out = {**DEFAULTS, **{k: v for k, v in (cfg or {}).items() if k in DEFAULTS and v is not None}}
    for k, (lo, hi) in LIMITS.items():
        out[k] = max(lo, min(hi, int(out[k])))
    out["min_gain"] = max(0.0, min(0.5, float(out["min_gain"])))
    out["min_effect"] = max(0.0, min(0.5, float(out["min_effect"])))
    out["track"] = [t for t in out["track"] if t in ("brand", "products")] or ["brand"]
    out["allow_new_pages"] = bool(out["allow_new_pages"])
    return out


def for_project(project, overrides: dict | None = None) -> dict:
    return clamp({**(project.settings or {}), **(overrides or {})})
