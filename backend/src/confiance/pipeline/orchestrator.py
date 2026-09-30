"""The optimization loop as a resumable state machine.

created -> kb -> prompts -> baseline -> optimize -> candidate -> evaluate -> awaiting_approval
        -> (human approves) -> deploy -> awaiting_live -> awaiting_measure -> measure -> done

Human gates: approval (mandatory - nothing ships without it) and, for draft PRs / CMS drafts,
confirmation that the change went live. Each stage persists its output, so a crash or restart resumes
at the failed stage instead of re-spending tokens on finished ones.

Iteration N+1 starts from what iteration N learned: its optimizer receives the measured real-world
outcome of the previous deployment.
"""

import json
from collections.abc import Callable
from datetime import timedelta

from sqlalchemy import select

from .. import activity, audit, brief as briefs, kb, notify, snapshots
from ..config import get_settings
from ..context import scope
from ..db import session_scope, utcnow
from ..deploy.service import deploy_run
from ..models import ChangeProposal, Deployment, Persona, Project, Run
from ..optimizer.agent import Optimizer
from ..search.base import SearchCache
from ..search.providers import build_provider
from ..sim import personas as personas_mod, stats
from . import plans
from ..sim import findability
from ..sim.runner import PromptSet, build_sandbox, load_rows, run_batch

# Tests replace this to inject an offline corpus provider.
provider_factory: Callable = lambda: build_provider()


class PipelineError(RuntimeError):
    pass


STAGES = ["created", "kb", "prompts", "baseline", "optimize", "candidate", "evaluate", "awaiting_approval",
          "deploy", "awaiting_live", "awaiting_measure", "measure", "done"]


def start_run(project_id: int, intensity: str | None = None) -> int:
    with session_scope() as s:
        project = s.get(Project, project_id)
        if project.current_brief_version == 0:
            raise PipelineError("project has no brief; complete onboarding first")
        open_run = s.scalars(select(Run).where(Run.project_id == project_id, Run.status.in_(["running", "pending"]))).first()
        if open_run:
            raise PipelineError(f"A round is still in progress. Stop it first if you want to start over.")
        # A round still waiting for approval is replaced by the new one (its unapproved suggestions are discarded).
        stale = list(s.scalars(select(Run).where(Run.project_id == project_id, Run.stage == "awaiting_approval", Run.status == "waiting")))
        replaced = []
        for old in stale:
            old.status = "cancelled"
            for cp in s.scalars(select(ChangeProposal).where(ChangeProposal.run_id == old.id, ChangeProposal.status == "candidate")):
                cp.status = "rejected"
            replaced.append(old.id)
        n = len(list(s.scalars(select(Run).where(Run.project_id == project_id))))
        plan_name = intensity if intensity in plans.PLANS else plans.DEFAULT_PLAN
        run = Run(project_id=project_id, iteration=n + 1, brief_version=project.current_brief_version, status="pending",
                  summary={"plan": plan_name})
        s.add(run)
        s.flush()
        rid = run.id
    audit.record("run.created", "user", {"iteration": n + 1, "plan": plan_name, "replaced_runs": replaced}, project_id=project_id, run_id=rid)
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


_STAGE_TEXT = {"kb": "Reading your website and learning what your business does",
               "prompts": "Creating pretend customers and writing their questions",
               "optimize": "Working out improvements to your pages",
               "evaluate": "Comparing the results before and after"}


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


def _load(project_id: int, brief_version: int):
    with session_scope() as s:
        project = s.get(Project, project_id)
        _, brief = briefs.get(s, project_id, brief_version)
        card = kb.card(s, project)
        s.expunge(project)
    return project, brief, card


def _st_created(run_id, project_id, bv):
    return "kb"


def _st_kb(run_id, project_id, bv):
    with session_scope() as s:
        project = s.get(Project, project_id)
        version = kb.build(s, project)
    _set(run_id, summary={"kb_version": version})
    return "prompts"


def _st_prompts(run_id, project_id, bv):
    project, brief, card = _load(project_id, bv)
    with session_scope() as s:
        n_personas = _plan(run_id)["personas"]
        active = list(s.scalars(select(Persona).where(Persona.project_id == project_id, Persona.active)))[:n_personas]
        if len(active) < n_personas:
            active = personas_mod.generate(s, project, brief, card, n=n_personas)
        for p in active:
            s.expunge(p)
    # A round uses only the first few questions (order = priority), so free allowances go further.
    chosen = brief.target_questions[:_plan(run_id)["max_questions"]]
    brief_sel = brief.model_copy(update={"target_questions": chosen})
    if len(chosen) < len(brief.target_questions):
        activity.emit(f"This round uses your first {len(chosen)} of {len(brief.target_questions)} questions.", "info")
    prompts: dict[str, dict[str, str]] = {"canonical": {q.id: q.text for q in chosen}}
    activity.set_total(len(active))
    for p in active:
        prompts[str(p.id)] = personas_mod.phrase_prompts(p, brief_sel)
        activity.tick()
        activity.emit(f"Pretend customer “{p.name}” wrote their version of your questions", "info")
    _set(run_id, summary={"prompts": prompts, "question_ids": [q.id for q in chosen]})
    audit.record("prompts.generated", "persona_agent", {"personas": len(active), "questions": len(brief.target_questions)})
    return "baseline"


def _prompt_set(run_id: int) -> PromptSet:
    with session_scope() as s:
        raw = s.get(Run, run_id).summary["prompts"]
    return PromptSet({None if k == "canonical" else int(k): v for k, v in raw.items()})


def _shared_cache(run_id: int) -> SearchCache:
    # Not persisted: arms of one run share a cache only within a process. A resumed run may re-search,
    # so the summary records whether pairing happened over identical third-party results.
    return _CACHES.setdefault(run_id, SearchCache())


_CACHES: dict[int, SearchCache] = {}


def _st_baseline(run_id, project_id, bv):
    project, brief, card = _load(project_id, bv)
    provider = provider_factory()
    # 1. Is the site found by real search today? (plain searches, no AI requests)
    activity.emit("Checking whether search finds your website today", "step")
    fi = findability.check(provider, project.domain, project.name, [(q.id, q.text) for q in brief.target_questions])
    _set(run_id, summary={"findability": fi, "findability_summary": findability.summarize(fi)})
    # 2. Practice round with your page guaranteed to be among the results, so we measure how well it works
    #    when found. The same rule applies to the improved round, so the comparison is fair.
    with session_scope() as s:
        sb = build_sandbox(s, project, provider=provider, cache=_shared_cache(run_id), expose=True)
    pl = _plan(run_id)
    bid = run_batch(project, brief, run_id, "baseline", "controlled", _prompt_set(run_id), sandbox=sb, kb_card=card,
                    samples=pl["samples"], max_steps=pl["steps"])
    _set(run_id, summary={"baseline_batch": bid})
    return "optimize"


def _history(project_id: int, run_id: int) -> str:
    with session_scope() as s:
        prev = s.scalars(select(Run).where(Run.project_id == project_id, Run.id < run_id, Run.status == "done")
                         .order_by(Run.id.desc())).first()
        if not prev:
            return ""
        return json.dumps({"previous_iteration": prev.iteration, "sandbox_evaluation": prev.summary.get("evaluation"),
                           "real_world_result": prev.summary.get("real_world")}, default=str)


def _st_optimize(run_id, project_id, bv):
    with session_scope() as s:
        baseline = s.get(Run, run_id).summary["baseline_batch"]
    opt = Optimizer(project_id, run_id, bv, baseline, provider_factory())
    opt.history = _history(project_id, run_id)
    ids = opt.run()
    _set(run_id, summary={"proposals": ids, "optimizer_summary": opt.summary})
    if not ids:
        _set(run_id, summary={"evaluation": {"recommendation": "no_changes"}})
        return "done"
    return "candidate"


def _st_candidate(run_id, project_id, bv):
    project, brief, card = _load(project_id, bv)
    with session_scope() as s:
        props = list(s.scalars(select(ChangeProposal).where(ChangeProposal.run_id == run_id,
                                                            ChangeProposal.status == "candidate")))
        overrides = {p.page_id: snapshots.version_content(s, p.candidate_version_id) for p in props}
        sb = build_sandbox(s, project, overrides, provider=provider_factory(), cache=_shared_cache(run_id), expose=True)
    pl = _plan(run_id)
    # Only re-ask the questions the changes are meant to help; the others cannot be affected, and skipping them
    # saves time and AI requests. Unknown or missing target ids fall back to asking everything.
    with session_scope() as s:
        all_ids = set(s.get(Run, run_id).summary.get("question_ids") or [q.id for q in brief.target_questions])
    targeted = {q for p in props for q in (p.target_questions or []) if q in all_ids}
    qids = sorted(targeted) if targeted and targeted != all_ids else None
    if qids:
        activity.emit(f"Only re-asking the {len(qids)} of {len(all_ids)} questions these changes are meant to help. "
                      "The others can't be affected, and skipping them saves time.", "info")
    bid = run_batch(project, brief, run_id, "candidate", "controlled", _prompt_set(run_id), sandbox=sb, kb_card=card,
                    samples=pl["samples"], max_steps=pl["steps"], question_ids=qids)
    _set(run_id, summary={"candidate_batch": bid, "candidate_questions": qids or sorted(all_ids)})
    return "evaluate"


def _st_evaluate(run_id, project_id, bv):
    with session_scope() as s:
        sm = s.get(Run, run_id).summary
        base, cand = load_rows(s, sm["baseline_batch"]), load_rows(s, sm["candidate_batch"])
    overall = stats.paired_delta(base, cand)
    per_q = {q: stats.paired_delta([r for r in base if r["question_id"] == q], [r for r in cand if r["question_id"] == q])
             for q in {r["question_id"] for r in base}}
    rec = {"up": "approve", "inconclusive": "review" if overall["delta"] > 0 else "review_weak", "down": "reject",
           "none": "review_weak"}[overall["direction"]]
    ev = {"overall": overall, "per_question": per_q, "recommendation": rec, "questions_retested": sm.get("candidate_questions"),
          "note": "Counterfactual sandbox estimate: directional evidence, not a guarantee of live results."}
    _set(run_id, summary={"evaluation": ev})
    audit.record("evaluation.done", "evaluator", {"overall": overall, "recommendation": rec})
    _CACHES.pop(run_id, None)
    notify.alert("run.awaiting_approval", "info", f"Run {run_id} is ready for review",
                 f"Sandbox delta {overall['delta']:+.3f} (CI {overall['ci']}), recommendation: {rec}", project_id)
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


_STEP = {"created": _st_created, "kb": _st_kb, "prompts": _st_prompts, "baseline": _st_baseline,
         "optimize": _st_optimize, "candidate": _st_candidate, "evaluate": _st_evaluate,
         "awaiting_approval": _st_awaiting_approval, "deploy": _st_deploy, "awaiting_live": _st_awaiting_live,
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
