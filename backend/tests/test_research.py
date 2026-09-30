from confiance.research import run as research
from confiance.search.base import SearchHit

COMP = """<html><head><title>Learn Linux Free</title><script type="application/ld+json">{"@type":"FAQPage"}</script></head>
<body><h1>Learn Linux</h1><h2>What is Linux?</h2><h2>Install guide</h2><p>""" + "text " * 900 + "</p></body></html>"


class Search:
    def search(self, q, n=10):
        if "linux" in q:
            return [SearchHit("https://big.test/linux", "", ""), SearchHit("https://big.test/other", "", ""), SearchHit("https://small.test/linux-intro", "", "")]
        if "databases" in q:
            return [SearchHit("https://huge.test/db", "", ""), SearchHit("https://big.test/db2", "", "")]
        if q == "Small Studio":
            return [SearchHit("https://small.test/", "", "")]
        return [SearchHit("https://huge.test/x", "", "")]


SITE = {"https://small.test/": "Small Studio teaches computing.", "https://small.test/linux-intro": "Learn Linux basics: commands, files and permissions for beginners.",
        "https://small.test/db": "Introduction to databases and SQL queries."}


def test_fit_levels_reflect_rank_and_coverage_and_competitors_are_read():
    qs = [("q1", "learn linux commands for beginners"), ("q2", "free databases sql tutorial"), ("q3", "kubernetes operators deep dive")]
    r = research.run_research(Search(), "small.test", "Small Studio", qs, SITE, fetch_html=lambda u: COMP)
    fit = {e["id"]: e for e in r["queries"]}
    assert fit["q1"]["fit"] == "winning" and fit["q1"]["rank"] == 3 and fit["q1"]["best_page"].endswith("linux-intro")
    assert fit["q2"]["fit"] == "in_reach" and fit["q2"]["status"] == "not_found" and fit["q2"]["coverage"] >= 0.5  # the site covers it, search doesn't show it
    assert fit["q3"]["fit"] == "needs_content" and "dedicated page" in fit["q3"]["fit_reason"]
    assert r["brand"]["status"] == "found" and r["summary"]["needs_content"] == 1 and r["summary"]["found"] >= 1
    assert r["competitors"] and all(c["domain"] != "small.test" for c in r["competitors"])
    assert r["patterns"]["share_with_faq"] == 1.0 and r["patterns"]["median_words"] > 800 and r["patterns"]["common_schema"][0]["type"] == "faqpage"


def test_winning_when_ranked_in_the_top_three():
    fit, why = research.question_fit(1, 0.9)
    assert fit == "winning" and "#1" in why
    assert research.question_fit(None, 0.2)[0] == "needs_content" and research.question_fit(8, 0.1)[0] == "in_reach"


def test_research_survives_failing_searches_and_pages():
    class Broken:
        def search(self, q, n=10):
            raise TimeoutError()

    r = research.run_research(Broken(), "small.test", "Small", [("q1", "anything")], SITE, fetch_html=lambda u: 1 / 0)
    assert r["queries"][0]["status"] == "unknown" and r["competitors"] == []  # unknown is not "not found", and nothing crashed


def test_coverage_measures_how_much_of_the_question_the_page_answers():
    assert research.coverage("learn linux commands", "Learn Linux commands today") == 1.0
    assert research.coverage("learn linux commands", "Pottery glaze recipes") == 0.0
    assert 0 < research.coverage("learn linux commands", "Linux for beginners") < 1
