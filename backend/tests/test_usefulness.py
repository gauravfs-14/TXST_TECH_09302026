"""Findability vs. usefulness-when-found, and the fairness of the comparison between the two rounds."""
import json
from types import SimpleNamespace as NS

import pytest

from confiance import llm
from confiance.engines import Turn, build_engine
from confiance.engines.base import EngineAnswer
from confiance.search.base import SearchHit
from confiance.search.providers import OfflineCorpusSearch
from confiance.search.sandbox import Sandbox
from confiance.sim import findability
from confiance.sim.metrics import Target, score, visibility_score

OLD = "Home. We teach things."
NEW = "Free Linux course for beginners. Learn Linux commands step by step, with exercises, in simple English."
OTHER = [("https://big.test/a", "Big A", "generic programming resources"), ("https://big.test/b", "Big B", "more generic resources"),
         ("https://huge.test/c", "Huge C", "learn programming free")]


def sandbox(page_text, expose=True, modified=False, provider=None):
    key = "small.test/"
    return Sandbox(provider=provider or OfflineCorpusSearch(OTHER), client_domain="small.test",
                   pages={key: ("Small", page_text)}, modified={key} if modified else set(),
                   urls={key: "https://small.test/"}, expose=expose)


def urls_of(sess, q):
    return [r["url"] for r in sess.web_search(q)]


def test_page_is_guaranteed_present_and_in_the_same_place_in_both_rounds():
    q = "free linux course for beginners"
    base = sandbox("Free Linux course for beginners. We teach things.").session()
    cand = sandbox(NEW, modified=True).session()
    b, c = urls_of(base, q), urls_of(cand, q)
    assert "https://small.test/" in b and "https://small.test/" in c
    assert b.index("https://small.test/") == c.index("https://small.test/") == min(1, len(b) - 1)  # same slot, both arms
    assert base.exposed and cand.exposed and cand.injected and not base.injected


def test_snippet_comes_from_the_version_being_served():
    q = "linux commands step by step exercises"
    snip = lambda text, mod: sandbox(text, modified=mod).session().web_search(q)
    old = next(r for r in snip("Free Linux course for beginners. We teach things.", False) if "small.test" in r["url"])["snippet"]
    new = next(r for r in snip(NEW, True) if "small.test" in r["url"])["snippet"]
    assert "step by step" in new and "step by step" not in old


def test_irrelevant_page_is_not_forced_in():
    sess = sandbox("Completely unrelated pottery studio.").session()
    assert "https://small.test/" not in urls_of(sess, "kubernetes networking internals") and not sess.exposed


def test_without_expose_nothing_is_faked():
    sess = sandbox(NEW, expose=False).session()
    assert "https://small.test/" not in urls_of(sess, "free linux course for beginners") and not sess.exposed


def test_a_failing_search_does_not_fail_the_conversation(monkeypatch):
    class Broken:
        def search(self, q, n=5):
            raise TimeoutError("timed out")

        def fetch(self, u):
            raise TimeoutError()

    monkeypatch.setattr("confiance.search.sandbox.time.sleep", lambda s: None)
    sess = sandbox(NEW, provider=Broken()).session()
    out = json.loads(sess.execute("web_search", {"query": "anything"}))
    assert out["results"] == [] and "problem" in out["note"]
    # ...and "no results" is just an empty result set
    class Empty:
        def search(self, q, n=5):
            raise Exception("DDGSException: No results found.")
    assert sandbox(NEW, provider=Empty(), expose=False).session().web_search("x") == []


def test_using_the_page_is_measured_and_moves_the_score():
    t = Target("small.test", ["Small"], [])
    page = "Free Linux course for beginners. Learn Linux commands step by step, with exercises, in simple English."
    quoted = EngineAnswer(text="Small offers a free Linux course for beginners. Learn Linux commands step by step, with exercises, in simple English. https://small.test/",
                          citations=["https://small.test/"], retrieved_urls=["https://small.test/"], queries=["q"], exposed=True)
    generic = EngineAnswer(text="Try freecodecamp for programming basics and the official documentation.", citations=["https://big.test/a"], queries=["q"], exposed=True)
    mq, mg = score(quoted, t, page_texts=[page]), score(generic, t, page_texts=[page])
    assert mq["used_page"] and not mg["used_page"] and mq["searched"]
    assert visibility_score(mq) > visibility_score(mg) + 0.4
    # answers stored before this metric existed still score the old way
    assert visibility_score({"answered": True, "mentioned": True, "cited": True, "retrieved": True}) == 1.0


def test_findability_reports_rank_domains_and_honest_unknowns():
    class P:
        def search(self, q, n=10):
            if q == "boom":
                raise TimeoutError()
            hits = {"found": [SearchHit("https://x.test/", "", ""), SearchHit("https://small.test/p", "", "")],
                    "Small": [SearchHit("https://small.test/", "", "")]}
            return hits.get(q, [SearchHit("https://big.test/", "", ""), SearchHit("https://huge.test/", "", "")])

    items = findability.check(P(), "small.test", "Small", [("q1", "found"), ("q2", "generic"), ("q3", "boom")])
    by = {i["id"]: i for i in items}
    assert by["q1"]["rank"] == 2 and by["q1"]["status"] == "found" and by["q1"]["top_domains"] == ["x.test"]
    assert by["q2"]["status"] == "not_found" and by["q2"]["top_domains"] == ["big.test", "huge.test"]
    assert by["q3"]["status"] == "unknown"  # a failed search is not evidence of "not found"
    assert by["brand"]["rank"] == 1
    assert findability.summarize(items) == {"questions_checked": 2, "questions_found": 1, "brand_found": True}


def test_assistant_is_asked_to_search_when_it_tries_to_answer_from_memory(monkeypatch):
    monkeypatch.setenv("CONFIANCE_LLM_MODEL", "m")
    from confiance import config
    config.get_settings.cache_clear()
    seen = []
    script = [llm.LLMResult(text="From memory: freecodecamp.", message={"role": "assistant", "content": "From memory"}),
              llm.LLMResult(tool_calls=[llm.ToolCall("1", "web_search", {"query": "linux course"})], message={"role": "assistant", "content": ""}),
              llm.LLMResult(text="Answer https://small.test/", message={"role": "assistant", "content": "Answer"})]

    def chat(component, messages, **kw):
        seen.append(messages[-1]["content"])
        return script.pop(0)

    monkeypatch.setattr(llm, "chat", chat)
    eng = build_engine("openai", "m")
    ans = eng.run("controlled", [Turn("user", "q")], sandbox(NEW).session())
    assert any("web_search tool first" in str(m) for m in seen) and ans.queries == ["linux course"] and ans.exposed


def test_partial_use_of_the_page_scores_between_none_and_full():
    base = {"answered": True, "mentioned": True, "cited": True, "exposed": True, "retrieved": True, "used_page": False}
    none, some, full = ({**base, "page_overlap": o} for o in (0.0, 0.05, 0.20))
    assert visibility_score(none) < visibility_score(some) < visibility_score(full)
    assert round(visibility_score(full) - visibility_score(none), 2) == 0.20  # the whole page-use component
