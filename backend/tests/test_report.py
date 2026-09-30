from sqlalchemy import select

from confiance import llm, reports
from confiance.db import session_scope
from confiance.models import ChangeProposal, Page, Product, Run, RunLoop, SimulationBatch, SimulationResult
from confiance.plan import generator
from test_plan import RESEARCH, make


def full_round(monkeypatch):
    pid, rid = make(monkeypatch)
    with session_scope() as s:
        run = s.get(Run, rid)
        run.stage = "awaiting_approval"  # where finalize hands over to the person
        cp = s.scalars(select(ChangeProposal)).first()
        s.add(Product(project_id=pid, name="Road Bike 3000", sku="RB-3000", url="https://shop.test/products/bike-0"))
        s.flush()
        pr = s.scalars(select(Product)).first()
        agg_b = {"overall": {"n": 4}, "by_product": {str(pr.id): {"product_mentioned_rate": 0.0, "product_cited_rate": 0.0}}}
        agg_c = {"overall": {"n": 4}, "by_product": {str(pr.id): {"product_mentioned_rate": 0.5, "product_cited_rate": 0.25}}}
        b = SimulationBatch(project_id=pid, run_id=rid, arm="baseline", mode="controlled", aggregate=agg_b)
        c = SimulationBatch(project_id=pid, run_id=rid, arm="candidate", mode="controlled", aggregate=agg_c)
        s.add_all([b, c]); s.flush()
        for batch, ans in ((b, "<script>alert('x')</script> generic answer"), (c, "Acme Bikes sells road bikes")):
            s.add(SimulationResult(batch_id=batch.id, engine="openai", persona_id=None, question_id="q3", prompt="acme bikes", answer=ans, metrics={"answered": True}))
        fun = lambda **k: {"exposed": 1.0, "fetched": 0.5, "used_page": 0.0, "mentioned": 0.5, "cited": 0.0, "n": 4, "score": 0.5, **k}
        s.add(RunLoop(run_id=rid, n=1, status="done", proposal_ids=[cp.id], batch_id=c.id, decision="stop:plateau",
                      delta={"overall": {"delta": 0.12, "ci": [0.06, 0.18], "pairs": 12}, "verdict": {"label": "improved", "recommendation": "approve", "text": "A clear improvement."}},
                      metrics={"tested_questions": ["q3"], "funnel_base": fun(), "funnel_now": fun(fetched=1.0, used_page=0.5, mentioned=1.0, cited=0.5, score=0.8),
                               "feedback": {"per_question": [{"question_id": "q3", "before": fun(), "now": fun(score=0.8, used_page=0.5)}]}}))
        run.summary = {**run.summary, "baseline_batch": b.id, "candidate_batch": c.id, "candidate_questions": ["q3"], "config": {"exposure_rank": 1, "max_loops": 3, "patience": 2, "min_gain": 0.03, "min_effect": 0.05},
                       "questions": [{"id": "q1", "text": "best road bike for commuting", "track": "brand"}, {"id": "q3", "text": "acme bikes", "track": "brand"}],
                       "evaluation": {"verdict": {"label": "improved", "recommendation": "approve", "text": "A clear improvement."}, "best_loop": 1, "stop_reason": "stop:plateau", "overall": {"delta": 0.12}}}
    generator.generate(rid, use_ai=False)
    return pid, rid


def test_report_gathers_every_section_from_stored_data(monkeypatch):
    _, rid = full_round(monkeypatch)
    r = reports.build(rid)
    assert r["meta"]["business"] == "Acme Bikes" and r["summary"]["verdict"]["label"] == "improved" and r["summary"]["best_loop"] == 1
    assert r["summary"]["stop_reason"] == "further loops stopped improving the result" and r["summary"]["loops_run"] == 1
    assert r["summary"]["funnel_before"]["fetched"] == 0.5 and r["summary"]["funnel_after"]["fetched"] == 1.0
    assert r["summary"]["findability"] == RESEARCH["summary"] and r["site_health"]["score"] < 100 and r["site_health"]["findings"]
    assert r["visibility"]["products"] == [{"product": "Road Bike 3000", "sku": "RB-3000", "before": 0.0, "after": 0.5, "linked_before": 0.0, "linked_after": 0.25}]
    q = {x["id"]: x for x in r["visibility"]["questions"]}
    assert q["q3"]["retested"] and q["q3"]["after_score"] == 0.8 and not q["q1"]["retested"] and q["q1"]["fit"] == "needs_content"
    assert r["optimization"]["loops"][0]["delta"] == 0.12 and r["optimization"]["proposals"][0]["changes"]
    assert r["plan"] and r["plan"][0]["priority"] == "P0" and sum(r["summary"]["actions"].values()) == len(r["plan"])
    assert r["appendix"]["samples"][0]["after"] == "Acme Bikes sells road bikes" and any("sandbox" in m for m in r["methodology"])


def test_html_report_is_complete_and_escapes_untrusted_text(monkeypatch):
    _, rid = full_round(monkeypatch)
    html = reports.render_html(reports.build(rid))
    for needle in ["Executive summary", "Site health", "Can search and assistants find you?", "Results by question", "Product / SKU visibility", "The draft-and-test loop",
                   "Proposed changes", "Improvement plan", "Methodology and limits", "Appendix: sample answers", "Road Bike 3000", "llms.txt"]:
        assert needle in html, needle
    assert "<script>alert" not in html and "&lt;script&gt;alert" in html  # an answer containing markup can't inject into the report
    assert html.count("<pre>") >= 3 and "@media print" in html


def test_markdown_report_has_the_same_content(monkeypatch):
    _, rid = full_round(monkeypatch)
    md = reports.render_markdown(reports.build(rid))
    for needle in ["# Optimization report: Acme Bikes", "## Site health", "## Improvement plan", "### [P0]", "```json", "```markdown", "**How to verify:**", "## Methodology and limits", "Road Bike 3000"]:
        assert needle in md, needle


def test_narrative_is_written_from_the_numbers_and_shown_when_present(monkeypatch):
    _, rid = full_round(monkeypatch)
    seen = {}

    def chat(component, messages, **kw):
        seen["prompt"] = messages[-1]["content"]
        return llm.LLMResult(text="We found a few things. The changes helped.", message={"role": "assistant", "content": ""})

    monkeypatch.setattr(llm, "chat", chat)
    text = reports.write_narrative(rid)
    assert text.startswith("We found") and "improved" in seen["prompt"] and "Use ONLY these facts" in seen["prompt"]
    assert reports.build(rid)["summary"]["narrative"] == text and text in reports.render_html(reports.build(rid))


def test_a_round_with_no_results_still_produces_a_report(monkeypatch):
    pid, rid = make(monkeypatch, propose=False)
    with session_scope() as s:
        s.get(Run, rid).summary = {"evaluation": {"recommendation": "no_changes", "verdict": {"label": "no_changes", "recommendation": "review", "text": "No safe changes could be drafted for these questions."}}}
    generator.generate(rid, use_ai=False)
    r = reports.build(rid)
    html, md = reports.render_html(r), reports.render_markdown(r)
    assert "No safe changes" in html and "No safe changes" in md and r["visibility"]["products"] == [] and r["appendix"]["samples"] == []
