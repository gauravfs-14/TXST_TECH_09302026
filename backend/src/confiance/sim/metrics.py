"""Visibility scoring for one engine answer. Deterministic metrics first; an optional cheap LLM judge
adds accuracy/sentiment. Judge input is the compact KB card, not the site, to keep tokens low."""

import re
from dataclasses import dataclass

from .. import llm
from ..engines.base import _URL, EngineAnswer
from ..textutil import domain_of, same_site

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


def score(ans: EngineAnswer, t: Target, *, kb_card: str = "", prompt: str = "", judge: bool = False) -> dict:
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
    }
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
    """Single 0-1 number per answer, used for paired comparisons. Weights favour being cited/recommended
    over merely appearing in text."""
    if not m.get("answered"):
        return 0.0
    v = 0.25 * m["mentioned"] + 0.40 * m["cited"] + 0.10 * m["retrieved"]
    if m.get("recommended") is not None:
        v += 0.25 * m["recommended"]
    else:
        v += 0.25 * (m["mentioned"] and m["cited"])
    return min(v, 1.0)
