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

from .. import audit, brief as briefs, kb, notify, snapshots
from ..config import get_settings
from ..context import scope
from ..db import session_scope, utcnow
from ..deploy.service import deploy_run
from ..models import ChangeProposal, Deployment, Persona, Project, Run
from ..optimizer.agent import Optimizer
from ..search.base import SearchCache
from ..search.providers import build_provider
from ..sim import personas as personas_mod, stats
from ..sim.runner import PromptSet, build_sandbox, load_rows, run_batch

# Tests replace this to inject an offline corpus provider.
provider_factory: Callable = lambda: build_provider()


class PipelineError(RuntimeError):
    pass


STAGES = ["created", "kb", "prompts", "baseline", "optimize", "candidate", "evaluate", "awaiting_approval",
          "deploy", "awaiting_live", "awaiting_measure", "measure", "done"]


def start_run(project_id: int) -> int:
    with session_scope() as s:
        project = s.get(Project, project_id)
        if project.current_brief_version == 0:
            raise PipelineError("project has no brief; complete onboarding first")
        open_run = s.scalars(select(Run).where(Run.project_id == project_id, Run.status.in_(["running", "pending"]))).first()
        if open_run:
            raise PipelineError(f"run {open_run.id} is still in progress")
        n = len(list(s.scalars(select(Run).where(Run.project_id == project_id))))
        run = Run(project_id=project_id, iteration=n + 1, brief_version=project.current_brief_version, status="pending")
        s.add(run)
        s.flush()
        rid = run.id
    audit.record("run.created", "user", {"iteration": n + 1}, project_id=project_id, run_id=rid)
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
    with scope(project_id, run_id):
        try:
            while True:
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
        except Exception as e:
            _set(run_id, status="failed", error=f"{type(e).__name__}: {e}")
            audit.record("run.failed", "orchestrator", {"stage": stage, "error": str(e)})
            notify.alert("run.failed", "warning", f"Run {run_id} failed at stage {stage}", str(e), project_id)
            raise
    return get_status(run_id)


def get_status(run_id: int) -> dict:
    with session_scope() as s:
        r = s.get(Run, run_id)
        return {"id": r.id, "project_id": r.project_id, "iteration": r.iteration, "stage": r.stage,
                "status": r.status, "error": r.error, "summary": r.summary,
                "measure_after": r.measure_after.isoformat() if r.measure_after else None,
                "created_at": r.created_at.isoformat()}


# ---- stages ---------------------------------------------------------------------------------------

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
        active = list(s.scalars(select(Persona).where(Persona.project_id == project_id, Persona.active)))
        if not active:
            active = personas_mod.generate(s, project, brief, card)
        for p in active:
            s.expunge(p)
    prompts: dict[str, dict[str, str]] = {"canonical": {q.id: q.text for q in brief.target_questions}}
    for p in active:
        prompts[str(p.id)] = personas_mod.phrase_prompts(p, brief)
    _set(run_id, summary={"prompts": prompts})
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
    with session_scope() as s:
        sb = build_sandbox(s, project, provider=provider_factory(), cache=_shared_cache(run_id))
    bid = run_batch(project, brief, run_id, "baseline", "controlled", _prompt_set(run_id), sandbox=sb, kb_card=card)
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
        sb = build_sandbox(s, project, overrides, provider=provider_factory(), cache=_shared_cache(run_id))
    bid = run_batch(project, brief, run_id, "candidate", "controlled", _prompt_set(run_id), sandbox=sb, kb_card=card)
    _set(run_id, summary={"candidate_batch": bid})
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
    ev = {"overall": overall, "per_question": per_q, "recommendation": rec,
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
    pre = run_batch(project, brief, run_id, "live_pre", "real", _prompt_set(run_id), sandbox=None, kb_card=card,
                    samples=max(1, get_settings().samples_per_question - 1))
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
    post = run_batch(project, brief, run_id, "live_post", "real", _prompt_set(run_id), sandbox=None, kb_card=card,
                     samples=max(1, get_settings().samples_per_question - 1))
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
