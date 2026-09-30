from functools import lru_cache

from google import genai
from google.genai import types

from .. import usage
from ..search.sandbox import TOOL_SPECS, ToolSession
from .base import CONTROLLED_SYSTEM, Engine, EngineAnswer, Turn, register


@lru_cache
def _client() -> genai.Client:
    return genai.Client()  # GEMINI_API_KEY / GOOGLE_API_KEY from env


def _log(resp, model: str) -> None:
    u = resp.usage_metadata
    if u is not None:
        cached = u.cached_content_token_count or 0
        usage.record("engine:gemini", "google", model, (u.prompt_token_count or 0) - cached,
                     (u.candidates_token_count or 0) + (u.thoughts_token_count or 0), cached)


def _contents(convo: list[Turn]) -> list[types.Content]:
    return [types.Content(role="model" if t.role == "assistant" else "user", parts=[types.Part(text=t.content)])
            for t in convo]


def _shape(resp) -> list[str]:
    return sorted(k for k, v in resp.model_dump().items() if v is not None and k != "sdk_http_response")


def _text(resp) -> str:
    try:
        return resp.text or ""
    except ValueError:
        return ""


@register("gemini")
class GeminiEngine(Engine):
    provider = "google"

    def controlled(self, convo: list[Turn], tools: ToolSession) -> EngineAnswer:
        decls = [types.FunctionDeclaration(name=n, description=d, parameters_json_schema=s) for n, d, s in TOOL_SPECS]
        contents = _contents(convo)
        resp = None
        for step in range(self.max_steps + 1):
            last = step == self.max_steps
            cfg = types.GenerateContentConfig(
                system_instruction=CONTROLLED_SYSTEM,
                tools=[types.Tool(function_declarations=decls)],
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                tool_config=types.ToolConfig(function_calling_config=types.FunctionCallingConfig(
                    mode=types.FunctionCallingConfigMode.NONE if last else types.FunctionCallingConfigMode.AUTO)),
            )
            resp = _client().models.generate_content(model=self.model, contents=contents, config=cfg)
            _log(resp, self.model)
            calls = resp.function_calls or []
            if not calls:
                break
            contents.append(resp.candidates[0].content)
            contents.append(types.Content(role="user", parts=[
                types.Part.from_function_response(name=c.name, response={"result": tools.execute(c.name, dict(c.args or {}))})
                for c in calls
            ]))
        return EngineAnswer(text=_text(resp), model_id=resp.model_version or self.model, steps=step + 1,
                            raw_shape=_shape(resp))

    def native(self, convo: list[Turn]) -> EngineAnswer:
        resp = _client().models.generate_content(
            model=self.model, contents=_contents(convo),
            config=types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())]))
        _log(resp, self.model)
        cites, queries = [], []
        gm = resp.candidates[0].grounding_metadata if resp.candidates else None
        if gm is not None:
            queries = list(gm.web_search_queries or [])
            for ch in gm.grounding_chunks or []:
                if ch.web is None:
                    continue
                # Grounding URIs are Google redirect links; the domain/title field names the real site.
                site = ch.web.domain or ch.web.title
                cites.append(f"https://{site}/" if site and "." in site else ch.web.uri)
        cites = list(dict.fromkeys(c for c in cites if c))
        return EngineAnswer(text=_text(resp), citations=cites, retrieved_urls=cites, queries=queries,
                            model_id=resp.model_version or self.model, raw_shape=_shape(resp))

    def list_models(self) -> list[str]:
        return [m.name.removeprefix("models/") for m in _client().models.list()]
