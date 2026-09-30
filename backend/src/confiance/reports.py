"""The full report for one round: everything that was found, tried, tested and recommended, in one document.

`build()` collects the facts from the database into a plain dict (the single source of truth); `render_html()` and
`render_markdown()` turn that dict into a printable page or a text file. Nothing is recomputed by the AI here: numbers
come from stored results, and the only AI-written part is the short narrative, which is optional and stored separately."""

import html as htmllib
from datetime import UTC, datetime
from urllib.parse import urlsplit

from sqlalchemy import select

from . import llm, usage
from .brief import get as get_brief
from .config import get_settings
from .db import session_scope
from .models import ChangeProposal, Page, PlanAction, Product, Project, Run, RunLoop, SimulationBatch, SimulationResult
from .plan.generator import _describe
from .services import scan as scan_mod
from .sim.products import track_of

STOP_TEXT = {"stop:max_loops": "the loop limit was reached", "stop:plateau": "further loops stopped improving the result", "stop:converged": "the drafter had nothing more to improve",
             "stop:no_changes": "no safe changes could be drafted", "continue": "still going"}
FUNNEL_LABELS = [("exposed", "Your page was in front of the assistant"), ("fetched", "The assistant opened your page"), ("used_page", "The answer used your page's content"),
                 ("mentioned", "The answer named your business"), ("cited", "The answer linked to your site")]


def _pct(x) -> str:
    return "n/a" if x is None else f"{round(x * 100)}%"


def build(run_id: int) -> dict:
    cfg_s = get_settings()
    with session_scope() as s:
        run = s.get(Run, run_id)
        if run is None:
            raise LookupError("round not found")
        project = s.get(Project, run.project_id)
        sm = dict(run.summary or {})
        try:
            brief_questions = [q.text for q in get_brief(s, project.id, run.brief_version)[1].target_questions]
        except LookupError:
            brief_questions = []
        audit_rec = scan_mod.latest(s, project.id)
        loops = [{"n": l.n, "status": l.status, "decision": l.decision, "proposals": len(l.proposal_ids or []), "delta": l.delta or {}, "metrics": l.metrics or {}, "notes": l.notes}
                 for l in s.scalars(select(RunLoop).where(RunLoop.run_id == run_id).order_by(RunLoop.n))]
        products = {p.id: {"id": p.id, "name": p.name, "sku": p.sku, "url": p.url, "category": p.category} for p in s.scalars(select(Product).where(Product.project_id == project.id))}
        props = []
        for cp in s.scalars(select(ChangeProposal).where(ChangeProposal.run_id == run_id).order_by(ChangeProposal.id)):
            pg = s.get(Page, cp.page_id)
            props.append({"id": cp.id, "status": cp.status, "kind": cp.kind, "loop": cp.loop, "url": pg.url, "rationale": cp.rationale, "targets": cp.target_questions or [],
                          "changes": [_describe(o) for o in cp.ops], "violations": (cp.guard_report or {}).get("violations", []), "warnings": (cp.guard_report or {}).get("warnings", [])})
        actions = [{"seq": a.seq, "priority": a.priority, "category": a.category, "title": a.title, "why": a.why, "steps": a.steps or [], "draft": a.draft or {}, "targets": a.targets or [],
                    "impact": a.impact, "effort": a.effort, "owner": a.owner, "timeframe": a.timeframe, "verify": a.verify, "evidence": a.evidence or [], "status": a.status, "source": a.source}
                   for a in s.scalars(select(PlanAction).where(PlanAction.run_id == run_id).order_by(PlanAction.seq))]
        batches = {b.id: b for b in s.scalars(select(SimulationBatch).where(SimulationBatch.run_id == run_id))}
        base_id, cand_id = sm.get("baseline_batch"), sm.get("candidate_batch")
        base_agg = (batches[base_id].aggregate if base_id in batches else {}) or {}
        cand_agg = (batches[cand_id].aggregate if cand_id in batches else {}) or {}
        samples = []
        texts = {q["id"]: q["text"] for q in sm.get("questions", [])}
        for qid in (sm.get("candidate_questions") or []) [:8]:
            row = {"question_id": qid, "question": texts.get(qid, qid)}
            for label, bid in (("before", base_id), ("after", cand_id)):
                r = s.scalars(select(SimulationResult).where(SimulationResult.batch_id == bid, SimulationResult.question_id == qid, SimulationResult.persona_id.is_(None)).order_by(SimulationResult.id)).first() if bid else None
                row[label] = (r.answer if r else "")
            samples.append(row)
        used = usage.summary(project.id, run_id)
        meta = {"business": project.name, "domain": project.domain, "round": run.iteration, "run_id": run_id, "stage": run.stage, "status": run.status,
                "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"), "created_at": run.created_at.strftime("%Y-%m-%d %H:%M")}
        audit = {"score": audit_rec.score, "scanned": audit_rec.created_at.strftime("%Y-%m-%d"), **audit_rec.data["audit"], "discovery": audit_rec.data["discovery"], "indexed": audit_rec.data.get("indexed")} if audit_rec else None

    ev = sm.get("evaluation") or {}
    cfg = sm.get("config") or {}
    best = next((l for l in loops if l["n"] == ev.get("best_loop")), None)
    fb, fn = (best or {}).get("metrics", {}).get("funnel_base"), (best or {}).get("metrics", {}).get("funnel_now")
    research = sm.get("research") or {}
    by_prod = {}
    for pid, agg in (cand_agg.get("by_product") or base_agg.get("by_product") or {}).items():
        by_prod[pid] = {"after": agg, "before": (base_agg.get("by_product") or {}).get(pid)}
    product_rows = [{"product": products.get(int(pid), {}).get("name", f"Product {pid}"), "sku": products.get(int(pid), {}).get("sku", ""),
                     "before": _rate(v["before"], "product_mentioned"), "after": _rate(v["after"], "product_mentioned"),
                     "linked_before": _rate(v["before"], "product_cited"), "linked_after": _rate(v["after"], "product_cited")} for pid, v in by_prod.items()]
    per_q = {p["question_id"]: p for p in (best or {}).get("metrics", {}).get("feedback", {}).get("per_question", [])}
    q_rows = []
    for q in sm.get("questions", []):
        fit = next((e for e in research.get("queries", []) if e["id"] == q["id"]), {})
        pq = per_q.get(q["id"])
        q_rows.append({"id": q["id"], "text": q["text"], "track": q["track"], "found_rank": fit.get("rank"), "fit": fit.get("fit"), "fit_reason": fit.get("fit_reason"), "top_domains": fit.get("top_domains", []),
                       "before_score": (pq or {}).get("before", {}).get("score"), "after_score": (pq or {}).get("now", {}).get("score"), "retested": bool(pq),
                       "used_before": (pq or {}).get("before", {}).get("used_page"), "used_after": (pq or {}).get("now", {}).get("used_page")})
    counts = {p: sum(a["priority"] == p for a in actions) for p in ("P0", "P1", "P2", "P3")}
    report = {
        "meta": meta, "config": cfg, "models": {"main": cfg_s.llm_model, "fast": cfg_s.llm_worker_model or cfg_s.llm_model},
        "summary": {"verdict": ev.get("verdict"), "best_loop": ev.get("best_loop"), "stop_reason": STOP_TEXT.get(ev.get("stop_reason", ""), ev.get("stop_reason", "")), "loops_run": len(loops),
                    "funnel_before": fb, "funnel_after": fn, "findability": research.get("summary"), "site_score": (audit or {}).get("score"), "actions": counts,
                    "edits": sum(p["kind"] == "edit" and p["status"] in ("candidate", "approved", "deployed") for p in props), "new_pages": sum(p["kind"] == "new_page" and p["status"] in ("candidate", "approved", "deployed") for p in props),
                    "blocked": sum(p["status"] == "blocked" for p in props), "narrative": sm.get("narrative", ""), "overall": ev.get("overall"), "by_track": ev.get("by_track")},
        "site_health": audit, "discoverability": {"queries": research.get("queries", []), "brand": research.get("brand"), "patterns": research.get("patterns"), "competitors": research.get("competitors", [])},
        "visibility": {"questions": q_rows, "products": product_rows, "funnel_labels": FUNNEL_LABELS}, "optimization": {"loops": [_loop_view(l) for l in loops], "proposals": props},
        "plan": actions, "appendix": {"samples": samples, "usage": used, "usage_total_usd": round(sum(r["cost_usd"] for r in used), 4),
                                      "brand_questions": brief_questions},
        "methodology": _methodology(cfg, cfg_s)}
    return report


def _rate(agg: dict | None, key: str):
    return (agg or {}).get(f"{key}_rate")


def _loop_view(l: dict) -> dict:
    d = l["delta"].get("overall", {}) or {}
    return {"n": l["n"], "proposals": l["proposals"], "delta": d.get("delta"), "ci": d.get("ci"), "pairs": d.get("pairs"), "verdict": (l["delta"].get("verdict") or {}).get("text"),
            "label": (l["delta"].get("verdict") or {}).get("label"), "decision": STOP_TEXT.get(l["decision"], l["decision"]), "tested": len(l["metrics"].get("tested_questions", [])), "notes": l.get("notes", "")}


def _methodology(cfg: dict, s) -> list[str]:
    return [
        "Confiance asks AI assistants your customers' questions many times, with pretend customers phrasing each question differently, and records whether the answer names, links to and draws on your pages.",
        f"To test a change without publishing it, the search tool's results are rewritten inside a sandbox so they contain your modified pages. Your page is placed at result #{cfg.get('exposure_rank', 1)} in both the 'before' and 'after' tests, so the comparison isolates how well the page content works. This does not predict search ranking.",
        "Findability (whether real search shows your site) is measured separately with plain searches and is never simulated.",
        "Before and after answers are compared in pairs (same question, same pretend customer, same try). A change is called an improvement only if the 95% range excludes zero and the gain is at least "
        f"{cfg.get('min_effect', 0.05)} on a 0 to 1 scale. Smaller differences are reported as no meaningful change.",
        f"The draft-and-test loop runs at most {cfg.get('max_loops', 3)} times and stops early when {cfg.get('patience', 2)} loop(s) in a row fail to beat the best result by {cfg.get('min_gain', 0.03)}. The best loop is kept, not necessarily the last.",
        "Every proposed change passes a code guard (locked regions, no invented numbers, no hidden text, no instructions aimed at AI models) before it is tested or shown to you.",
        "Sandbox results are estimates. The real check is a new round after you publish, since assistants and search engines re-crawl slowly.",
        "Small samples produce wide ranges. A Standard or Thorough round gives more reliable numbers than a Quick check."]


def write_narrative(run_id: int) -> str:
    """Two short plain-language paragraphs summarising the round, written from the report's own numbers."""
    rep = build(run_id)
    facts = {k: rep["summary"][k] for k in ("verdict", "loops_run", "stop_reason", "findability", "site_score", "actions", "edits", "new_pages", "funnel_before", "funnel_after")}
    top = [a["title"] for a in rep["plan"][:5]]
    res = llm.chat("report.narrative", [{"role": "system", "content": "You write clear, honest, plain-language executive summaries for business owners. No jargon, no hype, no invented numbers."},
                                        {"role": "user", "content": "Write two short paragraphs (under 170 words in total). First: what we found about how AI assistants and search see the business today and the main reasons. "
                                                                    "Second: what was changed and tested, how it did (be honest if there was no clear improvement), and the top priorities. Use ONLY these facts: "
                                                                    f"{facts}. Top plan items: {top}."}], role="worker", max_tokens=6000)
    text = res.text.strip()
    with session_scope() as s:
        run = s.get(Run, run_id)
        run.summary = {**(run.summary or {}), "narrative": text}
    return text


def default_narrative(rep: dict) -> str:
    sm, fs = rep["summary"], rep["summary"].get("findability") or {}
    parts = []
    if fs:
        parts.append(f"Real search shows your site for {fs.get('found', 0)} of {fs.get('checked', 0)} of the questions checked" + (", and finds you by name." if fs.get("brand_found") else ", and does not find you by name."))
    if sm.get("verdict"):
        parts.append(sm["verdict"]["text"])
    if sm["actions"]["P0"]:
        parts.append(f"{sm['actions']['P0']} action(s) are marked P0 and should be done first.")
    return " ".join(parts)


# ---- markdown -------------------------------------------------------------------------------------------------------

def render_markdown(r: dict) -> str:
    m, sm = r["meta"], r["summary"]
    L = [f"# Optimization report: {m['business']}", f"_{m['domain']} · round {m['round']} · generated {m['generated_at']}_", ""]
    L += ["## Executive summary", sm["narrative"] or default_narrative(r), ""]
    if sm["verdict"]:
        L += [f"**Sandbox result:** {sm['verdict']['text']}", f"**Loops run:** {sm['loops_run']} (stopped because {sm['stop_reason'] or 'the round finished'}); best loop: {sm['best_loop'] or 'n/a'}", ""]
    fb, fn = sm["funnel_before"], sm["funnel_after"]
    if fb and fn:
        L += ["| Step | Before | After |", "|---|---|---|"] + [f"| {lab} | {_pct(fb.get(k))} | {_pct(fn.get(k))} |" for k, lab in FUNNEL_LABELS] + [""]
    sh = r["site_health"]
    if sh:
        L += ["## Site health", f"Score **{sh['score']}/100** (scanned {sh['scanned']}). Pages checked: {sh['pages_checked']}.", ""]
        L += [f"- **[{f['severity'].upper()}] {f['title']}**: {f['detail']} _Fix: {f['fix']}_" for f in sh["findings"]] + [""]
    L += ["## Can search and assistants find you?"]
    for e in r["discoverability"]["queries"]:
        L.append(f"- “{e['query']}”: " + (f"found at #{e['rank']}" if e.get("rank") else "not found" if e["status"] == "not_found" else "couldn't check") + f" · {e.get('fit_reason', '')}" + (f" (instead: {', '.join(e['top_domains'][:3])})" if e.get("top_domains") and not e.get("rank") else ""))
    L.append("")
    L += ["## Results by question", "| Question | Track | Found | Before | After |", "|---|---|---|---|---|"]
    L += [f"| {q['text']} | {q['track']} | {('#' + str(q['found_rank'])) if q['found_rank'] else 'no'} | {_score(q['before_score'])} | {_score(q['after_score']) if q['retested'] else 'not re-tested'} |" for q in r["visibility"]["questions"]] + [""]
    if r["visibility"]["products"]:
        L += ["## Product / SKU visibility", "| Product | SKU | Named before | Named after | Linked before | Linked after |", "|---|---|---|---|---|---|"]
        L += [f"| {p['product']} | {p['sku']} | {_pct(p['before'])} | {_pct(p['after'])} | {_pct(p['linked_before'])} | {_pct(p['linked_after'])} |" for p in r["visibility"]["products"]] + [""]
    L += ["## The draft-and-test loop", "| Loop | Changes | Change in score | Verdict | Decision |", "|---|---|---|---|---|"]
    L += [f"| {l['n']} | {l['proposals']} | {_signed(l['delta'])} | {l['verdict'] or ''} | {l['decision']} |" for l in r["optimization"]["loops"]] + [""]
    L += ["## Proposed changes"]
    for p in r["optimization"]["proposals"]:
        L += [f"### {'NEW PAGE' if p['kind'] == 'new_page' else 'Edit'}: {urlsplit(p['url']).path or '/'} ({p['status']}, loop {p['loop']})", p["rationale"] or "", ""]
        L += [f"- {c}" for c in p["changes"]] + ([f"- **Blocked:** {'; '.join(p['violations'])}"] if p["violations"] else []) + [""]
    L += ["## Improvement plan"]
    for a in r["plan"]:
        L += [f"### [{a['priority']}] {a['title']}", f"_{a['category']} · impact {a['impact']} · effort {a['effort']} · owner: {a['owner']}" + (f" · {a['timeframe']}" if a["timeframe"] else "") + f" · status: {a['status']}_", "", a["why"], ""]
        L += [f"{i}. {st}" for i, st in enumerate(a["steps"], 1)] + [""]
        if a["draft"].get("content"):
            L += [f"**{a['draft'].get('label', 'Draft')}**", "```" + (a["draft"].get("language") or ""), a["draft"]["content"], "```", ""]
        if a["verify"]:
            L += [f"**How to verify:** {a['verify']}", ""]
    L += ["## Methodology and limits"] + [f"- {t}" for t in r["methodology"]] + [""]
    L += ["## Appendix: sample answers"]
    for sx in r["appendix"]["samples"]:
        L += [f"### {sx['question']}", "**Before:**", "", sx["before"] or "(none)", "", "**After:**", "", sx["after"] or "(none)", ""]
    return "\n".join(L)


def _score(x) -> str:
    return "n/a" if x is None else f"{x:.2f}"


def _signed(x) -> str:
    return "n/a" if x is None else f"{x:+.3f}"


# ---- html -----------------------------------------------------------------------------------------------------------

CSS = """
:root{--bg:#f4efe6;--surface:#fcfaf5;--line:#e0d7c6;--text:#2e2a25;--muted:#776d60;--primary:#566f4f;--clay:#a9623f;--brick:#a3453a;--sand:#f3e8cf}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:920px;margin:0 auto;padding:32px 20px 64px}h1,h2,h3{font-family:"Iowan Old Style",Georgia,serif;line-height:1.2}
h1{font-size:2rem;margin:0 0 .25rem}h2{margin:2.2rem 0 .6rem;padding-top:1rem;border-top:1px solid var(--line);font-size:1.4rem}h3{font-size:1.05rem;margin:1.2rem 0 .3rem}
.muted{color:var(--muted)}.card{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:16px 18px;margin:12px 0}
table{width:100%;border-collapse:collapse;margin:.6rem 0}th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--muted);font-weight:500;font-size:.85rem}
.pill{display:inline-block;font-size:.75rem;font-weight:600;padding:1px 9px;border-radius:99px;background:var(--sand)}.p0{background:#f2dcd7;color:var(--brick)}.p1{background:var(--sand);color:#8a6a24}.good{background:#e3e9dc;color:var(--primary)}
.bar{height:10px;background:#efe8dc;border-radius:99px;overflow:hidden;min-width:120px}.bar i{display:block;height:100%;background:var(--primary)}.bar.b i{background:#a49a8b}
pre{background:#f0e9dc;border:1px solid var(--line);border-radius:10px;padding:12px;overflow:auto;font-size:.82rem;white-space:pre-wrap}details{margin:.4rem 0}summary{cursor:pointer;color:var(--muted)}
.big{font-family:Georgia,serif;font-size:2.2rem;font-weight:600}.row{display:flex;gap:24px;flex-wrap:wrap}.kpi{flex:1;min-width:150px}.ans{white-space:pre-wrap;background:#f0e9dc;border-radius:10px;padding:10px;font-size:.85rem}
@media print{body{background:#fff}.card{break-inside:avoid}h2{break-after:avoid}details{display:block}}
"""


def _e(x) -> str:
    return htmllib.escape(str(x if x is not None else ""))


def _bar(v, cls="") -> str:
    return f'<div class="bar {cls}"><i style="width:{max(2, round((v or 0) * 100))}%"></i></div>'


def render_html(r: dict) -> str:
    m, sm = r["meta"], r["summary"]
    h = [f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Optimization report: {_e(m["business"])}</title><style>{CSS}</style></head><body><main>',
         f'<h1>Optimization report: {_e(m["business"])}</h1><p class="muted">{_e(m["domain"])} · round {m["round"]} · generated {_e(m["generated_at"])}</p>']
    h.append(f'<h2 style="border:0;margin-top:1rem">Executive summary</h2><div class="card"><p>{_e(sm["narrative"] or default_narrative(r))}</p>')
    if sm["verdict"]:
        h.append(f'<p><b>Sandbox result:</b> <span class="pill {"good" if sm["verdict"]["label"] == "improved" else ""}">{_e(sm["verdict"]["label"].replace("_", " "))}</span> {_e(sm["verdict"]["text"])}</p>'
                 f'<p class="muted">{sm["loops_run"]} loop(s) run; stopped because {_e(sm["stop_reason"] or "the round finished")}; best loop: {_e(sm["best_loop"] or "n/a")}.</p>')
    fs = sm.get("findability") or {}
    h.append('<div class="row">' + "".join(f'<div class="kpi"><div class="big">{v}</div><div class="muted">{k}</div></div>' for k, v in [
        ("site health", f'{sm["site_score"]}/100' if sm["site_score"] is not None else "n/a"), ("questions where search finds you", f'{fs.get("found", 0)} of {fs.get("checked", 0)}'),
        ("changes tested", sm["edits"] + sm["new_pages"]), ("plan actions (P0)", f'{sum(sm["actions"].values())} ({sm["actions"]["P0"]})')]) + "</div></div>")
    fb, fn = sm["funnel_before"], sm["funnel_after"]
    if fb and fn:
        h.append("<h3>How assistants treat your page: before and after</h3><table><tr><th>Step</th><th>Before</th><th></th><th>After</th><th></th></tr>" +
                 "".join(f"<tr><td>{_e(lab)}</td><td>{_pct(fb.get(k))}</td><td>{_bar(fb.get(k), 'b')}</td><td><b>{_pct(fn.get(k))}</b></td><td>{_bar(fn.get(k))}</td></tr>" for k, lab in FUNNEL_LABELS) + "</table>")
    sh = r["site_health"]
    if sh:
        h.append(f'<h2>Site health</h2><p>Score <b>{sh["score"]}/100</b> · scanned {_e(sh["scanned"])} · {sh["pages_checked"]} pages checked</p>')
        d = sh["discovery"]
        bl = [b for b, v in (d.get("robots", {}).get("ai_bots") or {}).items() if not v["allowed"]]
        h.append(f'<div class="card"><b>What crawlers see:</b> robots.txt {"found" if d.get("robots", {}).get("exists") else "missing"}{f" (blocks {_e(", ".join(bl[:6]))})" if bl else ""} · '
                 f'sitemap {"found, " + str(d.get("url_count", 0)) + " URLs" if any(x.get("status") == 200 for x in d.get("sitemaps", [])) else "missing"} · llms.txt {"found" if d.get("llms", {}).get("exists") else "missing"}</div>')
        h.append("<table><tr><th>Severity</th><th>Finding</th><th>Fix</th></tr>" + "".join(f'<tr><td><span class="pill {"p0" if f["severity"] == "high" else "p1" if f["severity"] == "medium" else ""}">{_e(f["severity"])}</span></td>'
                                                                                            f'<td><b>{_e(f["title"])}</b><br><span class="muted">{_e(f["detail"])}</span></td><td>{_e(f["fix"])}</td></tr>' for f in sh["findings"]) + "</table>")
    h.append('<h2>Can search and assistants find you?</h2><table><tr><th>Question</th><th>Real search</th><th>What it means</th></tr>' + "".join(
        f'<tr><td>“{_e(e["query"])}”</td><td>{("<span class=\'pill good\'>#" + str(e["rank"]) + "</span>") if e.get("rank") else ("<span class=\'pill\'>not found</span>" if e["status"] == "not_found" else "unknown")}</td>'
        f'<td>{_e(e.get("fit_reason", ""))}{("<br><span class=\'muted\'>Instead: " + _e(", ".join(e["top_domains"][:3])) + "</span>") if e.get("top_domains") and not e.get("rank") else ""}</td></tr>' for e in r["discoverability"]["queries"]) + "</table>")
    pt = r["discoverability"].get("patterns")
    if pt:
        h.append(f'<p class="muted">Pages that win these questions today: median {pt.get("median_words", 0)} words, {_pct(pt.get("share_with_faq"))} include an FAQ' + (f'; common headings: {_e(", ".join(pt["common_headings"][:4]))}' if pt.get("common_headings") else "") + ".</p>")
    h.append("<h2>Results by question</h2><table><tr><th>Question</th><th>Track</th><th>Search rank</th><th>Before</th><th>After</th></tr>" + "".join(
        f'<tr><td>{_e(q["text"])}</td><td>{_e(q["track"])}</td><td>{("#" + str(q["found_rank"])) if q["found_rank"] else "no"}</td><td>{_score(q["before_score"])}</td><td>{_score(q["after_score"]) if q["retested"] else "<span class=muted>not re-tested</span>"}</td></tr>' for q in r["visibility"]["questions"]) + "</table>")
    if r["visibility"]["products"]:
        h.append("<h2>Product / SKU visibility</h2><table><tr><th>Product</th><th>SKU</th><th>Named before</th><th>Named after</th><th>Linked before</th><th>Linked after</th></tr>" + "".join(
            f'<tr><td>{_e(p["product"])}</td><td>{_e(p["sku"])}</td><td>{_pct(p["before"])}</td><td>{_pct(p["after"])}</td><td>{_pct(p["linked_before"])}</td><td>{_pct(p["linked_after"])}</td></tr>' for p in r["visibility"]["products"]) + "</table>")
    h.append("<h2>The draft-and-test loop</h2><table><tr><th>Loop</th><th>Changes</th><th>Change in score</th><th>Verdict</th><th>Decision</th></tr>" + "".join(
        f'<tr><td>{l["n"]}</td><td>{l["proposals"]}</td><td>{_signed(l["delta"])}</td><td>{_e(l["verdict"])}</td><td>{_e(l["decision"])}</td></tr>' for l in r["optimization"]["loops"]) + "</table>")
    h.append("<h2>Proposed changes</h2>")
    for p in r["optimization"]["proposals"]:
        h.append(f'<div class="card"><b>{"New page" if p["kind"] == "new_page" else "Edit"}: {_e(urlsplit(p["url"]).path or "/")}</b> <span class="pill">{_e(p["status"])}</span> <span class="muted">loop {p["loop"]}</span><p>{_e(p["rationale"])}</p>'
                 f'<details><summary>What changes</summary><pre>{_e(chr(10).join(p["changes"]))}</pre></details>' + (f'<p class="muted"><b>Blocked:</b> {_e("; ".join(p["violations"]))}</p>' if p["violations"] else "") + "</div>")
    h.append("<h2>Improvement plan</h2>")
    for a in r["plan"]:
        cls = "p0" if a["priority"] == "P0" else "p1" if a["priority"] == "P1" else ""
        h.append(f'<div class="card"><span class="pill {cls}">{a["priority"]}</span> <b>{_e(a["title"])}</b><div class="muted">{_e(a["category"].replace("_", " "))} · impact {_e(a["impact"])} · effort {_e(a["effort"])} · owner: {_e(a["owner"])}' + (f' · {_e(a["timeframe"])}' if a["timeframe"] else "") + f' · {_e(a["status"])}</div><p>{_e(a["why"])}</p><ol>' +
                 "".join(f"<li>{_e(st)}</li>" for st in a["steps"]) + "</ol>" + (f'<details><summary>{_e(a["draft"].get("label", "Draft"))}</summary><pre>{_e(a["draft"]["content"])}</pre></details>' if a["draft"].get("content") else "") +
                 (f'<p class="muted"><b>How to verify:</b> {_e(a["verify"])}</p>' if a["verify"] else "") + "</div>")
    h.append("<h2>Methodology and limits</h2><ul>" + "".join(f"<li>{_e(t)}</li>" for t in r["methodology"]) + "</ul>")
    h.append("<h2>Appendix: sample answers</h2>")
    for sx in r["appendix"]["samples"]:
        h.append(f'<h3>{_e(sx["question"])}</h3><div class="row"><div class="kpi"><b>Before</b><div class="ans">{_e(sx["before"] or "(none)")}</div></div><div class="kpi"><b>After</b><div class="ans">{_e(sx["after"] or "(none)")}</div></div></div>')
    h.append(f'<p class="muted">AI use for this round: {_e(r["models"]["main"])} (main), {_e(r["models"]["fast"])} (fast). Estimated cost ${r["appendix"]["usage_total_usd"]:.2f}.</p></main></body></html>')
    return "".join(h)
