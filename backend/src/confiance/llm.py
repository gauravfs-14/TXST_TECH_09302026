"""The AI layer for CONFIANCE's internal agents (KB builder, personas, judge, optimizer).

Talks to any OpenAI-compatible Chat Completions endpoint: OpenAI, Google Gemini, Ollama, OpenRouter, Groq,
LM Studio, vLLM... Chat Completions (not the newer Responses API) is used because every compatible server
implements it. Things servers implement unevenly degrade gracefully:

  * JSON output: strict json_schema -> json_object -> plain text with tolerant parsing, validated against the
    schema with one repair retry.
  * optional parameters (stream_options, reasoning_effort, max_tokens vs max_completion_tokens): dropped or
    renamed when a server rejects them, and remembered for the rest of the process.
  * tool_choice is never used (Ollama ignores it); tools are simply omitted when we want none.

Thinking is left ON at the model's own default depth. We never turn it down to save quota. (An optional
`llm_reasoning_effort` setting exists for people who want to choose.) Thinking tokens count against the output
limit, so limits are generous, and provider fields that carry reasoning across tool-call turns are echoed back.

Free tiers are the reason for the pacing code. Their limits are low and often unpublished, so every call goes
through (1) a concurrency cap, (2) an optional requests-per-minute limiter, and (3) retry with backoff that
respects Retry-After and tells a per-minute limit (wait) from a daily quota (stop, explain, try tomorrow).
"""

import json
import random
import re
import threading
import time
import uuid
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import httpx
import jsonschema
from openai import APIConnectionError, APIStatusError, APITimeoutError, BadRequestError, OpenAI, RateLimitError

from . import activity, usage
from .config import get_settings


class LLMRefusal(RuntimeError):
    pass


class LLMOutputError(RuntimeError):
    pass


class LLMQuotaError(RuntimeError):
    """The provider's daily (or monthly) quota is used up. Retrying will not help until it resets."""


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict
    extra: dict | None = None  # provider fields that must be echoed back (e.g. Gemini thought signatures)


@dataclass
class LLMResult:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    message: dict = field(default_factory=dict)  # assistant message, ready to append to history
    finish_reason: str = ""


@lru_cache
def client() -> OpenAI:
    s = get_settings()
    # Our own retry loop handles 429/5xx/connection errors, so the SDK's is switched off (no double retrying).
    # The read timeout is *silence between streamed chunks*, not the whole answer.
    return OpenAI(base_url=s.llm_base_url, api_key=s.llm_api_key or "not-needed", max_retries=0,
                  timeout=httpx.Timeout(connect=15.0, read=s.llm_timeout_s, write=60.0, pool=30.0))


def model_for(role: str = "optimizer") -> str:
    """Roles: optimizer (few, hard calls) uses the main model; worker and engine (many small calls) use the
    fast model when one is set, otherwise the main model."""
    s = get_settings()
    m = s.llm_model if role == "optimizer" else (s.llm_worker_model or s.llm_model)
    if not m:
        raise RuntimeError("No AI model has been chosen yet. Please finish connecting your AI model.")
    return m


_THINK = re.compile(r"<think>.*?</think>", re.S)


def clean(text: str | None) -> str:
    """Removes inline <think> blocks from the *visible* answer (the model still thinks; we just don't parse it)."""
    return _THINK.sub("", text or "").strip()


# ---- pacing (adaptive) ---------------------------------------------------------------------------------------------
#
# Speed comes from running several requests at once, but the safe number is unknown (free-tier limits are often
# unpublished and per-project). So we do what network protocols do: start gently, speed up a step at a time while
# things succeed, and cut back sharply the moment the service says "too many requests" (AIMD). A configured
# concurrency / requests-per-minute is a *ceiling*, never a target. A local model on one GPU gains nothing from
# more parallelism, so its ceiling is low.

_sleep = time.sleep  # tests replace these two
_now = time.monotonic
_lock = threading.Condition()
_stamps: deque[float] = deque()  # start times of recent requests
_active = 0
_eff_conc = 0   # requests allowed at once right now (0 = not initialised)
_eff_rpm = 0    # requests per minute allowed right now (0 = no limit of our own, until a 429 teaches us one)
_streak = 0     # successes since the last limit
_UNSUPPORTED: set[str] = set()  # optional parameters this server rejected

_UP_CONC_EVERY = 8    # successes before allowing one more request at once
_UP_RPM_EVERY = 20    # successes before allowing a little more per minute
_MIN_LEARNED_RPM = 4


def _ceilings() -> tuple[int, int]:
    s = get_settings()
    return max(1, s.llm_max_concurrency), max(0, s.llm_rpm)


def _init_locked() -> None:
    global _eff_conc, _eff_rpm
    cmax, rmax = _ceilings()
    if _eff_conc == 0:
        _eff_conc = max(1, cmax // 2)              # start gently
        _eff_rpm = min(rmax, 8) if rmax else 0
    _eff_conc = min(_eff_conc, cmax)
    if rmax:
        _eff_rpm = min(_eff_rpm or rmax, rmax)


def reset_pacing() -> None:
    global _active, _eff_conc, _eff_rpm, _streak
    with _lock:
        _stamps.clear()
        _active, _eff_conc, _eff_rpm, _streak = 0, 0, 0, 0
        _lock.notify_all()
    _UNSUPPORTED.clear()


def pace() -> dict:
    """The speed we are running at right now, for the live view."""
    with _lock:
        _init_locked()
        cmax, rmax = _ceilings()
        return {"concurrency": _eff_conc, "max_concurrency": cmax, "rpm": _eff_rpm, "rpm_max": rmax, "in_flight": _active}


@contextmanager
def _gate():
    global _active
    with _lock:
        _init_locked()
        while _active >= _eff_conc:
            _lock.wait(timeout=1.0)  # re-checks, because the allowance can change while we wait
            _init_locked()
        _active += 1
    try:
        yield
    finally:
        with _lock:
            _active -= 1
            _lock.notify_all()


def _wait_for_rpm() -> None:
    while True:
        with _lock:
            _init_locked()
            now = _now()
            while _stamps and now - _stamps[0] >= 60:
                _stamps.popleft()
            if _eff_rpm <= 0 or len(_stamps) < _eff_rpm:
                _stamps.append(now)
                return
            wait = 60 - (now - _stamps[0]) + 0.05
        if wait > 1:
            activity.waiting(wait, "Pacing ourselves to stay under the service's limit.")
        _sleep(wait)


def _on_success() -> None:
    global _streak, _eff_conc, _eff_rpm
    said = ""
    with _lock:
        _streak += 1
        cmax, rmax = _ceilings()
        if _streak % _UP_CONC_EVERY == 0 and _eff_conc < cmax:
            _eff_conc += 1
            said = f"Going a little faster: {_eff_conc} requests at once."
            _lock.notify_all()
        if _eff_rpm and _streak % _UP_RPM_EVERY == 0 and (rmax == 0 or _eff_rpm < rmax):
            _eff_rpm += 1
    if said:
        activity.emit(said, "info")


def _on_limit() -> None:
    """The service said 'too many requests': halve what runs at once and learn a per-minute ceiling."""
    global _streak, _eff_conc, _eff_rpm
    with _lock:
        _init_locked()
        _streak = 0
        _eff_conc = max(1, _eff_conc // 2)
        recent = len(_stamps)  # requests started in the last minute
        base = max(recent, _eff_rpm)
        _eff_rpm = max(_MIN_LEARNED_RPM, int(base * 0.7))
        conc, rpm = _eff_conc, _eff_rpm
    activity.emit(f"Slowing down: {conc} at once and about {rpm} a minute, because the service said it was too much.", "wait")


def calls_today() -> int:
    from datetime import timedelta

    from sqlalchemy import func, select

    from .db import session_scope, utcnow
    from .models import UsageRecord

    with session_scope() as s:
        return s.scalar(select(func.count()).select_from(UsageRecord).where(UsageRecord.ts >= utcnow() - timedelta(hours=24))) or 0


def _classify(e: Exception, attempt: int) -> tuple[str, float]:
    """-> ('quota' | 'retry' | 'fatal', seconds_to_wait)"""
    text = str(e).lower()
    if isinstance(e, RateLimitError) or (isinstance(e, APIStatusError) and e.status_code == 429):
        daily = any(w in text for w in ("quota_exceeded", "per day", "perday", "per_day", "daily", "exceeded your current quota"))
        if daily and "per minute" not in text and "per-minute" not in text:
            return "quota", 0
        retry_after = None
        try:
            retry_after = float(e.response.headers.get("retry-after"))
        except Exception:
            pass
        return "retry", retry_after if retry_after is not None else min(60.0, 8.0 * (attempt + 1)) * random.uniform(0.9, 1.3)
    if isinstance(e, (APIConnectionError, APITimeoutError)) or (isinstance(e, APIStatusError) and (e.status_code >= 500 or e.status_code == 408)):
        return "retry", min(30.0, 2.0 * 2 ** attempt) * random.uniform(0.8, 1.2)
    return "fatal", 0


def _with_pacing(fn):
    """Run one whole request (open + consume the stream) under the adaptive concurrency and rate limits,
    retrying transient failures."""
    attempts = 6
    for attempt in range(attempts):
        wait, is_limit = 0.0, False
        with _gate():
            _wait_for_rpm()
            try:
                result = fn()
                _on_success()
                return result
            except (BadRequestError, LLMRefusal):
                raise
            except Exception as e:
                kind, wait = _classify(e, attempt)
                is_limit = isinstance(e, RateLimitError) or (isinstance(e, APIStatusError) and e.status_code == 429)
                if kind == "fatal":
                    raise
                if kind == "quota":
                    raise LLMQuotaError("The free daily limit for this AI service has been reached. It resets daily, "
                                        "so try again later or switch to another model.") from e
                if attempt == attempts - 1:
                    raise
                if is_limit:
                    _on_limit()
        activity.waiting(wait, "The AI service asked us to slow down." if is_limit else "The connection to the AI service hiccuped; retrying.")
        _sleep(wait)  # outside the gate so other threads can use the slot meanwhile


# ---- requests ------------------------------------------------------------------------------------------------------

def _open_stream(kwargs: dict):
    kw = {**kwargs, "stream": True}
    if "stream_options" not in _UNSUPPORTED:
        kw["stream_options"] = {"include_usage": True}
    for _ in range(5):
        try:
            return client().chat.completions.create(**kw)
        except BadRequestError as e:
            msg = str(e)
            changed = False
            for param in ("stream_options", "reasoning_effort"):
                if param in msg and param in kw:
                    _UNSUPPORTED.add(param)
                    kw = {k: v for k, v in kw.items() if k != param}
                    changed = True
            if "max_completion_tokens" in msg and "max_tokens" in kw:
                kw = {k: v for k, v in kw.items() if k != "max_tokens"} | {"max_completion_tokens": kwargs["max_tokens"]}
                changed = True
            if not changed:
                raise
    return client().chat.completions.create(**kw)


def _record(component: str, model: str, u, prompt_chars: int, out_chars: int) -> None:
    if u is not None:
        cached = getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", 0) or 0
        usage.record(component, "openai-compatible", model, max((u.prompt_tokens or 0) - cached, 0), u.completion_tokens or 0, cached)
    else:  # server didn't report usage: rough estimate (about 4 characters per token)
        usage.record(component, "openai-compatible", model, prompt_chars // 4, out_chars // 4)


def _extra_of(tc) -> dict | None:
    extra = getattr(tc, "extra_content", None)
    if extra is None:
        extra = (getattr(tc, "model_extra", None) or {}).get("extra_content")
    return extra if isinstance(extra, dict) else None


def _consume(kwargs: dict, component: str, model: str, messages: list[dict]) -> LLMResult:
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
                key = tc.index or 0
                # Some servers number every parallel call 0; a new non-empty id means a new call.
                if tc.id and key in partial and partial[key]["id"] and partial[key]["id"] != tc.id:
                    key = max(partial) + 1
                e = partial.setdefault(key, {"id": "", "name": "", "args": "", "extra": None})
                if tc.id:
                    e["id"] = tc.id
                if tc.function:
                    e["name"] += tc.function.name or ""
                    e["args"] += tc.function.arguments or ""
                e["extra"] = _extra_of(tc) or e["extra"]
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
        calls.append(ToolCall(e["id"] or f"call_{uuid.uuid4().hex[:12]}", e["name"], args if isinstance(args, dict) else {}, e["extra"]))
    text = clean("".join(parts))
    history: dict[str, Any] = {"role": "assistant", "content": text}  # "" not null: some servers reject null content
    if calls:
        history["tool_calls"] = []
        for c in calls:
            entry: dict[str, Any] = {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.args)}}
            if c.extra:
                entry["extra_content"] = c.extra
            history["tool_calls"].append(entry)
    return LLMResult(text=text, tool_calls=calls, message=history, finish_reason=finish)


def chat(component: str, messages: list[dict], *, tools: list[dict] | None = None, model: str | None = None,
         role: str = "optimizer", max_tokens: int = 16000, response_format: dict | None = None) -> LLMResult:
    """One model call. Thinking stays at the provider's default unless `llm_reasoning_effort` is set."""
    s = get_settings()
    model = model or model_for(role)
    kwargs: dict[str, Any] = {"model": model, "messages": messages, "max_tokens": max_tokens}
    if tools:
        kwargs["tools"] = [{"type": "function", "function": t} for t in tools]
    if response_format:
        kwargs["response_format"] = response_format
    if s.llm_reasoning_effort and "reasoning_effort" not in _UNSUPPORTED:
        kwargs["reasoning_effort"] = s.llm_reasoning_effort
    def run(m: str) -> LLMResult:
        kw = {**kwargs, "model": m}
        rid, t0 = activity.llm_started(), time.monotonic()
        try:
            result = _with_pacing(lambda: _consume(kw, component, m, messages))
        finally:
            activity.llm_finished(rid)
        activity.emit(f"AI call finished: {component} on {m} ({time.monotonic() - t0:.1f}s)", "llm",
                      {"component": component, "model": m, "seconds": round(time.monotonic() - t0, 1),
                       "tool_calls": [c.name for c in getattr(result, "tool_calls", [])]})
        return result

    try:
        return run(model)
    except LLMQuotaError:
        # Quotas are per model, and the main model's free allowance is usually the smaller one. If a separate fast
        # model is set, carry on with it rather than failing the whole round.
        fallback = s.llm_worker_model
        if role == "optimizer" and fallback and fallback != model:
            activity.emit(f"The main model's free daily limit is used up, so carrying on with the fast model ({fallback}).", "wait")
            return run(fallback)
        raise


def cached_system(stable: str, extra: str = "") -> str:
    """Stable text first so servers with automatic prefix caching (OpenAI, Gemini, vLLM) can reuse it."""
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
              max_tokens: int = 12000) -> dict:
    """One request that must return JSON matching `schema`, on the fast model (thinking left on)."""
    model = model or model_for("worker")
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
                    res = chat(component, messages, model=model, max_tokens=max_tokens)
        break
    raise LLMOutputError(f"{component}: the model did not return usable JSON ({last_err})")
