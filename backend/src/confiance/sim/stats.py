"""Small-sample statistics. LLM answers are noisy; every claim of improvement carries an interval."""

import math
import random
from collections import defaultdict


def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def bootstrap_ci(xs: list[float], iters: int = 2000, alpha: float = 0.05, seed: int = 7) -> tuple[float, float]:
    if not xs:
        return (0.0, 0.0)
    rng = random.Random(seed)
    n = len(xs)
    means = sorted(mean([xs[rng.randrange(n)] for _ in range(n)]) for _ in range(iters))
    return (means[int(alpha / 2 * iters)], means[int((1 - alpha / 2) * iters) - 1])


def aggregate(rows: list[dict]) -> dict:
    """rows: [{engine, question_id, score, metrics}] -> overall + per engine/question summaries."""
    def summarize(rs: list[dict]) -> dict:
        n = len(rs)
        sc = [r["score"] for r in rs]
        out = {"n": n, "visibility": round(mean(sc), 4), "visibility_ci": [round(x, 4) for x in bootstrap_ci(sc)]}
        for key in ("mentioned", "cited", "retrieved"):
            k = sum(1 for r in rs if r["metrics"].get(key))
            lo, hi = wilson(k, n)
            out[f"{key}_rate"] = round(k / n, 4) if n else 0.0
            out[f"{key}_ci"] = [round(lo, 4), round(hi, 4)]
        out["errors"] = sum(1 for r in rs if not r["metrics"].get("answered"))
        return out

    by_engine, by_question = defaultdict(list), defaultdict(list)
    for r in rows:
        by_engine[r["engine"]].append(r)
        by_question[r["question_id"]].append(r)
    return {"overall": summarize(rows),
            "by_engine": {k: summarize(v) for k, v in by_engine.items()},
            "by_question": {k: summarize(v) for k, v in by_question.items()}}


def paired_delta(base: list[dict], cand: list[dict]) -> dict:
    """Pair on (engine, persona, question, sample). Only keys answered in both arms count.
    Delta CI comes from bootstrapping the per-pair differences."""
    def key(r):
        return (r["engine"], r.get("persona_id"), r["question_id"], r.get("sample_idx", 0))

    b = {key(r): r["score"] for r in base if r["metrics"].get("answered")}
    c = {key(r): r["score"] for r in cand if r["metrics"].get("answered")}
    diffs = [c[k] - b[k] for k in b.keys() & c.keys()]
    if not diffs:
        return {"pairs": 0, "delta": 0.0, "ci": [0.0, 0.0], "significant": False, "direction": "none"}
    lo, hi = bootstrap_ci(diffs)
    return {"pairs": len(diffs), "delta": round(mean(diffs), 4), "ci": [round(lo, 4), round(hi, 4)],
            "significant": lo > 0 or hi < 0,
            "direction": "up" if lo > 0 else "down" if hi < 0 else "inconclusive"}
