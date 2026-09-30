"""The AI layer for CONFIANCE's internal agents (KB builder, personas, judge, optimizer).

Talks to any OpenAI-compatible Chat Completions endpoint - OpenAI, Ollama, OpenRouter, Groq, LM Studio,
vLLM... Chat Completions (not the newer Responses API) is used because it is the one every compatible
server implements. Features that servers implement unevenly degrade gracefully:

  * JSON output: try strict json_schema -> json_object -> plain text with tolerant parsing, and
    validate against the schema with one repair retry.
  * token limit parameter: max_tokens, retried as max_completion_tokens if the server insists.
  * tool_choice is never used (Ollama ignores it); we simply omit tools when we want none.
"""

import json
import re
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import httpx
import jsonschema
from openai import BadRequestError, OpenAI

from . import usage
from .config import get_settings


class LLMRefusal(RuntimeError):
    pass


class LLMOutputError(RuntimeError):
    pass


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class LLMResult:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    message: dict = field(default_factory=dict)  # assistant message, ready to append to history
    finish_reason: str = ""


@lru_cache
def client() -> OpenAI:
    s = get_settings()
    # The read timeout is *silence between streamed chunks*, not the whole answer, so long generations
    # from slow local models are fine while a dropped connection is noticed in minutes, not hours.
    return OpenAI(base_url=s.llm_base_url, api_key=s.llm_api_key or "not-needed", max_retries=2,
                  timeout=httpx.Timeout(connect=15.0, read=s.llm_timeout_s, write=60.0, pool=30.0))


def model_for(worker: bool = False) -> str:
    s = get_settings()
    m = (s.llm_worker_model if worker and s.llm_worker_model else s.llm_model)
    if not m:
        raise RuntimeError("No AI model has been chosen yet. Please finish connecting your AI model.")
    return m


_THINK = re.compile(r"<think>.*?</think>", re.S)


def clean(text: str | None) -> str:
    return _THINK.sub("", text or "").strip()


def _record(component: str, model: str, u, prompt_chars: int, out_chars: int) -> None:
    if u is not None:
        cached = getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", 0) or 0
        usage.record(component, "openai-compatible", model, max((u.prompt_tokens or 0) - cached, 0), u.completion_tokens or 0, cached)
    else:  # server didn't report usage: rough estimate (about 4 characters per token)
        usage.record(component, "openai-compatible", model, prompt_chars // 4, out_chars // 4)


def _open_stream(kwargs: dict):
    """Start a streaming request, tolerating servers that reject optional parameters."""
    kw = {**kwargs, "stream": True, "stream_options": {"include_usage": True}}
    for _ in range(3):
        try:
            return client().chat.completions.create(**kw)
        except BadRequestError as e:
            msg = str(e)
            if "stream_options" in msg and "stream_options" in kw:
                kw = {k: v for k, v in kw.items() if k != "stream_options"}
            elif "max_completion_tokens" in msg and "max_tokens" in kw:
                kw = {k: v for k, v in kw.items() if k != "max_tokens"} | {"max_completion_tokens": kwargs["max_tokens"]}
            else:
                raise
    return client().chat.completions.create(**kw)


def chat(component: str, messages: list[dict], *, tools: list[dict] | None = None, model: str | None = None,
         max_tokens: int = 4000, response_format: dict | None = None) -> LLMResult:
    model = model or model_for()
    kwargs: dict[str, Any] = {"model": model, "messages": messages, "max_tokens": max_tokens}
    if tools:
        kwargs["tools"] = [{"type": "function", "function": t} for t in tools]
    if response_format:
        kwargs["response_format"] = response_format

    parts: list[str] = []
    partial: dict[int, dict] = {}
    finish, refusal, u = "", "", None
    for chunk in _open_stream(kwargs):
        if getattr(chunk, "usage", None):
            u = chunk.usage
        if not chunk.choices:
            continue
        ch = chunk.choices[0]
        d = ch.delta
        if d is not None:
            if d.content:
                parts.append(d.content)
            if getattr(d, "refusal", None):
                refusal += d.refusal
            for tc in d.tool_calls or []:
                e = partial.setdefault(tc.index or 0, {"id": "", "name": "", "args": ""})
                if tc.id:
                    e["id"] = tc.id
                if tc.function:
                    e["name"] += tc.function.name or ""
                    e["args"] += tc.function.arguments or ""
        if ch.finish_reason:
            finish = ch.finish_reason
    _record(component, model, u, len(json.dumps(messages, default=str)), sum(map(len, parts)))
    if refusal:
        raise LLMRefusal(f"{component}: the model declined ({refusal[:120]})")

    calls = []
    for _, e in sorted(partial.items()):
        try:
            args = json.loads(e["args"]) if e["args"].strip() else {}
        except json.JSONDecodeError:
            args = {"_unparsed": e["args"]}
        calls.append(ToolCall(e["id"] or f"call_{uuid.uuid4().hex[:12]}", e["name"], args if isinstance(args, dict) else {}))
    text = clean("".join(parts))
    history: dict[str, Any] = {"role": "assistant", "content": text}  # "" not null: some servers (Ollama) reject null content
    if calls:
        history["tool_calls"] = [{"id": c.id, "type": "function",
                                  "function": {"name": c.name, "arguments": json.dumps(c.args)}} for c in calls]
    return LLMResult(text=text, tool_calls=calls, message=history, finish_reason=finish)


def cached_system(stable: str, extra: str = "") -> str:
    """Stable text first so servers with automatic prefix caching (OpenAI, vLLM, Ollama) can reuse it."""
    return stable if not extra else f"{stable}\n\n---\n{extra}"


def _extract_json(text: str) -> Any:
    text = clean(text)
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise


def json_call(component: str, *, system: str, prompt: str, schema: dict, model: str | None = None,
              max_tokens: int = 4000) -> dict:
    """One request that must return JSON matching `schema`."""
    model = model or model_for(worker=True)
    instruction = ("\n\nReply with a single JSON object and nothing else, matching this JSON Schema:\n"
                   + json.dumps(schema))
    messages = [{"role": "system", "content": system + instruction}, {"role": "user", "content": prompt}]
    formats = [{"type": "json_schema", "json_schema": {"name": "result", "schema": schema, "strict": True}},
               {"type": "json_object"}, None]
    last_err: Exception | None = None
    for fmt in formats:
        try:
            res = chat(component, messages, model=model, max_tokens=max_tokens, response_format=fmt)
        except BadRequestError as e:  # server doesn't support this response_format
            last_err = e
            continue
        for attempt in range(2):
            try:
                data = _extract_json(res.text)
                jsonschema.validate(data, schema)
                return data
            except (json.JSONDecodeError, jsonschema.ValidationError) as e:
                last_err = e
                if attempt == 0:
                    messages = messages + [res.message, {"role": "user", "content": f"That was not valid ({str(e)[:200]}). Reply again with only the JSON object."}]
                    res = chat(component, messages, model=model, max_tokens=max_tokens, response_format=None)
        break
    raise LLMOutputError(f"{component}: the model did not return usable JSON ({last_err})")
