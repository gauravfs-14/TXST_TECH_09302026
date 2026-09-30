"""The OpenAI-compatible layer, exercised against a fake client (no network)."""
from types import SimpleNamespace as NS

import pytest
from openai import BadRequestError

from confiance import llm
from confiance.engines import Turn, build_engine
from confiance.search.sandbox import Sandbox
from confiance.search.providers import DuckDuckGoSearch, OfflineCorpusSearch

SCHEMA = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"], "additionalProperties": False}


def resp(content=None, tool_calls=None):
    msg = NS(content=content, tool_calls=tool_calls, refusal=None)
    return NS(choices=[NS(message=msg, finish_reason="stop")], usage=NS(prompt_tokens=10, completion_tokens=5, prompt_tokens_details=None))


def bad_request(msg):
    return BadRequestError(msg, response=NS(status_code=400, headers={}, request=NS()), body=None)


@pytest.fixture
def fake(monkeypatch):
    calls = []
    script = []

    def create(**kw):
        calls.append(kw)
        r = script.pop(0)
        if isinstance(r, Exception):
            raise r
        if not kw.get("stream"):
            return r
        msg = r.choices[0].message
        tcs = [NS(index=i, id=tc.id, function=NS(name=tc.function.name, arguments=tc.function.arguments)) for i, tc in enumerate(msg.tool_calls or [])]
        # deliver the answer in pieces, like a real stream
        text = msg.content or ""
        chunks = [NS(usage=None, choices=[NS(delta=NS(content=text[:3], tool_calls=None, refusal=None), finish_reason=None)]),
                  NS(usage=None, choices=[NS(delta=NS(content=text[3:], tool_calls=tcs or None, refusal=None), finish_reason="stop")]),
                  NS(usage=r.usage, choices=[])]
        return iter(chunks)

    monkeypatch.setattr(llm, "client", lambda: NS(chat=NS(completions=NS(create=create))))
    monkeypatch.setenv("CONFIANCE_LLM_MODEL", "m")
    from confiance import config
    config.get_settings.cache_clear()
    return NS(calls=calls, script=script)


def test_json_falls_back_when_server_rejects_schema_format(fake):
    fake.script += [bad_request("response_format json_schema not supported"), resp('```json\n{"n": 3}\n```')]
    # second format (json_object) returns fenced json -> tolerant parse
    fake.script.insert(1, bad_request("response_format json_object not supported"))
    fake.script[:] = [bad_request("no json_schema"), bad_request("no json_object"), resp('Sure! ```json\n{"n": 3}\n```')]
    assert llm.json_call("t", system="s", prompt="p", schema=SCHEMA) == {"n": 3}
    assert [c.get("response_format", {}).get("type") for c in fake.calls] == ["json_schema", "json_object", None]


def test_json_repairs_once_then_fails(fake):
    fake.script[:] = [resp('{"n": "three"}'), resp('{"n": 4}')]
    assert llm.json_call("t", system="s", prompt="p", schema=SCHEMA) == {"n": 4}
    fake.script[:] = [resp("nonsense"), resp("still nonsense")]
    with pytest.raises(llm.LLMOutputError):
        llm.json_call("t", system="s", prompt="p", schema=SCHEMA)


def test_chat_parses_tool_calls_strips_thinking_and_retries_token_param(fake):
    tc = NS(id="", function=NS(name="lookup", arguments='{"word": "blue"}'))
    fake.script[:] = [bad_request("Unsupported parameter: use max_completion_tokens"), resp("<think>hmm</think>ok", [tc])]
    r = llm.chat("t", [{"role": "user", "content": "hi"}], tools=[{"name": "lookup", "description": "d", "parameters": {"type": "object"}}])
    assert r.text == "ok" and r.tool_calls[0].name == "lookup" and r.tool_calls[0].args == {"word": "blue"} and r.tool_calls[0].id
    assert "max_completion_tokens" in fake.calls[1] and "max_tokens" not in fake.calls[1] and fake.calls[1]["stream"]
    assert r.message["tool_calls"][0]["function"]["arguments"] == '{"word": "blue"}'


def test_engine_without_native_search_measures_the_live_web(monkeypatch):
    monkeypatch.setenv("CONFIANCE_LLM_MODEL", "m")
    monkeypatch.setenv("CONFIANCE_LLM_BASE_URL", "http://localhost:11434/v1")
    from confiance import config
    config.get_settings.cache_clear()
    eng = build_engine("openai")
    assert eng.supports_native is False
    assert eng.native([Turn("user", "hi")]).error  # honest: no built-in search here
    monkeypatch.setenv("CONFIANCE_LLM_BASE_URL", "https://api.openai.com/v1")
    config.get_settings.cache_clear()
    assert build_engine("openai").supports_native is True

    monkeypatch.setenv("CONFIANCE_LLM_BASE_URL", "http://localhost:11434/v1")
    config.get_settings.cache_clear()
    served = {}

    class Prov(OfflineCorpusSearch):
        def fetch(self, url):
            served["url"] = url
            return "Live", "the live page"

    monkeypatch.setattr("confiance.search.providers.build_provider", lambda *a, **k: Prov([("https://x.test/", "X", "x page")]))
    scripted = [llm.LLMResult(tool_calls=[llm.ToolCall("1", "fetch_page", {"url": "https://x.test/"})], message={"role": "assistant", "content": None}),
                llm.LLMResult(text="answer https://x.test/", message={"role": "assistant", "content": "answer"})]
    monkeypatch.setattr(llm, "chat", lambda *a, **k: scripted.pop(0))
    ans = eng.run_real([Turn("user", "q")])
    assert served["url"] == "https://x.test/" and ans.citations == ["https://x.test/"] and not ans.injected  # live web, nothing swapped in


def test_duckduckgo_provider_maps_results(monkeypatch):
    import ddgs

    class FakeDDGS:
        def __init__(self, timeout=None):
            pass

        def text(self, q, max_results=5):
            return [{"href": "https://a.test/", "title": "A", "body": "about a"}, {"title": "no url"}]

    monkeypatch.setattr(ddgs, "DDGS", FakeDDGS)
    hits = DuckDuckGoSearch().search("q", 5)
    assert [(h.url, h.title, h.snippet) for h in hits] == [("https://a.test/", "A", "about a")]


def test_stream_options_rejected_by_server_is_dropped(fake):
    fake.script[:] = [bad_request("Unknown parameter: stream_options"), resp("hello there")]
    r = llm.chat("t", [{"role": "user", "content": "hi"}])
    assert r.text == "hello there"
    assert "stream_options" in fake.calls[0] and "stream_options" not in fake.calls[1]


def test_missing_usage_is_estimated_not_lost(fake):
    from sqlalchemy import select
    from confiance.db import session_scope
    from confiance.models import UsageRecord
    r = resp("x" * 400)
    r.usage = None
    fake.script[:] = [r]
    llm.chat("estimate-me", [{"role": "user", "content": "y" * 800}])
    with session_scope() as s:
        row = s.scalars(select(UsageRecord).where(UsageRecord.component == "estimate-me")).one()
    assert row.input_tokens > 100 and row.output_tokens > 50


def test_empty_reply_is_stored_as_empty_string_not_null(fake):
    fake.script[:] = [resp("")]
    r = llm.chat("t", [{"role": "user", "content": "hi"}])
    assert r.message == {"role": "assistant", "content": ""} and r.tool_calls == []
