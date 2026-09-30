"""Turning a paired comparison into an honest, plain-language verdict.

Small samples make small differences look meaningful. A change is only called an improvement when it is both
statistically clear (the interval excludes zero) AND large enough to matter (>= min_effect). Anything smaller is
reported as 'no meaningful change', which is the truthful answer far more often than people expect."""

MIN_PAIRS = 6


def verdict(delta: dict, min_effect: float = 0.05) -> dict:
    d, (lo, hi), n = delta.get("delta", 0.0), delta.get("ci", [0.0, 0.0]), delta.get("pairs", 0)
    if n < MIN_PAIRS:
        return {"label": "inconclusive", "recommendation": "review", "text": f"Only {n} comparisons, which is too few to judge. Run a larger round to be sure."}
    if lo > 0 and d >= min_effect:
        return {"label": "improved", "recommendation": "approve", "text": f"A clear improvement: about {d:+.2f} on a 0 to 1 scale (95% range {lo:+.2f} to {hi:+.2f})."}
    if hi < 0 and d <= -min_effect / 2:
        return {"label": "worse", "recommendation": "reject", "text": f"These changes made answers worse ({d:+.2f}). Don't publish them."}
    if abs(d) < min_effect and lo > -min_effect and hi < min_effect:
        return {"label": "no_change", "recommendation": "review", "text": f"No meaningful change ({d:+.2f}, range {lo:+.2f} to {hi:+.2f}). The edits did not shift how assistants answer."}
    return {"label": "inconclusive", "recommendation": "review", "text": f"Possibly helpful ({d:+.2f}) but the range ({lo:+.2f} to {hi:+.2f}) is too wide to be sure."}
