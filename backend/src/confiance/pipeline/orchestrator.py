"""The optimization pipeline as a resumable state machine.

  requirements -> research -> baseline -> loop (draft -> test -> decide, up to a hard limit) -> finalize
      -> awaiting_approval -> (human approves) -> deploy -> awaiting_live -> awaiting_measure -> measure -> done

  requirements  what to measure: brand questions and product questions, pretend customers, the knowledge base
  research      real search results for each question, who wins, what their pages do, how well the site covers it
  baseline      the "before" test, with the client's pages placed in the (sandboxed) search results
  loop          the optimizer drafts changes; the search tool's results are rewritten to contain them; the same
                questions are asked again; the result decides whether to loop again. `max_loops` is a hard cap.
  finalize      pick the best loop, write the improvement plan and the report

Human gates: approval (mandatory - nothing ships without it) and, for draft PRs / CMS drafts, confirmation that
the change went live. Every stage persists its output, so a crash or restart resumes at the failed stage instead
of re-spending AI requests on finished ones.
"""

import hashlib
import json
import statistics
from collections import Counter
from collections.abc import Callable
from datetime import timedelta

from sqlalchemy import select

from .. import activity, audit, brief as briefs, kb, notify, snapshots
from .. import settings as settings_mod
from ..brief import TargetQuestion
from ..config import get_settings
from ..context import scope
from ..db import session_scope, utcnow
from ..deploy.service import deploy_run
from ..models import ChangeProposal, Deployment, Page, Persona, Product, Project, Run, RunLoop
from ..optimizer.agent import Optimizer
from ..research.run import run_research
from ..search.base import SearchCache
from ..search.providers import build_provider
from ..sim import personas as personas_mod, products as products_mod, stats
from ..sim.runner import PromptSet, build_sandbox, load_rows, run_batch
from ..sim.verdict import verdict as make_verdict
from ..textutil import domain_of, html_to_text
from . import plans

# Tests replace these to inject an offline search corpus and a fake page fetcher.
provider_factory: Callable = lambda: build_provider()
html_fetcher: Callable = kb.fetch_html


class PipelineError(RuntimeError):
    pass


STAGES = ["created", "requirements", "research", "baseline", "loop", "finalize", "awaiting_approval",
          "deploy", "awaiting_live", "awaiting_measure", "measure", "done"]
# Runs that started before the loop pipeline existed resume at the closest new stage.
_LEGACY = {"kb": "requirements", "prompts": "requirements", "optimize": "baseline", "candidate": "baseline", "evaluate": "baseline"}


def start_run(project_id: int, intensity: str | None = None, overrides: dict | None = None) -> int:
    """overrides: optional per-round settings (max_loops, min_gain, patience, exposure_rank, track, ...)."""
    with session_scope() as s:
        project = s.get(Project, project_id)
        if project.current_brief_version == 0:
            raise PipelineError("project has no brief; complete onboarding first")
        open_run = s.scalars(select(Run).where(Run.project_id == project_id, Run.status.in_(["running", "pending"]))).first()
        if open_run:
            raise PipelineError("A round is still in progress. Stop it first if you want to start over.")
        want = settings_mod.for_project(project, overrides or {})["track"]
        if "brand" not in want and not s.scalars(select(Product).where(Product.project_id == project_id, Product.active)).first():
            raise PipelineError("There are no products to test yet. Add or find your products first, or include your brand questions in this round.")
        # A round still waiting for approval is replaced by the new one (its unapproved suggestions are discarded).
        stale = list(s.scalars(select(Run).where(Run.project_id == project_id, Run.stage == "awaiting_approval", Run.status == "waiting")))
        replaced = []
        for old in stale:
            old.status = "cancelled"
            for cp in s.scalars(select(ChangeProposal).where(ChangeProposal.run_id == old.id, ChangeProposal.status == "candidate")):
                cp.status = "rejected"
            replaced.append(old.id)
        n = len(list(s.scalars(select(Run).where(Run.project_id == project_id))))
        cfg = settings_mod.for_project(project, {**(overrides or {}), **({"plan": intensity} if intensity else {})})
        if cfg["plan"] not in plans.PLANS:
            cfg["plan"] = plans.DEFAULT_PLAN
        run = Run(project_id=project_id, iteration=n + 1, brief_version=project.current_brief_version, status="pending",
                  summary={"plan": cfg["plan"], "config": cfg})
        s.add(run)
        s.flush()
        rid = run.id
    audit.record("run.created", "user", {"iteration": n + 1, "config": cfg, "replaced_runs": replaced}, project_id=project_id, run_id=rid)
    return rid


def _set(run_id: int, **kw) -> None:
    with session_scope() as s:
        run = s.get(Run, run_id)
        summary = dict(run.summary)
        summary.update(kw.pop("summary", {}))
        run.summary = summary
        for k, v in kw.items():
            setattr(run, k, v)


def _claim(run_id: int) -> tuple[int, str, int]:
    with session_scope() as s:
        run = s.get(Run, run_id)
        if run.status == "running":
            raise PipelineError("run is already being advanced")
        if run.status == "done":
            raise PipelineError("run already finished")
        run.status = "running"
        run.error = None
        run.stage = _LEGACY.get(run.stage, run.stage)
        return run.project_id, run.stage, run.brief_version


def advance(run_id: int) -> dict:
    """Advance until a human gate, a scheduled wait, completion, or failure. Safe to call repeatedly."""
    project_id, stage, brief_version = _claim(run_id)
    activity.clear_cancel(run_id)  # starting (or resuming) a round is a fresh intent; an old Stop must not leak in
    with scope(project_id, run_id):
        try:
            while True:
                activity.set_stage(run_id, stage)
                if stage in _STAGE_TEXT:
                    activity.emit(_STAGE_TEXT[stage], "step")
                nxt = _STEP[stage](run_id, project_id, brief_version)
                if nxt is None:  # gate / wait: stage unchanged, status waiting
                    _set(run_id, status="waiting")
                    break
                stage = nxt
                _set(run_id, stage=stage)
                audit.record("run.stage", "orchestrator", {"stage": stage})
                if stage == "done":
                    _set(run_id, status="done")
                    break
        except activity.RunCancelled:
            activity.emit("Stopped.", "done")
            _set(run_id, status="cancelled", error=None)
            audit.record("run.cancelled", "user", {"stage": stage})
            return get_status(run_id)
        except Exception as e:
            activity.emit(f"Something went wrong: {str(e)[:160]}", "warn")
            _set(run_id, status="failed", error=f"{type(e).__name__}: {e}")
            audit.record("run.failed", "orchestrator", {"stage": stage, "error": str(e)})
            notify.alert("run.failed", "warning", f"Run {run_id} failed at stage {stage}", str(e), project_id)
            raise
    activity.emit("Finished this stage. Waiting for you." if stage in ("awaiting_approval", "awaiting_live", "awaiting_measure") else "Done.", "done")
    return get_status(run_id)


_STAGE_TEXT = {"requirements": "Working out what to measure and learning about your business",
               "research": "Researching how search and AI assistants see you today",
               "baseline": "Testing today's pages (the baseline)",
               "loop": "Drafting improvements and testing them",
               "finalize": "Choosing the best draft and writing your plan and report"}


def cancel_run(run_id: int, actor: str = "user") -> str:
    """Stop a running round, or discard one that is waiting. Returns 'stopping' or 'cancelled'."""
    with session_scope() as s:
        run = s.get(Run, run_id)
        if run is None:
            raise PipelineError("round not found")
        status, project_id = run.status, run.project_id
    if status in ("done", "cancelled"):
        raise PipelineError("this round is already finished")
    if status == "running" and activity.snapshot(run_id)["known"]:
        activity.request_cancel(run_id)  # the running job stops at its next step
        audit.record("run.cancel_requested", actor, {}, project_id=project_id, run_id=run_id)
        return "stopping"
    with session_scope() as s:  # not executing in this process (waiting, failed, or left over from a crash)
        run = s.get(Run, run_id)
        run.status, run.error = "cancelled", None
        for cp in s.scalars(select(ChangeProposal).where(ChangeProposal.run_id == run_id, ChangeProposal.status == "candidate")):
            cp.status = "rejected"
    audit.record("run.cancelled", actor, {"was": status}, project_id=project_id, run_id=run_id)
    return "cancelled"


def recover_interrupted() -> int:
    """A restart kills a running job mid-stage but leaves its status 'running', which would block resuming.
    Mark those runs as interrupted (the person sees 'Try again'); finished stages are kept."""
    with session_scope() as s:
        stuck = list(s.scalars(select(Run).where(Run.status == "running")))
        for r in stuck:
            r.status, r.error = "failed", "This round was interrupted when the app restarted. Nothing is lost. Press “Try again” to carry on where it stopped."
        ids = [r.id for r in stuck]
    for rid in ids:
        audit.record("run.interrupted", "orchestrator", {"stage_kept": True}, run_id=rid)
    return len(ids)


def get_status(run_id: int) -> dict:
    with session_scope() as s:
        r = s.get(Run, run_id)
        return {"id": r.id, "project_id": r.project_id, "iteration": r.iteration, "stage": r.stage,
                "status": r.status, "error": r.error, "summary": r.summary,
                "measure_after": r.measure_after.isoformat() if r.measure_after else None,
                "created_at": r.created_at.isoformat()}


# ---- stages ---------------------------------------------------------------------------------------

def _plan(run_id: int) -> dict:
    with session_scope() as s:
        return plans.get(s.get(Run, run_id).summary.get("plan"))


def _cfg(run_id: int) -> dict:
    with session_scope() as s:
        return dict(s.get(Run, run_id).summary.get("config") or settings_mod.clamp({}))


def _summary(run_id: int) -> dict:
    with session_scope() as s:
        return dict(s.get(Run, run_id).summary or {})


def _load(project_id: int, brief_version: int):
    with session_scope() as s:
        project = s.get(Project, project_id)
        _, brief = briefs.get(s, project_id, brief_version)
        card = kb.card(s, project)
        s.expunge(project)
    return project, brief, card


def _st_created(run_id, project_id, bv):
    return "requirements"


def _reuse_prompts(project_id: int, run_id: int, key: str) -> dict | None:
    """The same questions and pretend customers as an earlier round: fewer AI requests, and rounds stay comparable."""
    with session_scope() as s:
        for r in s.scalars(select(Run).where(Run.project_id == project_id, Run.id < run_id).order_by(Run.id.desc()).limit(20)):
            if (r.summary or {}).get("prompts_key") == key and r.summary.get("prompts"):
                return r.summary["prompts"]
    return None


def _st_requirements(run_id, project_id, bv):
    project, brief, card = _load(project_id, bv)
    cfg, pl = _cfg(run_id), _plan(run_id)
    activity.emit("Learning about your business", "info")
    with session_scope() as s:
        try:
            kb.build(s, s.get(Project, project_id))  # skipped when the pages haven't changed
        except ValueError as e:
            raise PipelineError("We haven't read your website yet. Add your site first.") from e
        card = kb.card(s, s.get(Project, project_id))
    qs: list[dict] = []
    if "brand" in cfg["track"]:
        qs += [{"id": q.id, "text": q.text, "track": "brand"} for q in brief.target_questions[:pl["max_questions"]]]
        if len(brief.target_questions) > pl["max_questions"]:
            activity.emit(f"This round uses your first {pl['max_questions']} of {len(brief.target_questions)} brand questions.", "info")
    if "products" in cfg["track"]:
        with session_scope() as s:
            products_mod.generate_queries(s, project_id, project.name, card)
            prods = list(s.scalars(select(Product).where(Product.project_id == project_id, Product.active)))
            sel = products_mod.select_queries(prods, pl["max_product_queries"])
            names = {p.id: p.name for p in prods}
        qs += [{"id": q["id"], "text": q["text"], "track": "product", "product_id": q["product_id"], "product": names.get(q["product_id"], "")} for q in sel]
        if not sel:
            activity.emit("No products are being tracked yet, so this round covers brand questions only.", "info")
    if not qs:
        raise PipelineError("Add at least one question or product to track, then try again.")

    n_personas = pl["personas"]
    key = hashlib.sha1(json.dumps([bv, [q["text"] for q in qs], n_personas]).encode()).hexdigest()[:16]
    prompts = _reuse_prompts(project_id, run_id, key)
    if prompts:
        activity.emit("Reusing the pretend customers and questions from an earlier round, so results stay comparable.", "info")
    else:
        brief_sel = brief.model_copy(update={"target_questions": [TargetQuestion(id=q["id"], text=q["text"]) for q in qs]})
        with session_scope() as s:
            active = list(s.scalars(select(Persona).where(Persona.project_id == project_id, Persona.active)))[:n_personas]
            if len(active) < n_personas:
                active = personas_mod.generate(s, project, brief_sel, card, n=n_personas)
            for p in active:
                s.expunge(p)
        prompts = {"canonical": {q["id"]: q["text"] for q in qs}}
        activity.set_total(len(active))
        for p in active:
            prompts[str(p.id)] = personas_mod.phrase_prompts(p, brief_sel)
            activity.tick()
            activity.emit(f"Pretend customer “{p.name}” wrote their version of your questions", "info")
    _set(run_id, summary={"prompts": prompts, "prompts_key": key, "questions": qs, "question_ids": [q["id"] for q in qs]})
    audit.record("requirements.set", "orchestrator", {"brand_questions": sum(q["track"] == "brand" for q in qs),
                                                       "product_questions": sum(q["track"] == "product" for q in qs), "personas": n_personas})
    return "research"


def _prompt_set(run_id: int) -> PromptSet:
    raw = _summary(run_id)["prompts"]
    return PromptSet({None if k == "canonical" else int(k): v for k, v in raw.items()})


def _shared_cache(run_id: int) -> SearchCache:
    # Not persisted: all tests in one round share real search results only within a process. A resumed run may
    # re-search, which is why baseline and every loop go through the same cache whenever they can.
    return _CACHES.setdefault(run_id, SearchCache())


_CACHES: dict[int, SearchCache] = {}


def _st_research(run_id, project_id, bv):
    project, brief, card = _load(project_id, bv)
    qs = _summary(run_id)["questions"]
    with session_scope() as s:
        site_texts = {}
        for p in s.scalars(select(Page).where(Page.project_id == project_id, Page.kind == "page")):
            html = snapshots.live_content(s, p)
            if html:
                site_texts[p.url] = html_to_text(html)[1]
        product_urls = {}
        for q in qs:
            if q.get("product_id"):
                pr = s.get(Product, q["product_id"])
                if pr and pr.url:
                    product_urls[q["id"]] = pr.url
    res = run_research(provider_factory(), project.domain, project.name, [(q["id"], q["text"]) for q in qs], site_texts,
                       product_urls=product_urls, fetch_html=html_fetcher, on_progress=lambda m: activity.emit(m, "tool"))
    sm = res["summary"]
    _set(run_id, summary={"research": res, "findability": res["queries"] + ([res["brand"]] if res.get("brand") else []),
                          "findability_summary": {"questions_checked": sm["checked"], "questions_found": sm["found"], "brand_found": sm["brand_found"]}})
    activity.emit(f"Search shows your site for {sm['found']} of {sm['checked']} questions. {sm['needs_content']} would need new content.", "info")
    return "baseline"


def _st_baseline(run_id, project_id, bv):
    project, brief, card = _load(project_id, bv)
    cfg, pl = _cfg(run_id), _plan(run_id)
    # Your pages are placed among the (real) search results, at the same position in every test in this round,
    # so what's measured is how well the content works when found. Real findability was measured in research.
    with session_scope() as s:
        sb = build_sandbox(s, project, provider=provider_factory(), cache=_shared_cache(run_id), expose=True, expose_rank=cfg["exposure_rank"])
    bid = run_batch(project, brief, run_id, "baseline", "controlled", _prompt_set(run_id), sandbox=sb, kb_card=card,
                    samples=pl["samples"], max_steps=pl["steps"])
    _set(run_id, summary={"baseline_batch": bid})
    return "loop"


def _history(project_id: int, run_id: int) -> str:
    with session_scope() as s:
        prev = s.scalars(select(Run).where(Run.project_id == project_id, Run.id < run_id, Run.status == "done")
                         .order_by(Run.id.desc())).first()
        if not prev:
            return ""
        return json.dumps({"previous_round": prev.iteration, "sandbox_evaluation": prev.summary.get("evaluation"),
                           "real_world_result": prev.summary.get("real_world")}, default=str)


# ---- the loop --------------------------------------------------------------------------------------------

FUNNEL_KEYS = ("exposed", "fetched", "used_page", "mentioned", "cited", "product_mentioned", "product_cited")


def _funnel(rows: list[dict]) -> dict:
    n = max(len(rows), 1)
    return {k: round(sum(1 for r in rows if r["metrics"].get(k)) / n, 3) for k in FUNNEL_KEYS} | {"n": len(rows), "score": round(statistics.mean([r["score"] for r in rows]), 3) if rows else 0.0}


def _loop_rows(run_id: int) -> list[dict]:
    with session_scope() as s:
        return [{"id": l.id, "n": l.n, "status": l.status, "proposal_ids": list(l.proposal_ids or []), "batch_id": l.batch_id,
                 "delta": dict(l.delta or {}), "metrics": dict(l.metrics or {}), "decision": l.decision or "", "notes": l.notes or ""}
                for l in s.scalars(select(RunLoop).where(RunLoop.run_id == run_id).order_by(RunLoop.n))]


def _feedback(base_rows: list[dict], cand_rows: list[dict], texts: dict[str, str]) -> dict:
    """What the drafter needs to improve: per tested question, before vs now, what the answer used instead."""
    per = []
    for qid in sorted({r["question_id"] for r in cand_rows}):
        b = [r for r in base_rows if r["question_id"] == qid]
        c = [r for r in cand_rows if r["question_id"] == qid]
        cited = Counter(domain_of(u) for r in c for u in r.get("citations", []) if u)
        worst = min(c, key=lambda r: r["score"]) if c else None
        per.append({"question_id": qid, "question": texts.get(qid, ""), "before": _funnel(b), "now": _funnel(c),
                    "score_change": round(_funnel(c)["score"] - _funnel(b)["score"], 3),
                    "answer_relied_on": [d for d, _ in cited.most_common(4)], "sample_answer_now": (worst["answer"] or "")[:400] if worst else ""})
    return {"per_question": per, "not_improved": [p["question_id"] for p in per if p["score_change"] <= 0.02]}


def _decide(loops: list[dict], n: int, cfg: dict) -> str:
    """continue | stop:max_loops | stop:plateau. Progress = beating the best score so far by at least min_gain."""
    best, streak = 0.0, 0
    for l in loops:
        d = l["delta"].get("overall", {}).get("delta", 0.0)
        if d - best >= cfg["min_gain"]:
            best, streak = d, 0
        else:
            streak += 1
    if n >= cfg["max_loops"]:
        return "stop:max_loops"
    if streak >= cfg["patience"]:
        return "stop:plateau"
    return "continue"


def _finish_loop(loop_id: int, **kw) -> None:
    with session_scope() as s:
        l = s.get(RunLoop, loop_id)
        for k, v in kw.items():
            setattr(l, k, v)


def _run_loop(run_id: int, project_id: int, bv: int, n: int, cfg: dict) -> None:
    project, brief, card = _load(project_id, bv)
    pl = _plan(run_id)
    sm = _summary(run_id)
    activity.set_loop(run_id, n, cfg["max_loops"], "draft")
    activity.emit(f"Loop {n} of up to {cfg['max_loops']}: drafting changes" if n == 1 else f"Loop {n} of up to {cfg['max_loops']}: improving the draft using the test results", "step")
    with session_scope() as s:
        row = s.scalars(select(RunLoop).where(RunLoop.run_id == run_id, RunLoop.n == n)).first()
        if row is None:
            row = RunLoop(run_id=run_id, n=n, status="drafting")
            s.add(row)
            s.flush()
        loop_id, status = row.id, row.status
    prior = [l for l in _loop_rows(run_id) if l["n"] < n]
    prev = prior[-1] if prior else None

    if status == "drafting":
        with session_scope() as s:
            carry = {cp.page_id: cp.id for cp in s.scalars(select(ChangeProposal).where(ChangeProposal.id.in_(prev["proposal_ids"] if prev else [])))}
        opt = Optimizer(project_id, run_id, bv, sm.get("baseline_batch"), provider_factory(), loop=n, cfg=cfg, carry=carry,
                        feedback=(prev or {}).get("metrics", {}).get("feedback"))
        if n == 1:
            opt.history = _history(project_id, run_id)
        ids = opt.run()
        _set(run_id, summary={"optimizer_summary": opt.summary, "proposals": ids})
        if not ids:
            _finish_loop(loop_id, status="done", proposal_ids=[], decision="stop:no_changes", notes=opt.summary)
            return
        if n > 1 and not opt.touched:  # the drafter had nothing to improve: converged
            _finish_loop(loop_id, status="done", proposal_ids=ids, batch_id=prev["batch_id"], delta=prev["delta"],
                         metrics={**prev["metrics"], "carried_over": True}, decision="stop:converged", notes=opt.summary)
            return
        _finish_loop(loop_id, status="testing", proposal_ids=ids, notes=opt.summary)
    else:
        with session_scope() as s:
            ids = list(s.get(RunLoop, loop_id).proposal_ids)

    # ---- test: rewrite the search tool's results to contain the draft, and ask the same questions again
    activity.set_loop(run_id, n, cfg["max_loops"], "test")
    with session_scope() as s:
        props = list(s.scalars(select(ChangeProposal).where(ChangeProposal.id.in_(ids))))
        overrides = {cp.page_id: snapshots.version_content(s, cp.candidate_version_id) for cp in props if cp.candidate_version_id}
        sb = build_sandbox(s, project, overrides, provider=provider_factory(), cache=_shared_cache(run_id), expose=True, expose_rank=cfg["exposure_rank"])
        targets = {q for cp in props for q in (cp.target_questions or [])}
    all_ids = set(sm.get("question_ids") or [])
    tested = sorted(targets & all_ids)
    qids = tested if tested and set(tested) != all_ids else None
    if qids:
        activity.emit(f"Only re-asking the {len(qids)} of {len(all_ids)} questions this draft is meant to help. The others can't be affected.", "info")
    bid = run_batch(project, brief, run_id, "candidate", "controlled", _prompt_set(run_id), sandbox=sb, kb_card=card,
                    samples=pl["samples"], max_steps=pl["steps"], question_ids=qids)

    # ---- evaluate against the baseline
    with session_scope() as s:
        base, cand = load_rows(s, sm["baseline_batch"]), load_rows(s, bid)
    tested_ids = sorted({r["question_id"] for r in cand})
    base_t = [r for r in base if r["question_id"] in set(tested_ids)]
    overall = stats.paired_delta(base, cand)
    by_track = {t: stats.paired_delta([r for r in base if products_mod.track_of(r["question_id"]) == t], [r for r in cand if products_mod.track_of(r["question_id"]) == t])
                for t in ("brand", "product")}
    texts = {q["id"]: q["text"] for q in sm.get("questions", [])}
    verdict = make_verdict(overall, cfg["min_effect"])
    feedback = _feedback(base, cand, texts)
    loops = _loop_rows(run_id)
    loops = [l for l in loops if l["n"] != n] + [{"n": n, "delta": {"overall": overall}}]
    decision = _decide(sorted(loops, key=lambda l: l["n"]), n, cfg)
    _finish_loop(loop_id, status="done", batch_id=bid, delta={"overall": overall, "by_track": by_track, "verdict": verdict},
                 metrics={"tested_questions": tested_ids, "funnel_base": _funnel(base_t), "funnel_now": _funnel(cand), "feedback": feedback}, decision=decision)
    activity.emit(f"Loop {n} result: {verdict['text']}", "step")
    audit.record("loop.done", "orchestrator", {"loop": n, "delta": overall, "verdict": verdict["label"], "decision": decision}, project_id=project_id, run_id=run_id)


def _st_loop(run_id, project_id, bv):
    cfg = _cfg(run_id)
    while True:
        loops = _loop_rows(run_id)
        last = loops[-1] if loops else None
        if last and last["status"] == "done":
            if last["decision"].startswith("stop"):
                break
            n = last["n"] + 1
        elif last:
            n = last["n"]  # resume a loop that was interrupted
        else:
            n = 1
        if n > cfg["max_loops"]:
            break
        _run_loop(run_id, project_id, bv, n, cfg)
    return "finalize"


def _st_finalize(run_id, project_id, bv):
    cfg, sm = _cfg(run_id), _summary(run_id)
    loops = [l for l in _loop_rows(run_id) if l["status"] == "done"]
    scored = [l for l in loops if l["proposal_ids"] and l["batch_id"] and l["delta"].get("overall")]
    best = max(scored, key=lambda l: (l["delta"]["overall"]["delta"], -l["n"])) if scored else None
    reason = loops[-1]["decision"] if loops else "stop:no_changes"
    with session_scope() as s:
        keep = set(best["proposal_ids"]) if best else set()
        for cp in s.scalars(select(ChangeProposal).where(ChangeProposal.run_id == run_id, ChangeProposal.status.in_(["candidate", "superseded"]))):
            if cp.id in keep:  # the best loop may not be the last one, so its proposals may have been superseded since
                cp.status = "candidate"
                cp.guard_report = {**(cp.guard_report or {}), "superseded": False}
            else:
                cp.status = "superseded"  # an earlier or weaker draft, replaced by the best loop's set
    if not best:
        _set(run_id, summary={"evaluation": {"recommendation": "no_changes", "verdict": {"label": "no_changes", "recommendation": "review", "text": "No safe changes could be drafted for these questions."},
                                             "loops": [], "stop_reason": reason}})
    else:
        d = best["delta"]
        per_q = {}
        for q in best["metrics"].get("tested_questions", []):
            per_q[q] = next((p["score_change"] for p in best["metrics"]["feedback"]["per_question"] if p["question_id"] == q), 0.0)
        ev = {"overall": d["overall"], "by_track": d.get("by_track", {}), "verdict": d["verdict"], "recommendation": d["verdict"]["recommendation"],
              "per_question": per_q, "questions_retested": best["metrics"].get("tested_questions"), "best_loop": best["n"], "stop_reason": reason,
              "loops": [{"n": l["n"], "delta": l["delta"].get("overall", {}).get("delta"), "verdict": l["delta"].get("verdict", {}).get("label"), "decision": l["decision"],
                         "proposals": len(l["proposal_ids"])} for l in loops],
              "note": "Sandbox estimate: your pages are placed among real search results before and after. Directional evidence, not a guarantee of live results."}
        _set(run_id, summary={"evaluation": ev, "candidate_batch": best["batch_id"], "candidate_questions": best["metrics"].get("tested_questions")})
    audit.record("evaluation.done", "evaluator", {"best_loop": best["n"] if best else None, "stop_reason": reason,
                                                   "verdict": (best["delta"]["verdict"]["label"] if best else "no_changes")}, project_id=project_id, run_id=run_id)
    # The plan and report never block the round: if the AI part fails, the deterministic plan is still there.
    try:
        from ..plan import generator as plan_gen
        activity.emit("Writing your improvement plan", "step")
        plan_gen.generate(run_id)
        from .. import reports
        activity.emit("Writing the report summary", "step")
        reports.write_narrative(run_id)
    except Exception as e:
        activity.emit(f"The plan could only be partly written ({str(e)[:100]}).", "warn")
        audit.record("plan.partial", "orchestrator", {"error": str(e)[:300]}, project_id=project_id, run_id=run_id)
    _CACHES.pop(run_id, None)
    with session_scope() as s:
        ev = s.get(Run, run_id).summary.get("evaluation", {})
    notify.alert("run.awaiting_approval", "info", f"Round {run_id} is ready for review", ev.get("verdict", {}).get("text", ""), project_id)
    return "awaiting_approval"


def _st_awaiting_approval(run_id, project_id, bv):
    with session_scope() as s:
        approved = s.scalars(select(ChangeProposal).where(ChangeProposal.run_id == run_id,
                                                          ChangeProposal.status.in_(["approved", "deployed"]))).first()
        pending = s.scalars(select(ChangeProposal).where(ChangeProposal.run_id == run_id,
                                                         ChangeProposal.status == "candidate")).first()
    if approved:
        return "deploy"
    if pending:
        return None  # wait for a human
    return "done"  # everything rejected


def _st_deploy(run_id, project_id, bv):
    project, brief, card = _load(project_id, bv)
    # Native pre-deploy measurement: the real-world "before" for the post-deploy comparison.
    pl = _plan(run_id)
    pre = run_batch(project, brief, run_id, "live_pre", "real", _prompt_set(run_id), sandbox=None, kb_card=card,
                    samples=max(1, pl["samples"] - 1), max_steps=pl["steps"])
    dep_id = deploy_run(run_id, actor="orchestrator")
    _set(run_id, summary={"live_pre_batch": pre, "deployment_id": dep_id})
    return "awaiting_live"


def _st_awaiting_live(run_id, project_id, bv):
    with session_scope() as s:
        dep = s.get(Deployment, s.get(Run, run_id).summary["deployment_id"])
        status = dep.status
    if status == "failed":
        raise PipelineError("deployment failed; see deployment details")
    if status != "applied":
        return None  # waiting for merge/publish confirmation
    _set(run_id, measure_after=utcnow() + timedelta(hours=get_settings().post_deploy_measure_after_hours))
    return "awaiting_measure"


def _st_awaiting_measure(run_id, project_id, bv):
    with session_scope() as s:
        due = s.get(Run, run_id).measure_after
    return "measure" if due and utcnow() >= due else None


def _st_measure(run_id, project_id, bv):
    project, brief, card = _load(project_id, bv)
    pl = _plan(run_id)
    post = run_batch(project, brief, run_id, "live_post", "real", _prompt_set(run_id), sandbox=None, kb_card=card,
                     samples=max(1, pl["samples"] - 1), max_steps=pl["steps"])
    with session_scope() as s:
        sm = s.get(Run, run_id).summary
        delta = stats.paired_delta(load_rows(s, sm["live_pre_batch"]), load_rows(s, post))
    _set(run_id, summary={"live_post_batch": post, "real_world": delta})
    notify.alert("run.measured", "info", f"Run {run_id}: real-world result",
                 f"Visibility delta {delta['delta']:+.3f} (CI {delta['ci']}, {delta['direction']})", project_id)
    return "done"


_STEP = {"created": _st_created, "requirements": _st_requirements, "research": _st_research, "baseline": _st_baseline,
         "loop": _st_loop, "finalize": _st_finalize, "awaiting_approval": _st_awaiting_approval, "deploy": _st_deploy, "awaiting_live": _st_awaiting_live,
         "awaiting_measure": _st_awaiting_measure, "measure": _st_measure, "done": lambda *a: "done"}


# ---- human actions --------------------------------------------------------------------------------

def decide(run_id: int, proposal_ids: list[int], approve: bool, actor: str = "user") -> None:
    with session_scope() as s:
        for pid in proposal_ids:
            cp = s.get(ChangeProposal, pid)
            if cp is None or cp.run_id != run_id:
                raise PipelineError(f"proposal {pid} does not belong to run {run_id}")
            if cp.status != "candidate":
                raise PipelineError(f"proposal {pid} is {cp.status}, only guard-passing candidates can be decided")
            cp.status = "approved" if approve else "rejected"
        project_id = s.get(Run, run_id).project_id
    audit.record("proposal.approved" if approve else "proposal.rejected", actor, {"proposal_ids": proposal_ids},
                 project_id=project_id, run_id=run_id)
    # A human decision on a *completed* evaluation may unblock the run.
    with session_scope() as s:
        stage = s.get(Run, run_id).stage
    if stage == "awaiting_approval":
        advance(run_id)
