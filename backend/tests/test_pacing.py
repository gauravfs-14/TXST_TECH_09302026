"""Rate-limit handling: what the free tiers need."""
from types import SimpleNamespace as NS

import pytest
from openai import APIConnectionError, RateLimitError

from confiance import config, llm


def rate_limit(msg, retry_after=None):
    headers = {"retry-after": str(retry_after)} if retry_after is not None else {}
    return RateLimitError(msg, response=NS(status_code=429, headers=headers, request=NS()), body=None)


@pytest.fixture
def sleeps(monkeypatch):
    slept = []
    monkeypatch.setattr(llm, "_sleep", slept.append)
    monkeypatch.setenv("CONFIANCE_LLM_MODEL", "m")
    config.get_settings.cache_clear()
    llm.reset_pacing()
    return slept


def test_per_minute_limit_waits_and_retries_honoring_retry_after(sleeps):
    n = {"i": 0}

    def fn():
        n["i"] += 1
        if n["i"] < 3:
            raise rate_limit("Rate limit reached: requests per minute", retry_after=7)
        return "ok"

    assert llm._with_pacing(fn) == "ok" and sleeps == [7.0, 7.0]


def test_daily_quota_stops_immediately_with_a_plain_message(sleeps):
    def fn():
        raise rate_limit("429 RESOURCE_EXHAUSTED: quota_exceeded, you exceeded your daily quota")

    with pytest.raises(llm.LLMQuotaError, match="daily limit"):
        llm._with_pacing(fn)
    assert sleeps == []  # no pointless retries


def test_transient_connection_errors_retry_then_give_up(sleeps):
    def fn():
        raise APIConnectionError(request=NS())

    with pytest.raises(APIConnectionError):
        llm._with_pacing(fn)
    assert len(sleeps) == 5  # 6 attempts


def test_bad_requests_are_not_retried(sleeps):
    from openai import BadRequestError
    calls = []

    def fn():
        calls.append(1)
        raise BadRequestError("nope", response=NS(status_code=400, headers={}, request=NS()), body=None)

    with pytest.raises(BadRequestError):
        llm._with_pacing(fn)
    assert len(calls) == 1


def test_rpm_limiter_spaces_calls(sleeps, monkeypatch):
    monkeypatch.setenv("CONFIANCE_LLM_RPM", "2")
    config.get_settings.cache_clear()
    llm.reset_pacing()
    t = {"now": 1000.0}
    monkeypatch.setattr(llm, "_now", lambda: t["now"])
    monkeypatch.setattr(llm, "_sleep", lambda w: t.__setitem__("now", t["now"] + w))
    for _ in range(3):
        llm._wait_for_rpm()
    assert t["now"] - 1000.0 >= 59.9  # the third call had to wait out the minute


def test_model_roles_and_defaults(monkeypatch):
    monkeypatch.setenv("CONFIANCE_LLM_MODEL", "big")
    config.get_settings.cache_clear()
    assert llm.model_for("optimizer") == "big" and llm.model_for("worker") == "big"
    monkeypatch.setenv("CONFIANCE_LLM_WORKER_MODEL", "small")
    config.get_settings.cache_clear()
    assert llm.model_for("optimizer") == "big" and llm.model_for("worker") == "small" and llm.model_for("engine") == "small"
    from confiance.engines import build_engine
    assert build_engine("openai").model == "small"  # the high-volume simulated assistant uses the fast model


def test_thinking_is_never_turned_down_by_default(monkeypatch):
    captured = {}
    monkeypatch.setattr(llm, "_with_pacing", lambda f: f())
    monkeypatch.setattr(llm, "_consume", lambda kw, *a: captured.update(kw) or NS())
    monkeypatch.setenv("CONFIANCE_LLM_MODEL", "m")
    config.get_settings.cache_clear()
    llm.reset_pacing()
    llm.chat("t", [{"role": "user", "content": "x"}])
    assert "reasoning_effort" not in captured and captured["max_tokens"] >= 12000  # room for thinking + the answer
    monkeypatch.setenv("CONFIANCE_LLM_REASONING_EFFORT", "high")
    config.get_settings.cache_clear()
    captured.clear()
    llm.chat("t", [{"role": "user", "content": "x"}])
    assert captured["reasoning_effort"] == "high"  # only when the user asks


def test_thought_signature_style_fields_are_echoed_back(monkeypatch):
    tc = NS(id="c1", extra_content={"google": {"thought_signature": "abc"}}, function=NS(name="f", arguments="{}"))
    monkeypatch.setenv("CONFIANCE_LLM_MODEL", "m")
    config.get_settings.cache_clear()
    llm.reset_pacing()

    def create(**kw):
        msg = NS(content="", tool_calls=[tc], refusal=None)
        r = NS(choices=[NS(message=msg, finish_reason="stop")], usage=None)
        chunks = [NS(usage=None, choices=[NS(delta=NS(content="", tool_calls=[NS(index=0, id="c1", extra_content=tc.extra_content, function=NS(name="f", arguments="{}"))], refusal=None), finish_reason="stop")])]
        return iter(chunks)

    monkeypatch.setattr(llm, "client", lambda: NS(chat=NS(completions=NS(create=create))))
    r = llm.chat("t", [{"role": "user", "content": "x"}])
    assert r.message["tool_calls"][0]["extra_content"] == {"google": {"thought_signature": "abc"}}


def test_parallel_calls_numbered_zero_stay_separate(monkeypatch):
    monkeypatch.setenv("CONFIANCE_LLM_MODEL", "m")
    config.get_settings.cache_clear()
    llm.reset_pacing()

    def create(**kw):
        def call(i, name):
            return NS(usage=None, choices=[NS(delta=NS(content=None, refusal=None, tool_calls=[NS(index=0, id=f"id{i}", function=NS(name=name, arguments='{"q": 1}'))]), finish_reason=None)])
        return iter([call(1, "a"), call(2, "b")])

    monkeypatch.setattr(llm, "client", lambda: NS(chat=NS(completions=NS(create=create))))
    r = llm.chat("t", [{"role": "user", "content": "x"}])
    assert [(c.id, c.name, c.args) for c in r.tool_calls] == [("id1", "a", {"q": 1}), ("id2", "b", {"q": 1})]


# ---- adaptive concurrency / rate (AIMD) ---------------------------------------------------------------------------

def _fresh(monkeypatch, conc=4, rpm=0):
    monkeypatch.setenv("CONFIANCE_LLM_MODEL", "m")
    monkeypatch.setenv("CONFIANCE_LLM_MAX_CONCURRENCY", str(conc))
    monkeypatch.setenv("CONFIANCE_LLM_RPM", str(rpm))
    config.get_settings.cache_clear()
    llm.reset_pacing()
    clock = {"now": 1000.0}
    monkeypatch.setattr(llm, "_now", lambda: clock["now"])
    monkeypatch.setattr(llm, "_sleep", lambda w: clock.__setitem__("now", clock["now"] + w))  # sleeping advances the fake clock


def test_starts_gently_then_speeds_up_while_things_succeed(monkeypatch):
    _fresh(monkeypatch, conc=4)
    assert llm.pace()["concurrency"] == 2  # half the ceiling to begin with
    for _ in range(8):
        llm._with_pacing(lambda: "ok")
    assert llm.pace()["concurrency"] == 3
    for _ in range(8):
        llm._with_pacing(lambda: "ok")
    assert llm.pace()["concurrency"] == 4
    for _ in range(40):
        llm._with_pacing(lambda: "ok")
    assert llm.pace()["concurrency"] == 4  # never above the ceiling


def test_a_429_halves_concurrency_and_learns_a_per_minute_limit(monkeypatch):
    _fresh(monkeypatch, conc=8, rpm=0)  # no rate configured at all: the service has to teach us
    for _ in range(24):
        llm._with_pacing(lambda: "ok")
    assert llm.pace()["concurrency"] == 7 and llm.pace()["rpm"] == 0
    n = {"i": 0}

    def flaky():
        n["i"] += 1
        if n["i"] == 1:
            raise rate_limit("Rate limit reached: requests per minute", retry_after=1)
        return "ok"

    llm._with_pacing(flaky)
    p = llm.pace()
    assert p["concurrency"] == 3 and p["rpm"] >= 4  # halved, and a limit of our own now exists


def test_configured_rate_is_a_ceiling_reached_gradually(monkeypatch):
    _fresh(monkeypatch, conc=4, rpm=15)
    assert llm.pace()["rpm"] == 8  # starts below the ceiling
    monkeypatch.setattr(llm, "_wait_for_rpm", lambda: None)
    for _ in range(20 * 8):
        llm._with_pacing(lambda: "ok")
    assert llm.pace()["rpm"] == 15  # grew to the ceiling and stopped


def test_never_more_requests_at_once_than_currently_allowed(monkeypatch):
    import threading
    import time as _t
    _fresh(monkeypatch, conc=4)  # allowed right now: 2
    lock, running, peak = threading.Lock(), [0], [0]

    def work():
        with lock:
            running[0] += 1
            peak[0] = max(peak[0], running[0])
        _t.sleep(0.05)
        with lock:
            running[0] -= 1
        return "ok"

    threads = [threading.Thread(target=lambda: llm._with_pacing(work)) for _ in range(6)]  # 6 < 8, so no speed-up mid-test
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert peak[0] <= 2


def test_daily_quota_does_not_shrink_the_pace(monkeypatch):
    _fresh(monkeypatch, conc=4)
    before = llm.pace()

    def fn():
        raise rate_limit("quota_exceeded: daily quota")

    with pytest.raises(llm.LLMQuotaError):
        llm._with_pacing(fn)
    assert llm.pace()["concurrency"] == before["concurrency"]


def test_main_model_daily_quota_falls_back_to_the_fast_model(monkeypatch):
    monkeypatch.setenv("CONFIANCE_LLM_MODEL", "big")
    monkeypatch.setenv("CONFIANCE_LLM_WORKER_MODEL", "small")
    config.get_settings.cache_clear()
    llm.reset_pacing()
    used = []

    def consume(kw, *a):
        used.append(kw["model"])
        if kw["model"] == "big":
            raise rate_limit("quota_exceeded: daily quota")
        return llm.LLMResult(text="ok", message={"role": "assistant", "content": "ok"})

    monkeypatch.setattr(llm, "_consume", consume)
    monkeypatch.setattr(llm, "_sleep", lambda w: None)
    assert llm.chat("optimizer", [{"role": "user", "content": "x"}]).text == "ok" and used == ["big", "small"]
    # no fast model to fall back to: the plain quota error surfaces
    monkeypatch.setenv("CONFIANCE_LLM_WORKER_MODEL", "")
    config.get_settings.cache_clear()
    with pytest.raises(llm.LLMQuotaError):
        llm.chat("optimizer", [{"role": "user", "content": "x"}])
    # worker-role calls never fall back (they are already on the cheap model)
    monkeypatch.setenv("CONFIANCE_LLM_WORKER_MODEL", "small")
    config.get_settings.cache_clear()
    used.clear()
    monkeypatch.setattr(llm, "_consume", lambda kw, *a: (_ for _ in ()).throw(rate_limit("quota_exceeded: daily quota")))
    with pytest.raises(llm.LLMQuotaError):
        llm.chat("kb", [{"role": "user", "content": "x"}], role="worker")
