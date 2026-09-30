"""Runs a batch: (engines x personas x questions x samples) in parallel and persists scored results."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import activity, audit, snapshots
from ..brief import BriefData
from ..config import get_settings
from ..context import submit
from ..db import session_scope
from ..engines import Turn, build_engine
from ..models import Page, Project, SimulationBatch, SimulationResult
from ..search.base import SearchCache
from ..search.sandbox import Sandbox
from ..search.providers import build_provider
from ..textutil import domain_of, html_to_text, norm_url
from . import stats
from .metrics import Target, score, visibility_score


@dataclass
class PromptSet:
    """prompts[persona_id or None][question_id] -> text. Generated once per run and reused by every arm."""
    prompts: dict[int | None, dict[str, str]]


def build_sandbox(s: Session, project: Project, overrides: dict[int, str] | None = None, *,
                  provider=None, cache: SearchCache | None = None, expose: bool = False) -> Sandbox:
    overrides = overrides or {}
    pages, modified, urls = {}, set(), {}
    for p in s.scalars(select(Page).where(Page.project_id == project.id)):
        html = overrides.get(p.id) or snapshots.live_content(s, p)
        if html is None:
            continue
        key = norm_url(p.url)
        urls[key] = p.url
        pages[key] = html_to_text(html)
        if p.id in overrides:
            modified.add(key)
    return Sandbox(provider=provider or build_provider(), client_domain=project.domain, pages=pages,
                   modified=modified, cache=cache or SearchCache(), urls=urls, expose=expose)


def target_for(project: Project, brief: BriefData) -> Target:
    return Target(project.domain, [project.name, *project.brand_aliases], brief.competitors)


def run_batch(project: Project, brief: BriefData, run_id: int | None, arm: str, mode: str, prompts: PromptSet,
              *, sandbox: Sandbox | None, kb_card: str, samples: int | None = None,
              engines: list[dict] | None = None, question_ids: list[str] | None = None, max_steps: int | None = None) -> int:
    cfg = get_settings()
    samples = samples or cfg.samples_per_question
    engines = engines or project.engines
    target = target_for(project, brief)
    qids = set(question_ids) if question_ids else None

    tasks = []
    for eng in engines:
        for pid, qmap in prompts.prompts.items():
            for qid, text in qmap.items():
                if qids and qid not in qids:
                    continue
                for i in range(samples):
                    tasks.append((eng, pid, qid, text, i))

    def work(eng: dict, pid, qid: str, text: str, i: int) -> dict:
        activity.check_cancelled()
        engine = build_engine(eng["name"], eng.get("model"), max_steps)
        if mode == "real":
            ans = engine.run_real([Turn("user", text)])
        else:
            tools = sandbox.session() if mode == "controlled" and sandbox else None
            ans = engine.run(mode, [Turn("user", text)], tools)
        page_texts = [t for _, t in sandbox.pages.values()] if (sandbox is not None and mode == "controlled") else None
        m = score(ans, target, kb_card=kb_card, prompt=text, judge=cfg.use_llm_judge and not ans.error, page_texts=page_texts)
        return {"engine": eng["name"], "persona_id": pid, "question_id": qid, "sample_idx": i, "prompt": text,
                "ans": ans, "metrics": m, "score": visibility_score(m)}

    label = {"baseline": "Round 1 of 2: asking with your website as it is today",
             "candidate": "Round 2 of 2: asking again with the improvements in place",
             "live_pre": "Checking today's real-world answers (before publishing)",
             "live_post": "Checking real-world answers after publishing"}.get(arm, f"Asking ({arm})")
    activity.set_total(len(tasks))
    activity.emit(f"{label} ({len(tasks)} practice conversations)", "step")
    rows = []
    with ThreadPoolExecutor(cfg.max_parallel_calls) as pool:
        futs = [submit(pool, work, *t) for t in tasks]
        for f in as_completed(futs):
            if activity.is_cancelled():
                for x in futs:
                    x.cancel()  # conversations not started yet never start
            r = f.result()
            rows.append(r)
            activity.tick()
            short = (r["prompt"][:70] + "…") if len(r["prompt"]) > 70 else r["prompt"]
            if r["ans"].error:
                activity.emit(f"Couldn't get an answer to “{short}”: {r['ans'].error[:120]}", "warn")
            else:
                m = r["metrics"]
                activity.emit(f"Asked “{short}”. Mentions you: {'yes' if m.get('mentioned') else 'no'}, links to you: {'yes' if m.get('cited') else 'no'}", "ask",
                              {"engine": r["engine"], "latency_ms": r["ans"].latency_ms})

    with session_scope() as s:
        batch = SimulationBatch(project_id=project.id, run_id=run_id, arm=arm, mode=mode)
        s.add(batch)
        s.flush()
        for r in rows:
            a = r["ans"]
            s.add(SimulationResult(
                batch_id=batch.id, engine=r["engine"], model_id=a.model_id, persona_id=r["persona_id"],
                question_id=r["question_id"], prompt=r["prompt"], sample_idx=r["sample_idx"], answer=a.text,
                citations=a.citations, retrieved_urls=a.retrieved_urls, queries=a.queries, injected=a.injected,
                metrics=r["metrics"], error=a.error, latency_ms=a.latency_ms))
        batch.aggregate = stats.aggregate([{"engine": r["engine"], "question_id": r["question_id"],
                                            "score": r["score"], "metrics": r["metrics"]} for r in rows])
        batch_id = batch.id
    audit.record("sim.batch_done", "simulator", {"batch_id": batch_id, "arm": arm, "mode": mode, "results": len(rows),
                                                 "errors": sum(1 for r in rows if r["ans"].error)},
                 project_id=project.id, run_id=run_id)
    return batch_id


def load_rows(s: Session, batch_id: int) -> list[dict]:
    out = []
    for r in s.scalars(select(SimulationResult).where(SimulationResult.batch_id == batch_id)):
        out.append({"engine": r.engine, "persona_id": r.persona_id, "question_id": r.question_id,
                    "sample_idx": r.sample_idx, "metrics": r.metrics, "score": visibility_score(r.metrics),
                    "answer": r.answer, "prompt": r.prompt, "citations": r.citations, "error": r.error})
    return out


__all__ = ["PromptSet", "build_sandbox", "run_batch", "load_rows", "target_for", "domain_of"]
