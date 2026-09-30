"""Optimizer: a ReAct agent (reason -> act -> observe -> repeat) that proposes page changes.

Tools let it look at evidence (weak questions, KB, pages, the real web) and propose edits. Every
proposal is checked by the guard *inside* the tool call, so a blocked proposal comes back as an
observation and the agent can revise it - the same loop a human editor would follow.
"""

import json
from collections import defaultdict

from sqlalchemy import select

from .. import activity, audit, kb, llm, snapshots
from ..brief import BriefData, get as get_brief
from ..db import session_scope
from ..models import ChangeProposal, Page, Project, Run
from ..search.base import SearchProvider
from ..sim.runner import load_rows
from ..textutil import domain_of, html_to_text
from . import guard
from .ops import OP_DOC, OP_SCHEMA

MAX_PAGE_CHARS = 14_000

SYSTEM = """You are the optimizer inside CONFIANCE, a Generative Engine Optimization system. AI answer engines
(ChatGPT, Claude, Gemini, ...) search the web, read pages and answer users' questions. Your job is to make the
client's pages the ones an assistant finds, trusts, uses and cites for the target questions.

Two separate things decide the outcome, and they need different fixes:
1. USEFULNESS WHEN FOUND. Once an assistant sees a page, does the answer draw on it? Page edits improve this, and it
   is what the practice test measures (the page is guaranteed to be among the results, before and after).
2. FINDABILITY. Is the site in the real search results at all? get_findability shows this per question. If a
   question is "not found" and the results are dominated by big sites, editing one page rarely changes that.

What tends to work for usefulness (do these thoroughly, not timidly):
- Answer each target question DIRECTLY near the top: a question-shaped heading, then a 2-3 sentence answer that names
  the business and states concrete facts taken from the page or knowledge base.
- One rich FAQ (add_faq) using the exact wording people use for the target questions.
- Title and meta description that contain the specific topics and entities people ask about.
- Structured data (add_jsonld: Organization, FAQPage, Course, Article, LocalBusiness... whichever is true).
- Specific, verifiable facts: what is offered, for whom, where, since when, how it differs from alternatives.

For findability, page edits alone are not enough. When questions are not found, call `recommend` with concrete bigger
steps, e.g. a NEW dedicated page for a specific long-tail topic, more specific wording, or being listed where
assistants look. Be specific and honest about what you expect. Do not pretend an edit will fix ranking.

Hard rules (a code guard blocks violations; you cannot override it):
- Only state facts present on the page or in the knowledge base. Never invent numbers, awards, reviews or claims.
- No hidden text, no keyword stuffing, no instructions addressed to AI models. Write for humans.
- Respect the brief's locked regions, locked phrases, editable pages and allowed operations.

Process: get_weak_questions and get_findability first, read the relevant pages, check the knowledge base and (if
useful) how others answer via web_search, then propose_change - one proposal per page, with a strong set of
operations rather than a single tweak. If a proposal is blocked, read the violations and revise. Add recommendations
for what edits cannot fix. Call finish when done.

""" + OP_DOC

TOOLS = [
    {"name": "list_pages", "description": "List the client's pages: id, url, title.",
     "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "get_weak_questions",
     "description": "Target questions ranked weakest-first from the baseline simulation, with citation stats, "
                    "competitors that were cited instead, and short sample answers.",
     "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}, "additionalProperties": False}},
    {"name": "get_findability",
     "description": "For each target question (and the business name): does real web search return the client's site, at what "
                    "rank, and which other sites dominate the results instead.",
     "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "recommend",
     "description": "Record a bigger step that page edits alone cannot achieve (a new page, off-site listing, more specific "
                    "content). Shown to the business owner next to the edits.",
     "parameters": {"type": "object", "properties": {
         "title": {"type": "string", "description": "Short headline"},
         "action": {"type": "string", "description": "What to do, concretely"},
         "why": {"type": "string", "description": "Which questions it helps and why"}},
         "required": ["title", "action", "why"], "additionalProperties": False}},
    {"name": "search_kb", "description": "Search the company knowledge base for passages/facts.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"],
                      "additionalProperties": False}},
    {"name": "read_page", "description": "Read a page's current HTML (truncated) by page id.",
     "parameters": {"type": "object", "properties": {"page_id": {"type": "integer"}}, "required": ["page_id"],
                      "additionalProperties": False}},
    {"name": "web_search", "description": "Search the real web (e.g. to see who answers a question today).",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"],
                      "additionalProperties": False}},
    {"name": "propose_change",
     "description": "Propose edits to one page. Checked immediately against the brief's constraints.",
     "parameters": {"type": "object", "properties": {
         "page_id": {"type": "integer"},
         "ops": {"type": "array", "items": OP_SCHEMA},
         "rationale": {"type": "string"},
         "target_questions": {"type": "array", "items": {"type": "string"}, "description": "question ids this helps"}},
         "required": ["page_id", "ops", "rationale", "target_questions"], "additionalProperties": False}},
    {"name": "finish", "description": "Stop; summarize what you proposed and what remains.",
     "parameters": {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"],
                      "additionalProperties": False}},
]


class Optimizer:
    def __init__(self, project_id: int, run_id: int, brief_version: int, baseline_batch_id: int | None,
                 provider: SearchProvider | None):
        self.project_id, self.run_id, self.brief_version = project_id, run_id, brief_version
        self.baseline_batch_id, self.provider = baseline_batch_id, provider
        self.proposals: dict[int, int] = {}  # page_id -> proposal id
        self.done = False
        self.summary = ""
        self.history = ""  # digest of the previous iteration's outcome

    # ---- tool implementations -------------------------------------------------------------
    def _t_list_pages(self, _: dict) -> str:
        with session_scope() as s:
            out = []
            for p in s.scalars(select(Page).where(Page.project_id == self.project_id)):
                title, _t = html_to_text(snapshots.live_content(s, p) or "")
                out.append({"page_id": p.id, "url": p.url, "title": title})
        return json.dumps(out)

    def _t_get_weak_questions(self, a: dict) -> str:
        activity.emit("Looking at which questions do worst today", "tool")
        if not self.baseline_batch_id:
            return "[]"
        with session_scope() as s:
            rows = load_rows(s, self.baseline_batch_id)
            _, brief = get_brief(s, self.project_id, self.brief_version)
        text = {q.id: q.text for q in brief.target_questions}
        prio = {q.id: q.priority for q in brief.target_questions}
        by = defaultdict(list)
        for r in rows:
            by[r["question_id"]].append(r)
        out = []
        for qid, rs in by.items():
            vis = sum(r["score"] for r in rs) / len(rs)
            comp = defaultdict(int)
            for r in rs:
                for c in r["metrics"].get("competitors_cited", []):
                    comp[c] += 1
            worst = min(rs, key=lambda r: r["score"])
            out.append({"question_id": qid, "question": text.get(qid, ""), "priority": prio.get(qid, 1),
                        "visibility": round(vis, 3),
                        "cited_rate": round(sum(bool(r["metrics"].get("cited")) for r in rs) / len(rs), 3),
                        "mentioned_rate": round(sum(bool(r["metrics"].get("mentioned")) for r in rs) / len(rs), 3),
                        "page_shown_rate": round(sum(bool(r["metrics"].get("exposed")) for r in rs) / len(rs), 3),
                        "page_used_rate": round(sum(bool(r["metrics"].get("used_page")) for r in rs) / len(rs), 3),
                        "competitors_cited": dict(comp),
                        "sample_answer": (worst["answer"] or "")[:500]})
        out.sort(key=lambda x: (x["visibility"], -x["priority"]))
        return json.dumps(out[: int(a.get("limit") or 8)])

    def _t_get_findability(self, a: dict) -> str:
        activity.emit("Checking which questions real search already finds you for", "tool")
        with session_scope() as s:
            run = s.get(Run, self.run_id)
            items = (run.summary or {}).get("findability") or []
        return json.dumps(items) if items else "[]"

    def _t_recommend(self, a: dict) -> str:
        item = {"title": str(a.get("title", ""))[:120], "action": str(a.get("action", ""))[:600], "why": str(a.get("why", ""))[:400]}
        if not item["title"] or not item["action"]:
            return "ERROR: title and action are required"
        with session_scope() as s:
            run = s.get(Run, self.run_id)
            summary = dict(run.summary or {})
            summary["recommendations"] = [*summary.get("recommendations", []), item][:8]
            run.summary = summary
        activity.emit(f"Recorded a bigger step: {item['title'][:90]}", "step")
        return "recorded"

    def _t_search_kb(self, a: dict) -> str:
        activity.emit(f"Checking what we know about your business: “{str(a.get('query', ''))[:70]}”", "tool")
        with session_scope() as s:
            return json.dumps(kb.search(s, s.get(Project, self.project_id), str(a["query"])))

    def _t_read_page(self, a: dict) -> str:
        with session_scope() as s:
            p = s.get(Page, int(a["page_id"]))
            if p is None or p.project_id != self.project_id:
                return "ERROR: no such page"
            activity.emit(f"Reading your page: {p.url.replace('https://', '').replace('http://', '')[:80]}", "tool")
            html = snapshots.live_content(s, p) or ""
        return html[:MAX_PAGE_CHARS] + ("\n...[truncated]" if len(html) > MAX_PAGE_CHARS else "")

    def _t_web_search(self, a: dict) -> str:
        activity.emit(f"Checking how others answer: “{str(a.get('query', ''))[:70]}”", "tool")
        if self.provider is None:
            return "ERROR: web search unavailable"
        return json.dumps([{"url": h.url, "title": h.title, "snippet": h.snippet[:300]}
                           for h in self.provider.search(str(a["query"]), 5)])

    def _t_propose_change(self, a: dict) -> str:
        with session_scope() as s:
            project = s.get(Project, self.project_id)
            page = s.get(Page, int(a["page_id"]))
            if page is None or page.project_id != self.project_id:
                return "ERROR: no such page"
            _, brief = get_brief(s, self.project_id, self.brief_version)
            old_html = snapshots.live_content(s, page) or ""
            report, new_html = guard.check(old_html, a["ops"], page.url, brief.constraints,
                                           kb_text=kb.grounding_text(s, project))
            status = "candidate" if report.ok else "blocked"
            prev = self.proposals.get(page.id)
            if report.ok:
                if prev:
                    old = s.get(ChangeProposal, prev)
                    old.status = "rejected"
                    old.guard_report = {**old.guard_report, "superseded": True}
                v = snapshots.new_version(s, page, new_html, "candidate", parent_id=page.live_version_id,
                                          run_id=self.run_id, note=a["rationale"][:500])
            cp = ChangeProposal(run_id=self.run_id, page_id=page.id, ops=a["ops"], rationale=a["rationale"],
                                target_questions=a.get("target_questions", []), status=status,
                                guard_report=report.to_dict(), base_version_id=page.live_version_id,
                                candidate_version_id=v.id if report.ok else None)
            s.add(cp)
            s.flush()
            if report.ok:
                self.proposals[page.id] = cp.id
            cp_id = cp.id
        audit.record("optimizer.proposal_" + status, "optimizer", {"proposal_id": cp_id, "page_id": a["page_id"],
                                                                  "violations": report.violations,
                                                                  "warnings": report.warnings},
                     project_id=self.project_id, run_id=self.run_id)
        if report.ok:
            activity.emit(f"Suggested a change to a page (passed all safety checks): {a['rationale'][:110]}", "step")
            return f"ACCEPTED as candidate (proposal {cp_id}). Warnings: {report.warnings or 'none'}"
        activity.emit(f"Blocked an idea to keep you safe: {report.violations[0][:120]}", "warn")
        return "BLOCKED by guard. Violations: " + "; ".join(report.violations)

    def _t_finish(self, a: dict) -> str:
        self.done, self.summary = True, str(a.get("summary", ""))
        return "ok"

    # ---- the loop ---------------------------------------------------------------------------
    def run(self, max_steps: int = 25) -> list[int]:
        with session_scope() as s:
            project = s.get(Project, self.project_id)
            _, brief = get_brief(s, self.project_id, self.brief_version)
            card = kb.card(s, project)
        stable = f"{SYSTEM}\n\n## Company knowledge\n{card}\n\n## Brief\n{brief.model_dump_json(indent=1)}"
        opening = "Begin. Start with get_weak_questions, get_findability and list_pages."
        if self.history:
            opening += f"\n\nWhat the previous iteration achieved (learn from it; do not repeat what failed): {self.history}"
        messages: list[dict] = [{"role": "system", "content": stable}, {"role": "user", "content": opening}]
        nudges = 0
        for step in range(max_steps):
            activity.check_cancelled()
            activity.emit("The AI is thinking about the next step…", "info")
            res = llm.chat("optimizer", messages, tools=TOOLS, role="optimizer", max_tokens=16000)
            activity.tick()
            messages.append(res.message)
            if not res.tool_calls:
                # Smaller models sometimes answer in prose instead of calling a tool. Nudge, then give up.
                if not self.proposals and nudges < 2:
                    nudges += 1
                    messages.append({"role": "user", "content": "Please use the tools: call get_weak_questions, read_page, then propose_change (or finish)."})
                    continue
                break
            for c in res.tool_calls:
                handler = getattr(self, f"_t_{c.name}", None)
                try:
                    out = handler(dict(c.args)) if handler else f"ERROR: unknown tool {c.name}"
                    err = out.startswith("ERROR")
                except Exception as e:
                    out, err = f"ERROR: {type(e).__name__}: {e}", True
                audit.record("optimizer.tool", "optimizer", {"step": step, "tool": c.name, "input": dict(c.args),
                                                              "output_preview": out[:300]},
                             project_id=self.project_id, run_id=self.run_id)
                messages.append({"role": "tool", "tool_call_id": c.id, "content": out})
            if self.done:
                break
        else:
            audit.record("optimizer.step_limit", "optimizer", {"max_steps": max_steps},
                         project_id=self.project_id, run_id=self.run_id)
        audit.record("optimizer.finished", "optimizer", {"summary": self.summary,
                                                        "proposals": list(self.proposals.values())},
                     project_id=self.project_id, run_id=self.run_id)
        return list(self.proposals.values())


__all__ = ["Optimizer", "domain_of"]
