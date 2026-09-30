"""The "openai" engine: any OpenAI-compatible endpoint (OpenAI, Ollama, OpenRouter, Groq, LM Studio, vLLM...).

* controlled mode - Chat Completions with our web_search/fetch_page tools. Works on every compatible server.
* native mode     - OpenAI's own hosted web search through the Responses API. Only real OpenAI has it, so
                    for every other server `supports_native` is False and "real world" measurement uses the
                    same tool loop against the live web (see Engine.run_real).
"""

from .. import llm, usage
from ..config import get_settings
from ..search.sandbox import TOOL_SPECS, ToolSession
from .base import CONTROLLED_SYSTEM, Engine, EngineAnswer, Turn, register


def _is_openai(base_url: str) -> bool:
    return "api.openai.com" in base_url


def _citations(resp) -> list[str]:
    out = []
    for item in resp.output:
        if item.type == "message":
            for c in item.content:
                for a in getattr(c, "annotations", None) or []:
                    if a.type == "url_citation":
                        out.append(a.url)
    return list(dict.fromkeys(out))


@register("openai")
class OpenAIEngine(Engine):
    provider = "openai-compatible"

    @property
    def supports_native(self) -> bool:
        return _is_openai(get_settings().llm_base_url)

    def controlled(self, convo: list[Turn], tools: ToolSession) -> EngineAnswer:
        specs = [{"name": n, "description": d, "parameters": s} for n, d, s in TOOL_SPECS]
        messages: list[dict] = [{"role": "system", "content": CONTROLLED_SYSTEM}] + [{"role": t.role, "content": t.content} for t in convo]
        res = None
        for step in range(self.max_steps + 1):
            last = step == self.max_steps
            res = llm.chat("engine:openai", messages, tools=None if last else specs, model=self.model, max_tokens=4000)
            if not res.tool_calls:
                break
            messages.append(res.message)
            for c in res.tool_calls:
                messages.append({"role": "tool", "tool_call_id": c.id, "content": tools.execute(c.name, c.args)})
        return EngineAnswer(text=res.text, model_id=self.model, steps=step + 1, raw_shape=["choices", "message"])

    def native(self, convo: list[Turn]) -> EngineAnswer:
        if not self.supports_native:
            return EngineAnswer(error="This provider has no built-in web search.", model_id=self.model)
        resp = llm.client().responses.create(model=self.model, input=[{"role": t.role, "content": t.content} for t in convo],
                                            tools=[{"type": "web_search"}], include=["web_search_call.action.sources"])
        u = resp.usage
        if u is not None:
            cached = getattr(getattr(u, "input_tokens_details", None), "cached_tokens", 0) or 0
            usage.record("engine:openai-native", "openai", self.model, u.input_tokens - cached, u.output_tokens, cached)
        queries, retrieved = [], []
        for item in resp.output:
            if item.type == "web_search_call":
                action = getattr(item, "action", None)
                if getattr(action, "query", None):
                    queries.append(action.query)
                retrieved += [s.url for s in (getattr(action, "sources", None) or []) if getattr(s, "url", None)]
        shape = sorted(set(resp.model_dump().keys()) | {f"item:{i.type}" for i in resp.output})
        return EngineAnswer(text=llm.clean(resp.output_text), citations=_citations(resp), retrieved_urls=retrieved,
                            queries=queries, model_id=resp.model, raw_shape=shape)

    def list_models(self) -> list[str]:
        return [m.id for m in llm.client().models.list()]

