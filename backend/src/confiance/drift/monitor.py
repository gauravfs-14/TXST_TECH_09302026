"""Engine drift detection.

A fixed canary panel is run against each configured engine on a schedule (native mode, i.e. what real
users get). We compare against a stored baseline fingerprint and alert on:

  * model_changed      - the model id the API reports differs (silent alias re-pointing)
  * model_missing      - the configured model no longer appears in the provider's model list (deprecation)
  * api_shape_changed  - response fields/blocks appeared or disappeared (API change)
  * behavior_shift     - search-use rate, citation rate or answer length moved beyond thresholds
  * error_rate         - canaries failing where they used to succeed

Baselines are only replaced when a human acknowledges drift (`accept_baseline`), so a slow change
can't quietly become the new normal.
"""

import statistics
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select

from .. import audit, notify
from ..config import get_settings
from ..context import submit
from ..db import session_scope
from ..engines import Turn, build_engine
from ..models import DriftBaseline, DriftCheck
from ..sim.stats import wilson

# Questions that require fresh web information so search/citation behaviour is exercised.
CANARY_PROMPTS = [
    "What are the most recent stable release versions of Python and Node.js? Cite sources.",
    "Who won the most recent FIFA World Cup, and where was the final played? Cite sources.",
    "What is the current Federal Reserve target range for the federal funds rate? Cite sources.",
    "List three well-known open-source vector databases and one key feature of each. Cite sources.",
    "What does the acronym GEO mean in the context of AI search, and how does it differ from SEO?",
]

TH_RATE = 0.4   # absolute change in a rate that we call a shift (with CI non-overlap)
TH_LEN = 0.5    # relative change in median answer length


def _fingerprint(engine_name: str, model: str, samples: int) -> dict:
    eng = build_engine(engine_name, model)
    answers = []
    with ThreadPoolExecutor(4) as pool:
        futs = [submit(pool, eng.run_real, [Turn("user", p)]) for p in CANARY_PROMPTS for _ in range(samples)]
        answers = [f.result() for f in futs]
    ok = [a for a in answers if not a.error]
    try:
        models = eng.list_models()
    except Exception as e:
        models = None
        list_err = str(e)[:200]
    fp = {
        "n": len(answers), "errors": len(answers) - len(ok),
        "error_samples": sorted({a.error[:120] for a in answers if a.error})[:3],
        "resolved_models": sorted({a.model_id for a in ok if a.model_id}),
        "shape": sorted(set().union(*[set(a.raw_shape) for a in ok])) if ok else [],
        "search_use_rate": (sum(1 for a in ok if a.queries) / len(ok)) if ok else 0.0,
        "citation_rate": (sum(1 for a in ok if a.citations) / len(ok)) if ok else 0.0,
        "median_chars": statistics.median([len(a.text) for a in ok]) if ok else 0,
        "n_ok": len(ok),
        "model_listed": (model in models) if models is not None and model else None,
        "list_error": None if models is not None else list_err,
    }
    return fp


def compare(base: dict, cur: dict, model: str) -> list[dict]:
    f = []
    if cur["n_ok"] == 0:
        f.append({"kind": "error_rate", "severity": "critical",
                  "detail": f"all {cur['n']} canaries failed: {cur['error_samples']}"})
        return f
    if set(cur["resolved_models"]) != set(base["resolved_models"]):
        f.append({"kind": "model_changed", "severity": "warning",
                  "detail": f"reported model ids changed {base['resolved_models']} -> {cur['resolved_models']}"})
    if cur["model_listed"] is False and base.get("model_listed") is not False:
        f.append({"kind": "model_missing", "severity": "critical",
                  "detail": f"{model} is no longer in the provider's model list (deprecated or renamed)"})
    added, removed = set(cur["shape"]) - set(base["shape"]), set(base["shape"]) - set(cur["shape"])
    if added or removed:
        f.append({"kind": "api_shape_changed", "severity": "warning",
                  "detail": f"response fields added={sorted(added)} removed={sorted(removed)}"})
    for key in ("search_use_rate", "citation_rate"):
        b_lo, b_hi = wilson(round(base[key] * base["n_ok"]), base["n_ok"])
        c_lo, c_hi = wilson(round(cur[key] * cur["n_ok"]), cur["n_ok"])
        if abs(cur[key] - base[key]) >= TH_RATE and (c_lo > b_hi or c_hi < b_lo):
            f.append({"kind": "behavior_shift", "severity": "warning",
                      "detail": f"{key} moved {base[key]:.2f} -> {cur[key]:.2f}"})
    if base["median_chars"] and abs(cur["median_chars"] - base["median_chars"]) / base["median_chars"] >= TH_LEN:
        f.append({"kind": "behavior_shift", "severity": "info",
                  "detail": f"median answer length {base['median_chars']:.0f} -> {cur['median_chars']:.0f} chars"})
    base_err, cur_err = base["errors"] / max(base["n"], 1), cur["errors"] / max(cur["n"], 1)
    if cur_err - base_err >= 0.3:
        f.append({"kind": "error_rate", "severity": "critical",
                  "detail": f"canary error rate {base_err:.0%} -> {cur_err:.0%}: {cur['error_samples']}"})
    return f


def check_engine(engine_name: str, model: str) -> dict:
    samples = get_settings().drift_canary_samples
    try:
        cur = _fingerprint(engine_name, model, samples)
    except Exception as e:
        cur = {"n": 0, "errors": 0, "n_ok": 0, "error_samples": [f"{type(e).__name__}: {e}"[:200]],
               "resolved_models": [], "shape": [], "search_use_rate": 0, "citation_rate": 0, "median_chars": 0,
               "model_listed": None, "list_error": None}
    with session_scope() as s:
        base = s.scalars(select(DriftBaseline).where(DriftBaseline.engine == engine_name, DriftBaseline.model == model)
                         .order_by(DriftBaseline.id.desc())).first()
        if base is None:
            if cur["n_ok"] == 0:
                status, findings = "error", [{"kind": "error_rate", "severity": "critical",
                                              "detail": f"could not establish baseline: {cur['error_samples']}"}]
            else:
                s.add(DriftBaseline(engine=engine_name, model=model, fingerprint=cur))
                status, findings = "baseline", []
        else:
            findings = compare(base.fingerprint, cur, model)
            status = "drift" if findings else "ok"
        s.add(DriftCheck(engine=engine_name, model=model, status=status, findings=findings, observed=cur))
    audit.record("drift.checked", "drift_monitor", {"engine": engine_name, "model": model, "status": status,
                                                    "findings": findings})
    for fd in findings:
        notify.alert(f"drift.{fd['kind']}", fd["severity"], f"[{engine_name}] {fd['kind']}: {model}", fd["detail"])
    return {"engine": engine_name, "model": model, "status": status, "findings": findings}


def check_all(engines: list[dict]) -> list[dict]:
    seen, out = set(), []
    for e in engines:
        key = (e["name"], e.get("model") or get_settings().engine_models.get(e["name"], ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(check_engine(*key))
    return out


def accept_baseline(engine_name: str, model: str, actor: str = "user") -> None:
    """Human acknowledges the new behavior: the latest observation becomes the baseline."""
    with session_scope() as s:
        last = s.scalars(select(DriftCheck).where(DriftCheck.engine == engine_name, DriftCheck.model == model)
                         .order_by(DriftCheck.id.desc())).first()
        if last is None or not last.observed.get("n_ok"):
            raise ValueError("no successful observation to accept")
        s.add(DriftBaseline(engine=engine_name, model=model, fingerprint=last.observed))
    audit.record("drift.baseline_accepted", actor, {"engine": engine_name, "model": model})
