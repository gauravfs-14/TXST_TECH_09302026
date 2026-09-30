"""Optimizer: a ReAct agent (reason -> act -> observe -> repeat) that drafts page changes.

It runs once per loop. In loop 1 it works from the research; in later loops it also sees how the previous draft
performed in the sandbox and revises. Every proposal is checked by the code guard *inside* the tool call, so a
blocked proposal comes back as an observation and the agent can fix it, the same loop a human editor would follow.
"""

import json
from collections import defaultdict
from urllib.parse import urlsplit

from sqlalchemy import select

from .. import activity, audit, kb, llm, snapshots
from ..brief import get as get_brief
from ..db import session_scope
from ..discovery.site import classify_url
from ..models import ChangeProposal, Page, Project, Run
from ..search.base import SearchProvider
from ..services import scan as scan_mod
from ..sim.runner import load_rows
from ..textutil import html_to_text, norm_url
from . import guard, newpage
from .ops import OP_DOC, OP_SCHEMA

MAX_PAGE_CHARS = 14_000

SYSTEM = """You are the optimizer inside CONFIANCE, a Generative Engine Optimization system. AI answer engines
(ChatGPT, Claude, Gemini, ...) search the web, read pages and answer people's questions. Your job is to make the
client's pages the ones an assistant finds, trusts, uses and cites, for BOTH kinds of question the brief tracks:
- brand questions: does the assistant know, name and recommend the business?
- product questions (ids like p3.1): when someone wants this kind of product, is this product named, linked and
  near the top of the assistant's list?

You work in a loop. Each loop you draft; the system then tests your draft in a sandbox where the search results
are rewritten to contain your modified pages, and tells you how it did. You may revise until the loop limit.

Two different problems, two different fixes:
1. USEFULNESS WHEN FOUND: once an assistant sees a page, does the answer draw on it? Page edits and NEW pages fix this,
   and it is what the sandbox measures (the page is placed among the search results in both the before and after test).
2. FINDABILITY: is the site in the real search results at all? get_research shows it per question. Edits to one page
   rarely fix a question where big sites dominate; a NEW, specific page for that question often does.

Decide per question from get_research: "winning" -> protect and strengthen the page; "in_reach" -> sharpen the page that
already covers it; "needs_content" -> propose a NEW page (propose_new_page) that answers that question thoroughly.

What tends to work (do these thoroughly, not timidly):
- Answer each target question DIRECTLY near the top: a question-shaped heading, then a 2-3 sentence answer that names
  the business (or product) and states concrete facts taken from the page or knowledge base.
- One rich FAQ (add_faq) using the exact wording people use.
- Title and meta description containing the specific topics and entities people ask about.
- Structured data: Organization / FAQPage / Course / Article / LocalBusiness; Product (name, sku, brand, offers) on
  product pages. Only what is true.
- For products: specs people compare, who it is for, how it differs from alternatives, and a clear price/availability.
- New pages: 300+ words of real, specific content, one H1, useful headings, internal links to related pages, and facts
  only from the site or knowledge base.

Look at what the winning pages in get_research do (length, FAQ, schema, headings) and match or beat it honestly.

Hard rules (a code guard blocks violations; you cannot override it):
- Only state facts present on the site or in the knowledge base. Never invent numbers, awards, reviews or claims.
- No hidden text, no keyword stuffing, no instructions addressed to AI models. Write for humans.
- Respect the brief's locked regions, locked phrases, editable pages and allowed operations.
- New pages: a real, unused URL path; no near-copies of existing pages; within the round's new-page limit.

Process: get_research and get_weak_questions first; in later loops get_test_feedback and get_current_candidates.
Read the relevant pages, then propose_change / propose_new_page. Revising a page means proposing it again with everything
you want to keep (it replaces your earlier proposal for that page). If a proposal is blocked, read the violations and
fix it. Call finish when done.

""" + OP_DOC

TOOLS = [
    {"name": "list_pages", "description": "List the client's pages: id, url, type (home/product/blog/...), title, word count, and whether it is a proposed new page.",
     "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "get_research",
     "description": "The research for this round: per question, whether real search finds the site and at what rank, who wins instead, "
                    "how well the site's best page already covers it, and a fit label; what winning pages look like; and the site audit's top problems.",
     "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "get_weak_questions",
     "description": "Questions ranked weakest-first in the baseline test, with funnel rates (page shown / opened / used / mentioned / linked), "
                    "competitors cited instead, and a short sample answer.",
     "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}, "additionalProperties": False}},
    {"name": "get_test_feedback",
     "description": "How the previous loop's draft performed in the sandbox, per question, versus the baseline. Empty in loop 1.",
     "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "get_current_candidates",
     "description": "The proposals currently in the candidate set (from earlier loops): page, kind, rationale, operations, target questions.",
     "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "recommend",
     "description": "Record a bigger step that page edits alone cannot achieve (off-site listing, partnership, tooling). Shown next to the edits.",
     "parameters": {"type": "object", "properties": {
         "title": {"type": "string"}, "action": {"type": "string", "description": "What to do, concretely"},
         "why": {"type": "string", "description": "Which questions it helps and why"}},
         "required": ["title", "action", "why"], "additionalProperties": False}},
    {"name": "search_kb", "description": "Search the company knowledge base for passages/facts.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"], "additionalProperties": False}},
    {"name": "read_page", "description": "Read a page's current HTML (truncated) by page id. For a proposed new page, returns your draft.",
     "parameters": {"type": "object", "properties": {"page_id": {"type": "integer"}}, "required": ["page_id"], "additionalProperties": False}},
    {"name": "web_search", "description": "Search the real web (e.g. to see who answers a question today).",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"], "additionalProperties": False}},
    {"name": "propose_change",
     "description": "Propose edits to one existing page. Checked immediately against the brief's constraints.",
     "parameters": {"type": "object", "properties": {
         "page_id": {"type": "integer"}, "ops": {"type": "array", "items": OP_SCHEMA}, "rationale": {"type": "string"},
         "target_questions": {"type": "array", "items": {"type": "string"}, "description": "question ids this helps (brand q1.. or product p3.1..)"}},
         "required": ["page_id", "ops", "rationale", "target_questions"], "additionalProperties": False}},
    {"name": "propose_new_page",
     "description": "Propose a brand-new page for questions the existing pages can't answer. Checked immediately.",
     "parameters": {"type": "object", "properties": {
         "path": {"type": "string", "description": "URL path, lowercase with hyphens, e.g. /guides/linux-for-beginners"},
         "title": {"type": "string"}, "meta_description": {"type": "string"},
         "body_html": {"type": "string", "description": "The page content as HTML: one H1, headings, paragraphs, lists. No scripts or forms."},
         "json_ld": {"type": "string", "description": "Optional schema.org JSON-LD as a JSON string (Article, Course, FAQPage, Product...)"},
         "rationale": {"type": "string"}, "target_questions": {"type": "array", "items": {"type": "string"}}},
         "required": ["path", "title", "meta_description", "body_html", "rationale", "target_questions"], "additionalProperties": False}},
    {"name": "finish", "description": "Stop; summarize what you proposed and what remains.",
     "parameters": {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"], "additionalProperties": False}},
]


class Optimizer:
    def __init__(self, project_id: int, run_id: int, brief_version: int, baseline_batch_id: int | None, provider: SearchProvider | None,
                 *, loop: int = 1, cfg: dict | None = None, carry: dict[int, int] | None = None, feedback: dict | None = None):
        self.project_id, self.run_id, self.brief_version = project_id, run_id, brief_version
        self.baseline_batch_id, self.provider = baseline_batch_id, provider
        self.loop, self.cfg, self.feedback = loop, cfg or {}, feedback
        self.proposals: dict[int, int] = dict(carry or {})  # page_id -> active proposal id (carried over from earlier loops)
        self.touched: set[int] = set()  # pages whose proposal changed in THIS loop
        self.done = False
        self.summary = ""
        self.history = ""  # digest of the previous round's outcome

    # ---- helpers -------------------------------------------------------------------------------
    def _run_summary(self) -> dict:
        with session_scope() as s:
            return dict(s.get(Run, self.run_id).summary or {})

    def _question_texts(self) -> dict[str, str]:
        sm = self._run_summary()
        if sm.get("questions"):
            return {q["id"]: q["text"] for q in sm["questions"]}
        with session_scope() as s:
            _, brief = get_brief(s, self.project_id, self.brief_version)
        return {q.id: q.text for q in brief.target_questions}

    # ---- tool implementations ---------------------------------------------------------------
    def _t_list_pages(self, _: dict) -> str:
        with session_scope() as s:
            out = []
            for p in s.scalars(select(Page).where(Page.project_id == self.project_id, Page.kind == "page")):
                html = snapshots.live_content(s, p)
                if html is None and p.is_new and p.id in self.proposals:
                    cp = s.get(ChangeProposal, self.proposals[p.id])
                    html = snapshots.version_content(s, cp.candidate_version_id) if cp and cp.candidate_version_id else ""
                title, text = html_to_text(html or "")
                out.append({"page_id": p.id, "url": p.url, "type": p.page_type, "title": title, "words": len(text.split()), "proposed_new_page": bool(p.is_new)})
        return json.dumps(out)

    def _t_get_research(self, _: dict) -> str:
        activity.emit("Reading the research for this round", "tool")
        sm = self._run_summary()
        research = sm.get("research") or {}
        with session_scope() as s:
            rec = scan_mod.latest(s, self.project_id)
            findings = [{"severity": f["severity"], "title": f["title"]} for f in (rec.data["audit"]["findings"] if rec else [])[:8]]
            score = rec.score if rec else None
        return json.dumps({
            "summary": research.get("summary"),
            "questions": [{k: e.get(k) for k in ("id", "query", "status", "rank", "fit", "fit_reason", "best_page", "coverage", "top_domains", "product_rank")} for e in research.get("queries", [])],
            "brand_search": {k: (research.get("brand") or {}).get(k) for k in ("status", "rank", "top_domains")},
            "winning_pages": research.get("patterns"), "example_competitors": [{k: c[k] for k in ("domain", "title", "words", "h2", "has_faq")} for c in research.get("competitors", [])[:4]],
            "site_audit": {"score": score, "top_problems": findings}})

    def _t_get_weak_questions(self, a: dict) -> str:
        activity.emit("Looking at which questions do worst today", "tool")
        if not self.baseline_batch_id:
            return "[]"
        with session_scope() as s:
            rows = load_rows(s, self.baseline_batch_id)
        text = self._question_texts()
        by = defaultdict(list)
        for r in rows:
            by[r["question_id"]].append(r)
        out = []
        rate = lambda rs, k: round(sum(bool(r["metrics"].get(k)) for r in rs) / len(rs), 3)
        for qid, rs in by.items():
            comp = defaultdict(int)
            for r in rs:
                for c in r["metrics"].get("competitors_cited", []):
                    comp[c] += 1
            worst = min(rs, key=lambda r: r["score"])
            out.append({"question_id": qid, "question": text.get(qid, ""), "visibility": round(sum(r["score"] for r in rs) / len(rs), 3),
                        "page_shown_rate": rate(rs, "exposed"), "page_opened_rate": rate(rs, "fetched"), "page_used_rate": rate(rs, "used_page"),
                        "mentioned_rate": rate(rs, "mentioned"), "cited_rate": rate(rs, "cited"),
                        **({"product_named_rate": rate(rs, "product_mentioned"), "product_linked_rate": rate(rs, "product_cited")} if any("product_mentioned" in r["metrics"] for r in rs) else {}),
                        "competitors_cited": dict(comp), "sample_answer": (worst["answer"] or "")[:500]})
        out.sort(key=lambda x: x["visibility"])
        return json.dumps(out[: int(a.get("limit") or 10)])

    def _t_get_test_feedback(self, _: dict) -> str:
        activity.emit("Reading how the last draft did in testing", "tool")
        return json.dumps(self.feedback) if self.feedback else "No test results yet: this is the first loop."

    def _t_get_current_candidates(self, _: dict) -> str:
        with session_scope() as s:
            out = []
            for pid, cpid in self.proposals.items():
                cp, page = s.get(ChangeProposal, cpid), s.get(Page, pid)
                out.append({"proposal_id": cpid, "page_id": pid, "url": page.url, "kind": cp.kind, "rationale": cp.rationale, "target_questions": cp.target_questions,
                            "operations": [o.get("type") for o in cp.ops], "changed_this_loop": pid in self.touched})
        return json.dumps(out)

    def _t_recommend(self, a: dict) -> str:
        item = {"title": str(a.get("title", ""))[:120], "action": str(a.get("action", ""))[:600], "why": str(a.get("why", ""))[:400]}
        if not item["title"] or not item["action"]:
            return "ERROR: title and action are required"
        with session_scope() as s:
            run = s.get(Run, self.run_id)
            summary = dict(run.summary or {})
            summary["recommendations"] = [*summary.get("recommendations", []), item][:10]
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
            html = snapshots.live_content(s, p)
            if html is None and p.id in self.proposals:
                cp = s.get(ChangeProposal, self.proposals[p.id])
                html = snapshots.version_content(s, cp.candidate_version_id) if cp and cp.candidate_version_id else ""
        html = html or ""
        return html[:MAX_PAGE_CHARS] + ("\n...[truncated]" if len(html) > MAX_PAGE_CHARS else "")

    def _t_web_search(self, a: dict) -> str:
        activity.emit(f"Checking how others answer: “{str(a.get('query', ''))[:70]}”", "tool")
        if self.provider is None:
            return "ERROR: web search unavailable"
        try:
            return json.dumps([{"url": h.url, "title": h.title, "snippet": h.snippet[:300]} for h in self.provider.search(str(a["query"]), 5)])
        except Exception as e:
            return f"ERROR: the search service had a problem ({str(e)[:80]}); try a simpler query"

    def _record(self, page: Page, cp: ChangeProposal, report, status: str, rationale: str) -> str:
        audit.record("optimizer.proposal_" + status, "optimizer", {"proposal_id": cp.id, "page_id": page.id, "kind": cp.kind, "loop": self.loop,
                                                                  "violations": report.violations, "warnings": report.warnings},
                     project_id=self.project_id, run_id=self.run_id)
        if report.ok:
            activity.emit(f"Suggested {'a new page' if cp.kind == 'new_page' else 'a change to a page'} (passed all safety checks): {rationale[:110]}", "step")
            return f"ACCEPTED as candidate (proposal {cp.id}). Warnings: {report.warnings or 'none'}"
        activity.emit(f"Blocked an idea to keep you safe: {report.violations[0][:120]}", "warn")
        return "BLOCKED by guard. Violations: " + "; ".join(report.violations)

    def _supersede(self, s, page_id: int) -> None:
        prev = self.proposals.get(page_id)
        if prev:
            old = s.get(ChangeProposal, prev)
            old.status = "superseded"
            old.guard_report = {**old.guard_report, "superseded": True}

    def _t_propose_change(self, a: dict) -> str:
        with session_scope() as s:
            project = s.get(Project, self.project_id)
            page = s.get(Page, int(a["page_id"]))
            if page is None or page.project_id != self.project_id:
                return "ERROR: no such page"
            if page.is_new:
                return "ERROR: that is a proposed new page; use propose_new_page with the same path to revise it"
            _, brief = get_brief(s, self.project_id, self.brief_version)
            old_html = snapshots.live_content(s, page) or ""
            report, new_html = guard.check(old_html, a["ops"], page.url, brief.constraints, kb_text=kb.grounding_text(s, project))
            status = "candidate" if report.ok else "blocked"
            if report.ok:
                self._supersede(s, page.id)
                v = snapshots.new_version(s, page, new_html, "candidate", parent_id=page.live_version_id, run_id=self.run_id, note=a["rationale"][:500])
            cp = ChangeProposal(run_id=self.run_id, page_id=page.id, ops=a["ops"], rationale=a["rationale"], target_questions=a.get("target_questions", []),
                                status=status, guard_report=report.to_dict(), loop=self.loop, kind="edit", base_version_id=page.live_version_id,
                                candidate_version_id=v.id if report.ok else None)
            s.add(cp)
            s.flush()
            if report.ok:
                self.proposals[page.id] = cp.id
                self.touched.add(page.id)
            return self._record(page, cp, report, status, a["rationale"])

    def _t_propose_new_page(self, a: dict) -> str:
        with session_scope() as s:
            project = s.get(Project, self.project_id)
            _, brief = get_brief(s, self.project_id, self.brief_version)
            origin = project.site_url or f"https://{project.domain}"
            path = "/" + str(a["path"]).strip().strip("/").lower()
            url = origin.rstrip("/") + path
            existing, mine = {}, None
            for p in s.scalars(select(Page).where(Page.project_id == self.project_id, Page.kind == "page")):
                if norm_url(p.url) == norm_url(url) and p.is_new:
                    mine = p  # revising my own earlier draft of this same page
                    continue
                html = snapshots.live_content(s, p)
                if html:
                    existing[norm_url(p.url)] = html_to_text(html)[1]
            others = sum(1 for pid in self.proposals if pid != (mine.id if mine else None) and s.get(Page, pid).is_new)
            try:
                jsonld = json.loads(a["json_ld"]) if a.get("json_ld") else None
            except ValueError:
                jsonld = None
            report, html = newpage.check(path, a["title"], a["meta_description"], a["body_html"], origin=origin, existing=existing, c=brief.constraints,
                                         kb_text=kb.grounding_text(s, project), allow_new=bool(self.cfg.get("allow_new_pages", True)),
                                         max_new=int(self.cfg.get("max_new_pages", 3)), new_so_far=others, jsonld=jsonld)
            status = "candidate" if report.ok else "blocked"
            page = mine
            if report.ok:
                if page is None:
                    page = Page(project_id=self.project_id, url=url, kind="page", is_new=True, origin="proposed", page_type=classify_url(url) if classify_url(url) != "other" else "blog")
                    s.add(page)
                    s.flush()
                self._supersede(s, page.id)
                v = snapshots.new_version(s, page, html, "candidate", parent_id=None, run_id=self.run_id, note=a["rationale"][:500])
            else:
                page = page or s.scalars(select(Page).where(Page.project_id == self.project_id, Page.kind == "page")).first()
            ops = [{"type": "create_page", "path": path, "title": a["title"], "meta_description": a["meta_description"], "html": a["body_html"], "json_ld": a.get("json_ld")}]
            cp = ChangeProposal(run_id=self.run_id, page_id=page.id, ops=ops, rationale=a["rationale"], target_questions=a.get("target_questions", []),
                                status=status, guard_report=report.to_dict(), loop=self.loop, kind="new_page", base_version_id=None,
                                candidate_version_id=v.id if report.ok else None)
            s.add(cp)
            s.flush()
            if report.ok:
                self.proposals[page.id] = cp.id
                self.touched.add(page.id)
            return self._record(page, cp, report, status, a["rationale"])

    def _t_finish(self, a: dict) -> str:
        self.done, self.summary = True, str(a.get("summary", ""))
        return "ok"

    # ---- the loop ---------------------------------------------------------------------------
    def run(self, max_steps: int = 30) -> list[int]:
        with session_scope() as s:
            project = s.get(Project, self.project_id)
            _, brief = get_brief(s, self.project_id, self.brief_version)
            card = kb.card(s, project)
        stable = f"{SYSTEM}\n\n## Company knowledge\n{card}\n\n## Brief\n{brief.model_dump_json(indent=1)}"
        max_loops = int(self.cfg.get("max_loops", 3))
        if self.loop == 1:
            opening = f"Loop 1 of up to {max_loops}. Begin with get_research and get_weak_questions, then list_pages."
        else:
            opening = (f"Loop {self.loop} of up to {max_loops}. Your last draft was tested. Call get_test_feedback and get_current_candidates, "
                       "then improve what didn't move and keep what worked. If nothing more can be improved, call finish without proposing.")
        if self.history:
            opening += f"\n\nWhat the previous round achieved (learn from it; do not repeat what failed): {self.history}"
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
                    messages.append({"role": "user", "content": "Please use the tools: call get_research, read_page, then propose_change or propose_new_page (or finish)."})
                    continue
                break
            for c in res.tool_calls:
                handler = getattr(self, f"_t_{c.name}", None)
                try:
                    out = handler(dict(c.args)) if handler else f"ERROR: unknown tool {c.name}"
                    err = out.startswith("ERROR")
                except Exception as e:
                    out, err = f"ERROR: {type(e).__name__}: {e}", True
                audit.record("optimizer.tool", "optimizer", {"loop": self.loop, "step": step, "tool": c.name, "input": {k: (str(v)[:200] if isinstance(v, str) else v) for k, v in dict(c.args).items()},
                                                              "output_preview": out[:300]}, project_id=self.project_id, run_id=self.run_id)
                messages.append({"role": "tool", "tool_call_id": c.id, "content": out})
            if self.done:
                break
        else:
            audit.record("optimizer.step_limit", "optimizer", {"max_steps": max_steps, "loop": self.loop}, project_id=self.project_id, run_id=self.run_id)
        audit.record("optimizer.finished", "optimizer", {"loop": self.loop, "summary": self.summary, "proposals": list(self.proposals.values()),
                                                        "changed_this_loop": sorted(self.touched)}, project_id=self.project_id, run_id=self.run_id)
        return list(self.proposals.values())


__all__ = ["Optimizer", "urlsplit"]
