"""Visibility scoring for one engine answer. Deterministic metrics first; an optional cheap LLM judge
adds accuracy/sentiment. Judge input is the compact KB card, not the site, to keep tokens low."""

import re
from dataclasses import dataclass

from .. import llm
from ..engines.base import _URL, EngineAnswer
from ..textutil import domain_of, same_site, shingles

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "accuracy": {"type": "integer", "description": "0-5: are statements about the brand consistent with the facts? 5 = all correct, 0 = contradicts facts. Use 3 if the brand is not discussed."},
        "sentiment": {"type": "integer", "description": "-2 (negative) to 2 (very positive) toward the brand; 0 if not mentioned."},
        "recommended": {"type": "boolean", "description": "Does the answer actively recommend the brand as a good option for the user's need?"},
        "notes": {"type": "string"},
    },
    "required": ["accuracy", "sentiment", "recommended", "notes"], "additionalProperties": False,
}


@dataclass
class Target:
    domain: str
    aliases: list[str]
    competitors: list[str]  # domains

    def alias_re(self) -> re.Pattern:
        names = [a for a in {*self.aliases, domain_of(self.domain)} if a]
        return re.compile("|".join(rf"(?<!\w){re.escape(a)}(?!\w)" for a in names), re.I) if names else re.compile(r"$^")


def score(ans: EngineAnswer, t: Target, *, kb_card: str = "", prompt: str = "", judge: bool = False,
          page_texts: list[str] | None = None) -> dict:
    text = ans.text or ""
    prose = _URL.sub(" ", text)  # a cited URL is a citation, not a mention in the prose
    m = t.alias_re().search(prose)
    cites = ans.citations
    cite_idx = next((i for i, u in enumerate(cites) if same_site(u, t.domain)), None)
    retrieved = any(same_site(u, t.domain) for u in ans.retrieved_urls)
    comp_mentions = [c for c in t.competitors if re.search(rf"(?<!\w){re.escape(domain_of(c).split('.')[0])}(?!\w)", prose, re.I)]
    comp_cited = [c for c in t.competitors if any(same_site(u, c) for u in cites)]
    metrics = {
        "answered": bool(text) and not ans.error,
        "mentioned": m is not None,
        "mention_pos": (m.start() / max(len(prose), 1)) if m else None,
        "cited": cite_idx is not None,
        "cite_rank": None if cite_idx is None else cite_idx + 1,
        "retrieved": retrieved,
        "competitors_mentioned": comp_mentions,
        "competitors_cited": comp_cited,
        "n_citations": len(cites),
        "answer_chars": len(text),
        "searched": bool(ans.queries),
        "exposed": bool(getattr(ans, "exposed", False)) or retrieved,
    }
    if page_texts is not None:
        # Did the answer draw on the client's page? Share of the answer's 4-word phrases that appear on it.
        # Far more sensitive than "was the brand named", which stays at 0 until everything else is right.
        a = shingles(prose)
        page = set().union(*[shingles(x) for x in page_texts]) if page_texts else set()
        hit = len(a & page)
        overlap = hit / max(len(a), 1)
        metrics["page_overlap"] = round(overlap, 4)
        metrics["used_page"] = bool(metrics["exposed"]) and hit >= 3 and overlap >= 0.03
    if judge and metrics["answered"]:
        try:
            j = llm.json_call(
                "judge", system=llm.cached_system(
                    "You grade an AI assistant's answer for how it treats one brand. Facts about the brand:\n" + kb_card),
                prompt=f"User question: {prompt}\n\nAssistant answer:\n{text[:6000]}",
                schema=JUDGE_SCHEMA, max_tokens=500)
            metrics.update({"accuracy": j["accuracy"], "sentiment": j["sentiment"],
                            "recommended": j["recommended"], "judge_notes": j["notes"]})
        except Exception as e:  # judge failure must not lose the deterministic metrics
            metrics["judge_error"] = str(e)[:200]
    return metrics


def visibility_score(m: dict) -> float:
    """Single 0-1 number per answer, used for paired comparisons. Being cited or recommended counts most;
    when page usage was measured, drawing on the page's content counts too."""
    if not m.get("answered"):
        return 0.0
    rec = m["recommended"] if m.get("recommended") is not None else bool(m["mentioned"] and m["cited"])
    if "used_page" in m:
        # Graded, not yes/no: 10% of the answer's phrases coming from the page counts as fully using it. Mentions and
        # links saturate as soon as the page is in front of the assistant, so this is where gains show up first.
        used = min(1.0, m.get("page_overlap", 0.0) / 0.10) if "page_overlap" in m else float(m["used_page"])
        v = 0.20 * m["mentioned"] + 0.25 * m["cited"] + 0.20 * used + 0.10 * bool(m.get("exposed")) + 0.25 * rec
    else:  # results stored before page usage was measured
        v = 0.25 * m["mentioned"] + 0.40 * m["cited"] + 0.10 * m["retrieved"] + 0.25 * rec
    return min(v, 1.0)
