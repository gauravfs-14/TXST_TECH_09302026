from functools import lru_cache

import anthropic

from .. import usage


@lru_cache
def client() -> "anthropic.Anthropic":
    return anthropic.Anthropic(max_retries=4)  # ANTHROPIC_API_KEY from the environment


from ..search.sandbox import TOOL_SPECS, ToolSession
from .base import CONTROLLED_SYSTEM, Engine, EngineAnswer, Turn, register

# Models without dynamic-filtering web search fall back to the basic tool variant.
_BASIC_SEARCH_MODELS = {"claude-haiku-4-5"}


def _log(resp, model: str) -> None:
    u = resp.usage
    usage.record("engine:claude", "anthropic", model, u.input_tokens, u.output_tokens,
                 getattr(u, "cache_read_input_tokens", 0) or 0, getattr(u, "cache_creation_input_tokens", 0) or 0)


def _text(resp) -> str:
    return "".join(b.text for b in resp.content if b.type == "text")


def _shape(resp) -> list[str]:
    return sorted(set(resp.model_dump().keys()) | {f"block:{b.type}" for b in resp.content})


@register("claude")
class ClaudeEngine(Engine):
    provider = "anthropic"

    def controlled(self, convo: list[Turn], tools: ToolSession) -> EngineAnswer:
        tool_defs = [{"name": n, "description": d, "input_schema": s, "strict": True} for n, d, s in TOOL_SPECS]
        messages: list = [{"role": t.role, "content": t.content} for t in convo]
        resp = None
        for step in range(self.max_steps + 1):
            last = step == self.max_steps
            resp = client().messages.create(
                model=self.model, max_tokens=8000, system=CONTROLLED_SYSTEM, tools=tool_defs, messages=messages,
                **({"tool_choice": {"type": "none"}} if last else {}),
            )
            _log(resp, self.model)
            if resp.stop_reason == "refusal":
                return EngineAnswer(error="refusal", model_id=resp.model, steps=step + 1)
            uses = [b for b in resp.content if b.type == "tool_use"]
            if not uses:
                break
            messages.append({"role": "assistant", "content": resp.content})
            messages.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": u.id, "content": tools.execute(u.name, u.input)} for u in uses
            ]})
        return EngineAnswer(text=_text(resp), model_id=resp.model, steps=step + 1, raw_shape=_shape(resp))

    def native(self, convo: list[Turn]) -> EngineAnswer:
        tool_type = "web_search_20250305" if self.model in _BASIC_SEARCH_MODELS else "web_search_20260209"
        messages: list = [{"role": t.role, "content": t.content} for t in convo]
        texts, cites, retrieved, queries = [], [], [], []
        resp = None
        for _ in range(4):  # resume pause_turn a few times
            resp = client().messages.create(model=self.model, max_tokens=8000, messages=messages,
                                            tools=[{"type": tool_type, "name": "web_search", "max_uses": 5}])
            _log(resp, self.model)
            for b in resp.content:
                if b.type == "server_tool_use":
                    queries.append((b.input or {}).get("query", ""))
                elif b.type == "web_search_tool_result" and isinstance(b.content, list):
                    retrieved += [r.url for r in b.content if getattr(r, "url", None)]
                elif b.type == "text":
                    texts.append(b.text)
                    cites += [c.url for c in (b.citations or []) if getattr(c, "url", None)]
            if resp.stop_reason != "pause_turn":
                break
            messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason == "refusal":
            return EngineAnswer(error="refusal", model_id=resp.model)
        return EngineAnswer(text="".join(texts), citations=list(dict.fromkeys(cites)),
                            retrieved_urls=list(dict.fromkeys(retrieved)), queries=queries,
                            model_id=resp.model, raw_shape=_shape(resp))

    def list_models(self) -> list[str]:
        return [m.id for m in client().models.list()]
