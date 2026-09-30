"""The improvement plan: a prioritized, concrete list of what to do, in what order, with drafts and how to verify.

Built in layers so it is always useful even if the AI part fails:
  1. audit         technical and structured-data fixes, each with a ready-to-paste draft
  2. research      questions the site can't win yet: what to write, or how to strengthen the closest page
  3. tested edits  the changes that were tested in the sandbox, ready to publish
  4. products      product-page and product-data work
  5. AI-tailored   extra actions specific to this business, grounded in the evidence above
Actions carry a status (todo / doing / done / dismissed) that survives from one round to the next."""

import hashlib
import json
from collections import Counter
from urllib.parse import urlsplit

from sqlalchemy import func, or_, select

from .. import activity, llm
from ..kb import store as kb_store
from ..db import session_scope
from ..models import ChangeProposal, Page, PlanAction, Product, Project, Run
from ..services import scan as scan_mod
from ..textutil import domain_of
from . import drafts

PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
IMPACT_ORDER = {"high": 0, "medium": 1, "low": 2}
EFFORT_ORDER = {"small": 0, "medium": 1, "large": 2}
COMMUNITY = {
    "reddit.com": ("Reddit", "Search Reddit for the questions your customers ask (search: site:reddit.com plus your topic). Answer 3 to 5 threads honestly and helpfully, disclosing who you are, and link to a page of yours only where it truly helps. Assistants cite Reddit threads often."),
    "quora.com": ("Quora", "Answer the questions that match your topic in depth, in your own name or the business's, linking to a relevant page only where it helps."),
    "stackoverflow.com": ("Stack Overflow", "If your topic is technical, answer unanswered questions with complete, correct answers. Reputation there carries into search and assistants."),
    "github.com": ("GitHub", "Publish a small open resource (a README-driven guide, cheat sheet or examples repo) that links back to your site."),
    "medium.com": ("Medium", "Republish or summarize your best guide as an article with a canonical link back to your original."),
    "youtube.com": ("YouTube", "Turn your best guide into a short video with a full transcript and a link to the article in the description."),
    "wikipedia.org": ("Wikipedia", "Don't edit your own page; instead, earn coverage from independent sources that Wikipedia editors could cite."),
    "linkedin.com": ("LinkedIn", "Publish the guide as a LinkedIn article and share it from the business and founders' profiles."),
    "facebook.com": ("Facebook", "Keep the business page complete (address, hours, description with your exact name) and link it to your site."),
}


def fingerprint(category: str, title: str) -> str:
    return hashlib.sha1(f"{category}|{' '.join(title.lower().split())}".encode()).hexdigest()[:16]


def action(category: str, title: str, why: str, steps: list[str], *, priority: str = "P2", impact: str = "medium", effort: str = "medium",
           owner: str = "website owner", timeframe: str = "", verify: str = "", draft: dict | None = None, targets: list | None = None,
           evidence: list | None = None, source: str = "audit") -> dict:
    return {"category": category, "title": title[:300], "why": why, "steps": steps, "priority": priority, "impact": impact, "effort": effort, "owner": owner,
            "timeframe": timeframe, "verify": verify, "draft": draft or {}, "targets": targets or [], "evidence": evidence or [], "source": source}


# ---- 1. from the audit ---------------------------------------------------------------------------------------------

def from_audit(findings: list[dict], ctx: dict) -> list[dict]:
    out, origin = [], ctx["origin"]
    covered_meta = ctx["covered"]["meta"]
    covered_title = ctx["covered"]["title"]
    for f in findings:
        fid, ev = f["id"], [f["detail"], *[f"Affected: {u}" for u in f["urls"][:5]]]
        pri = {"high": "P0", "medium": "P1", "low": "P2", "info": "P3"}[f["severity"]]
        a = lambda *args, **kw: out.append(action(*args, source="audit", evidence=ev, **kw))
        if fid == "robots-blocks-all":
            a("technical", "Stop robots.txt blocking the whole site", f["detail"], ["Open robots.txt at the root of your site.", "Delete the blanket 'Disallow: /' under 'User-agent: *' (or narrow it to private folders).", "Save, publish, and re-check the file in your browser."],
              priority="P0", impact="high", effort="small", owner="web developer", timeframe="today", verify=f"Open {origin}/robots.txt: 'Disallow: /' must be gone.",
              draft={"label": "Replacement robots.txt", "language": "text", "content": drafts.robots_open(ctx["sitemap_url"]), "filename": "robots.txt"})
        elif fid == "robots-blocks-ai-search":
            a("technical", "Let AI answer crawlers read your site", f["detail"], ["Open robots.txt.", f"Remove the Disallow rules for: {', '.join(f['evidence'])}.", "Add the Allow block from the draft, then publish.", "Blocking training-only crawlers is separate and fine to keep."],
              priority="P0", impact="high", effort="small", owner="web developer", timeframe="today", verify="Open robots.txt and confirm none of those user-agents is disallowed. Re-run the site scan.",
              draft={"label": "robots.txt additions", "language": "text", "content": drafts.robots_allow(f["evidence"], ctx["sitemap_url"])})
        elif fid == "robots-missing":
            a("technical", "Add a robots.txt", f["detail"], ["Create a text file named robots.txt at the root of your site.", "Paste the draft, publish.", "Check it loads at /robots.txt."], priority="P2", impact="low", effort="small", owner="web developer",
              draft={"label": "robots.txt", "language": "text", "content": drafts.robots_open(ctx["sitemap_url"]), "filename": "robots.txt"}, verify=f"{origin}/robots.txt loads.")
        elif fid == "sitemap-missing":
            a("technical", "Publish an XML sitemap", f["detail"], ["Generate a sitemap from your CMS/site builder if it can (most can), or use the draft as a starting point.", "Publish it at /sitemap.xml.", "Add a 'Sitemap:' line to robots.txt.", "Submit it in Google Search Console and Bing Webmaster Tools."],
              priority="P0", impact="high", effort="small", owner="web developer", timeframe="1 day", verify="Search Console shows the sitemap as 'Success' with the expected number of pages.",
              draft={"label": "sitemap.xml (starter, from the pages found)", "language": "xml", "content": drafts.sitemap_xml(ctx["page_urls"]), "filename": "sitemap.xml"})
        elif fid == "sitemap-not-in-robots":
            a("technical", "Reference the sitemap in robots.txt", f["detail"], ["Add the line below to robots.txt.", "Publish."], priority="P2", impact="low", effort="small", owner="web developer",
              draft={"label": "robots.txt line", "language": "text", "content": f"Sitemap: {ctx['sitemap_url']}\n"}, verify="robots.txt ends with a Sitemap: line.")
        elif fid == "sitemap-tiny":
            a("technical", "Include every public page in the sitemap", f["detail"], ["Regenerate the sitemap so it lists all public pages.", "Resubmit in Search Console."], priority="P1", impact="medium", effort="small", owner="web developer")
        elif fid in ("llms-missing", "llms-empty"):
            a("technical", "Publish an llms.txt", f["detail"], ["Review the draft and correct any link or description.", "Publish it at /llms.txt (plain text, UTF-8).", "Keep it short: it is a map of your best pages, not a full index."],
              priority="P1", impact="medium", effort="small", owner="web developer", timeframe="1 day", verify=f"{origin}/llms.txt loads as plain text and lists your key pages.",
              draft={"label": "llms.txt (generated from your site)", "language": "markdown", "content": ctx["llms_txt"], "filename": "llms.txt"})
        elif fid == "not-indexed":
            a("technical", "Get your site into the search index", f["detail"], ["Verify your site in Google Search Console and Bing Webmaster Tools (a DNS record or an HTML file).", "Submit your sitemap in both.", "Use 'Request indexing' on the home page and your 3 most important pages.",
                                                                                    "Earn 2 or 3 links from sites that are already indexed (business listings, partner sites)."], priority="P0", impact="high", effort="medium", owner="website owner", timeframe="1 to 2 weeks",
              verify="A search for site:yourdomain.com returns your pages (indexing can take days to weeks).")
        elif fid == "no-https":
            a("technical", "Serve the site over HTTPS", f["detail"], ["Install an SSL certificate (many hosts include one free).", "Redirect all http:// URLs to https://.", "Update canonical links and the sitemap to https."], priority="P1", impact="medium", effort="small", owner="web developer")
        elif fid == "noindex":
            a("technical", "Remove accidental noindex tags", f["detail"], ["Find the noindex meta tag or header on the listed pages.", "Remove it (often a CMS 'discourage search engines' setting).", "Request indexing again."], priority="P0", impact="high", effort="small", owner="web developer", verify="View source on the pages: no 'noindex'.")
        elif fid == "meta-missing" and not all(u in covered_meta for u in f["urls"]):
            a("content", "Write meta descriptions for the pages that lack one", f["detail"], ["For each page, write 120 to 160 characters that say what the page offers and for whom.", "Put the main topic and your business name in it."], priority=pri, impact="medium", effort="small")
        elif fid in ("title-missing", "title-length") and not all(u in covered_title for u in f["urls"]):
            a("content", "Fix page titles", f["detail"], ["Give each page a unique title of 30 to 60 characters.", "Lead with the topic, end with your business name."], priority=pri, impact="medium", effort="small")
        elif fid in ("h1-missing", "h1-multiple"):
            a("content", "Give each page a single clear H1", f["detail"], ["Use one H1 that states the page's topic.", "Use H2/H3 for sections."], priority=pri, impact="low", effort="small")
        elif fid == "canonical-missing":
            a("technical", "Add canonical links", f["detail"], ["Add <link rel=\"canonical\" href=\"...\"> pointing to the page's preferred URL."], priority="P2", impact="low", effort="small", owner="web developer")
        elif fid == "thin":
            a("content", "Expand thin pages with specific content", f["detail"], ["For each listed page, answer the questions a customer would ask: what, for whom, how much, how it works.", "Aim for 300+ words of specific, factual content.", "Add an FAQ."], priority="P1", impact="medium", effort="medium")
        elif fid == "no-alt":
            a("content", "Add alt text to images", f["detail"], ["Describe what each image shows in a short phrase."], priority="P3", impact="low", effort="small")
        elif fid == "no-viewport":
            a("technical", "Add the mobile viewport tag", f["detail"], ["Add <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"> to the page head."], priority="P2", impact="low", effort="small", owner="web developer")
        elif fid == "schema-org-missing":
            a("structured_data", "Add Organization and WebSite structured data", f["detail"], ["Paste the JSON-LD from the draft into the <head> of your home page.", "Check every value is correct (add your logo URL and social profile URLs if you have them).", "Test it in Google's Rich Results Test."],
              priority="P1", impact="medium", effort="small", owner="web developer", timeframe="1 day", verify="The Rich Results Test / Schema Markup Validator reports an Organization and a WebSite with no errors.",
              draft={"label": "Organization + WebSite JSON-LD", "language": "json", "content": ctx["org_jsonld"]})
        elif fid == "schema-product-missing":
            sample = ctx["products"][:3]
            a("products", "Add Product structured data to product pages", f["detail"], ["Add a Product JSON-LD block to each product page, using the draft as the pattern.", "Fill every field from the page's own content (name, SKU, brand, price, currency, availability).", "Validate each page in the Rich Results Test."],
              priority="P0", impact="high", effort="medium", owner="web developer", timeframe="1 week", targets=[p["name"] for p in sample], verify="Rich Results Test shows 'Product' detected with offers on each product page.",
              draft={"label": f"Product JSON-LD (drafts for {len(sample)} product(s))", "language": "json", "content": "\n\n".join(drafts.product_jsonld(p) for p in sample) or "(no products detected yet)"})
        elif fid == "schema-offer-missing":
            a("products", "Add price and availability (Offer) to products", f["detail"], ["Add an 'offers' object with price, priceCurrency and availability to each Product JSON-LD block."], priority="P1", impact="medium", effort="small", owner="web developer")
        elif fid == "schema-article-missing":
            a("structured_data", "Mark up articles with Article structured data", f["detail"], ["Add Article/BlogPosting JSON-LD with headline, author, datePublished and dateModified."], priority="P2", impact="low", effort="small", owner="web developer")
        elif fid == "schema-faq-missing":
            a("structured_data", "Mark up FAQs with FAQPage structured data", f["detail"], ["Add FAQPage JSON-LD that mirrors the visible questions and answers exactly."], priority="P2", impact="low", effort="small", owner="web developer")
        elif fid == "orphans":
            a("technical", "Link to pages that nothing links to", f["detail"], ["Add links to each listed page from the home page, a category page or a related article.", "Use descriptive link text."], priority="P1", impact="medium", effort="small")
    return out


# ---- 2. from the research ---------------------------------------------------------------------------------------------

def from_lighthouse(lh: dict | None, ctx: dict) -> list[dict]:
    """Actions from the Lighthouse test of the home page (speed, accessibility, best practices, SEO)."""
    if not lh or not lh.get("available"):
        return []
    sc, out = lh.get("scores", {}), []
    ev_base = [f"Lighthouse ({lh.get('strategy', 'mobile')}) on {lh.get('url', '')}: " + ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in sc.items())]
    perf = sc.get("performance", 100)
    if perf < 90:
        opp = lh.get("opportunities", [])
        steps = [f"{o['title']}" + (f" ({o['detail']})" if o.get("detail") else "") for o in opp[:5]] or ["Compress and resize large images.", "Remove unused scripts and plugins.", "Turn on caching and a CDN."]
        out.append(action("technical", "Make the site faster", f"Lighthouse gives the home page {perf}/100 for speed. Slow pages lose visitors and are crawled less.",
                          steps + ["Re-run the site scan to see the new score."], priority="P0" if perf < 50 else "P1", impact="high" if perf < 50 else "medium", effort="medium", owner="web developer",
                          evidence=ev_base + [f"{k.upper()}: {v['display']}" for k, v in lh.get("metrics", {}).items() if v.get("display")][:5], source="audit", verify="Lighthouse performance is 90 or higher.",
                          timeframe="1 to 2 weeks"))
    for key, label, cat in (("seo", "SEO", "technical"), ("accessibility", "accessibility", "technical"), ("best_practices", "best-practice", "technical")):
        score = sc.get(key, 100)
        fails = lh.get("failed", {}).get(key, [])
        if score < 90 and fails:
            out.append(action(cat, f"Fix Lighthouse {label} issues", f"Lighthouse gives the home page {score}/100 for {label}.",
                              [f"Fix: {f['title']}" for f in fails[:6]] + ["Re-run the site scan to confirm."], priority="P1" if score < 70 else "P2", impact="medium", effort="small" if score >= 70 else "medium",
                              owner="web developer", evidence=ev_base, source="audit", verify=f"Lighthouse {label} score is 90 or higher."))
    return out


def starter(ctx: dict, has_rounds: bool) -> list[dict]:
    """What to do before the first round exists: the round itself, plus the basics that make it worthwhile."""
    out = []
    if not has_rounds:
        out.append(action("measurement", "Run your first round", "A round asks AI assistants the questions your customers ask, measures whether you are found, and tests improvements to your pages in a safe sandbox. It also writes the full report.",
                          ["Open Optimize and press Start a round.", "Wait for it to finish (it runs in the background).", "Review the proposed page changes and the report."], priority="P1", impact="high", effort="small", owner="you",
                          timeframe="today", verify="Round 1 appears under Reports.", source="loop"))
    if not ctx["products"]:
        out.append(action("products", "Add your key products or services", "Shoppers ask assistants about specific products. Naming yours lets Confiance test whether they are found.",
                          ["Open Products.", "Add each product or service, or import a CSV.", "Include the page address for each."], priority="P2", impact="medium", effort="small", owner="you", source="research"))
    return out


def from_research(research: dict, ctx: dict) -> list[dict]:
    out = []
    patterns, brand = research.get("patterns") or {}, ctx["name"]
    new_page_targets = ctx["new_page_targets"]
    edited_targets = ctx["edited_targets"]
    for e in research.get("queries", []):
        qid, q = e["id"], e["query"]
        if e["fit"] == "needs_content" and qid not in new_page_targets:
            out.append(action("content", f"Write a page that answers: “{q}”", e["fit_reason"] + " The closest page you have covers only about %d%% of what people ask." % int(e["coverage"] * 100),
                              ["Use the brief in the draft to write the page in your own voice.", "Publish it at a clean URL, add it to your sitemap, and link to it from your home page and a related page.", "Add FAQPage markup that mirrors the visible questions."],
                              priority="P1", impact="high", effort="medium", timeframe="1 to 2 weeks", targets=[qid], source="research",
                              draft={"label": "Page brief", "language": "markdown", "content": drafts.page_outline(q, brand, patterns, ctx["facts"])},
                              evidence=[f"Search results for this question are led by: {', '.join(e['top_domains'][:3]) or 'other sites'}"],
                              verify=f"In 1 to 3 weeks search '{q}' and check whether the page appears; re-run this test."))
        elif e["fit"] == "in_reach" and qid not in edited_targets and e.get("best_page"):
            path = urlsplit(e["best_page"]).path or "/"
            out.append(action("content", f"Strengthen {path} for: “{q}”", e["fit_reason"],
                              ["Add an H2 phrased like the question, followed by a 40 to 60 word direct answer that names your business.", "Add the specific facts, numbers and examples people look for.", "Link to it from your home page and a related page.", "Make sure the title and meta description mention the topic."],
                              priority="P2", impact="medium", effort="small", targets=[qid], source="research", evidence=[f"Best-matching page: {e['best_page']}"]))
    brand_e = research.get("brand") or {}
    if brand_e and brand_e.get("status") == "not_found":
        out.append(action("off_page", "Make sure a search for your business name finds you", "Searching for your business by name doesn't show your site. If people (or assistants) can't find you by name, nothing else works.",
                          ["Verify the site in Google Search Console and Bing Webmaster Tools and submit your sitemap.", "Claim the business name on the platforms your customers use (Google Business Profile if you serve a local area, LinkedIn, and one or two social profiles), each with the exact name and a link to your site.",
                           "Make the home page title start with your business name.", "Link your profiles to each other and to the site."],
                          priority="P0", impact="high", effort="small", timeframe="1 week", source="research", evidence=[f"Search results for “{ctx['name']}” were led by: {', '.join(brand_e.get('top_domains', [])[:3]) or 'other sites'}"],
                          verify=f"Search for “{ctx['name']}”: your site appears on the first page."))
    doms = Counter(d for e in research.get("queries", []) if e["status"] != "found" for d in e.get("top_domains", []))
    for dom, (label, how) in COMMUNITY.items():
        if any(dom in d for d in doms):
            out.append(action("off_page", f"Show up where assistants already look: {label}", f"{label} appears in the results for questions you don't win yet, so assistants read it when answering.", [how, "Do this a little at a time, and never post the same link repeatedly."],
                              priority="P2", impact="medium", effort="medium", owner="website owner", timeframe="ongoing", source="research", evidence=[f"{label} appears for {sum(dom in d for d in doms.elements())} question(s)"]))
    return out


# ---- 3. the tested changes ----------------------------------------------------------------------------------------------

def _describe(op: dict) -> str:
    t = op.get("type")
    return {"set_title": lambda: f"Title: {op.get('text')}", "set_meta_description": lambda: f"Meta description: {op.get('content')}",
            "add_faq": lambda: "Add an FAQ section:\n" + "\n".join(f"  - {i.get('q')} {i.get('a')}" for i in (op.get("items") or [])),
            "add_jsonld": lambda: f"Add structured data:\n{op.get('json')}", "insert_after": lambda: f"Add after {op.get('selector')}:\n{op.get('html')}",
            "append_section": lambda: f"Add a section:\n{op.get('html')}", "replace_block": lambda: f"Replace {op.get('selector')} with:\n{op.get('html')}",
            "create_page": lambda: f"New page {op.get('path')}: {op.get('title')}\n{op.get('html')}"}.get(t, lambda: str(op))()


def from_proposals(props: list[dict], verdict: dict, ctx: dict) -> list[dict]:
    out = []
    improved = verdict.get("label") == "improved"
    for p in props:
        text = "\n\n".join(_describe(o) for o in p["ops"])
        path = urlsplit(p["url"]).path or "/"
        if p["kind"] == "new_page":
            out.append(action("content", f"Publish the new page {path}", p["rationale"] or "A new page that answers questions your site doesn't cover yet.",
                              ["Create the page from the exported file (new-pages folder) or paste the HTML into your CMS.", f"Publish it at {path}.", "Add it to your sitemap and link to it from the home page and one related page.", "Request indexing in Search Console."],
                              priority="P1" if not improved else "P0", impact="high", effort="small", owner="website owner", timeframe="this week", targets=p["targets"], source="loop",
                              draft={"label": f"Page content for {path}", "language": "text", "content": text}, evidence=[f"Tested in the sandbox: {verdict.get('text', '')}"],
                              verify=f"The page loads at {path}; re-run this test in a few days."))
        else:
            out.append(action("content", f"Publish the improved {path}", p["rationale"] or "Changes to an existing page, tested in the sandbox.",
                              ["Download the change package from the round's page (each change comes as a file and a diff).", "Apply each change to the live page; don't touch anything you locked.", "Publish, then request indexing in Search Console."],
                              priority="P1" if not improved else "P0", impact="medium", effort="small", owner="website owner", timeframe="this week", targets=p["targets"], source="loop",
                              draft={"label": "What changes", "language": "text", "content": text}, evidence=[f"Tested in the sandbox: {verdict.get('text', '')}"], verify="Open the page and confirm each change; re-run this test in a few days."))
    return out


# ---- 4. products ------------------------------------------------------------------------------------------------------------

def from_products(products: list[dict], research: dict, ctx: dict) -> list[dict]:
    out = []
    no_url = [p for p in products if not p.get("url")]
    if no_url:
        out.append(action("products", "Give each product its own page", f"{len(no_url)} tracked product(s) have no product page, so nothing can be found or cited for them.",
                          ["Create one page per product with a clear name, specs, price and who it's for.", "Add Product structured data (see the product markup action)."], priority="P1", impact="high", effort="medium",
                          targets=[p["name"] for p in no_url[:8]], source="research"))
    weak = [e for e in research.get("queries", []) if str(e["id"]).startswith("p") and e.get("product_rank") is None and e["status"] != "found"]
    if weak:
        names = sorted({next((p["name"] for p in products if f"p{p['id']}." in e["id"] or e["id"].startswith(f"p{p['id']}.")), "") for e in weak} - {""})
        out.append(action("products", "Make product pages easier to choose", "Shoppers' questions don't currently lead to your product pages in search.",
                          ["On each product page, add: who it's for, key specs in a table, how it compares with the usual alternatives, and a short FAQ.", "Use the exact product name and model in the title and H1.", "Add reviews or ratings only if they are real and shown on the page."],
                          priority="P1", impact="high", effort="medium", targets=names[:8], source="research", evidence=[e["query"] for e in weak[:4]]))
    return out


def measurement(ctx: dict) -> list[dict]:
    return [action("measurement", "Re-test after you publish", "The sandbox estimates the effect of a change; only a real re-test shows whether assistants now find and use it.",
                   ["Publish the changes above.", "Wait 3 to 7 days (assistants and search engines re-crawl slowly).", "Start a new round, which re-measures against the same questions.", "Repeat monthly."],
                   priority="P2", impact="high", effort="small", timeframe="3 to 7 days after publishing", source="loop", verify="The next round's 'today' numbers match or beat this round's tested numbers.")]


# ---- 5. AI-tailored ---------------------------------------------------------------------------------------------------------------

AI_SCHEMA = {"type": "object", "properties": {"actions": {"type": "array", "items": {
    "type": "object", "properties": {
        "title": {"type": "string"}, "category": {"type": "string", "enum": ["content", "technical", "structured_data", "off_page", "products", "measurement"]},
        "priority": {"type": "string", "enum": ["P0", "P1", "P2", "P3"]}, "impact": {"type": "string", "enum": ["high", "medium", "low"]},
        "effort": {"type": "string", "enum": ["small", "medium", "large"]}, "why": {"type": "string"},
        "steps": {"type": "array", "items": {"type": "string"}}, "draft_label": {"type": "string"}, "draft_text": {"type": "string"},
        "verify": {"type": "string"}, "timeframe": {"type": "string"}},
    "required": ["title", "category", "priority", "impact", "effort", "why", "steps", "draft_label", "draft_text", "verify", "timeframe"], "additionalProperties": False}}},
    "required": ["actions"], "additionalProperties": False}


def ai_actions(evidence: dict, have: list[str]) -> list[dict]:
    data = llm.json_call(
        "plan.tailor", system="You are a Generative Engine Optimization and SEO consultant writing a plan for one specific business. Be concrete and honest. "
        "Never invent facts, statistics or partner names. If you don't know something, say what to find out.",
        prompt="Evidence about this business (JSON):\n" + json.dumps(evidence, ensure_ascii=False)[:14000] +
               "\n\nActions already in the plan (do NOT repeat these):\n- " + "\n- ".join(have[:40]) +
               "\n\nWrite 4 to 6 ADDITIONAL actions specific to THIS business and its evidence. Each must be concrete: name the real page types, headings, tools, "
               "communities or directories relevant to this industry and region; give 3 to 6 imperative steps; include a ready-to-use draft (outline, copy, or checklist) in draft_text; "
               "say how to verify success. Avoid generic advice like 'build backlinks' or 'create quality content' without saying exactly where and what.",
        schema=AI_SCHEMA, max_tokens=12000)
    out = []
    for a in data["actions"][:6]:
        if a["title"].strip() and len(a["steps"]) >= 2:
            out.append(action(a["category"], a["title"], a["why"], a["steps"], priority=a["priority"], impact=a["impact"], effort=a["effort"], timeframe=a["timeframe"], verify=a["verify"],
                              draft={"label": a["draft_label"], "language": "markdown", "content": a["draft_text"]} if a["draft_text"].strip() else {}, source="ai"))
    return out


# ---- orchestration ------------------------------------------------------------------------------------------------------------------

def _context(s, project: Project, run: Run | None) -> tuple[dict, list[dict], dict, dict]:
    rec = scan_mod.latest(s, project.id)
    data = rec.data if rec else {"discovery": {}, "audit": {"findings": []}, "pages": []}
    origin = project.site_url or f"https://{project.domain}"
    disc = data.get("discovery", {})
    pages_meta = [{"url": p["url"], "title": p.get("title", ""), "type": p.get("type", "other"), "desc": p.get("meta_description", "")} for p in data.get("pages", [])]
    prods = [{"id": p.id, "name": p.name, "sku": p.sku, "url": p.url, "brand": p.brand, "category": p.category, "price": p.price, "description": (p.attributes or {}).get("description", "")}
             for p in s.scalars(select(Product).where(Product.project_id == project.id, Product.active))]
    summary_item = next(iter(kb_store._items(s, project, "summary")), None)
    facts = [f.content for f in kb_store._items(s, project, "fact")][:8]
    sm = (run.summary if run else None) or {}
    props = []
    for cp in (s.scalars(select(ChangeProposal).where(ChangeProposal.run_id == run.id, ChangeProposal.status == "candidate")) if run else []):
        pg = s.get(Page, cp.page_id)
        props.append({"id": cp.id, "url": pg.url, "kind": cp.kind, "ops": cp.ops, "rationale": cp.rationale, "targets": cp.target_questions})
    covered = {"meta": {p["url"] for p in props if any(o.get("type") == "set_meta_description" for o in p["ops"])},
               "title": {p["url"] for p in props if any(o.get("type") == "set_title" for o in p["ops"])}}
    sitemap_url = next((x["url"] for x in disc.get("sitemaps", []) if x.get("status") == 200), origin.rstrip("/") + "/sitemap.xml")
    ctx = {"name": project.name, "origin": origin, "sitemap_url": sitemap_url, "products": prods, "facts": facts, "page_urls": [origin.rstrip("/") + "/"] + [p["url"] for p in pages_meta if p["url"].rstrip("/") != origin.rstrip("/")],
           "covered": covered, "new_page_targets": {q for p in props if p["kind"] == "new_page" for q in p["targets"]}, "edited_targets": {q for p in props if p["kind"] == "edit" for q in p["targets"]},
           "org_jsonld": drafts.org_jsonld(project.name, origin, summary_item.content if summary_item else ""),
           "llms_txt": drafts.llms_txt(project.name, summary_item.content if summary_item else "", pages_meta, prods)}
    return ctx, props, data, sm


def generate(run_id: int, use_ai: bool = True) -> int:
    with session_scope() as s:
        run = s.get(Run, run_id)
        project = s.get(Project, run.project_id)
        ctx, props, data, sm = _context(s, project, run)
        pid = project.id
    ev = sm.get("evaluation") or {}
    research = sm.get("research") or {}
    actions = from_audit(data["audit"]["findings"], ctx) + from_research(research, ctx) + from_lighthouse(data.get("lighthouse"), ctx) + from_proposals(props, ev.get("verdict", {}), ctx) + from_products(ctx["products"], research, ctx) + measurement(ctx)
    if use_ai:
        try:
            activity.emit("Tailoring extra actions to your business", "tool")
            evidence = {"business": ctx["name"], "domain": urlsplit(ctx["origin"]).netloc, "facts": ctx["facts"], "site_audit_score": data.get("audit", {}).get("score"),
                        "top_problems": [f["title"] for f in data["audit"]["findings"][:8]], "questions": [{k: e.get(k) for k in ("query", "status", "rank", "fit", "top_domains")} for e in research.get("queries", [])],
                        "winning_pages": research.get("patterns"), "products": [{"name": p["name"], "category": p["category"], "price": p["price"]} for p in ctx["products"][:10]],
                        "sandbox_result": ev.get("verdict", {}).get("text"), "new_pages_proposed": [p["url"] for p in props if p["kind"] == "new_page"]}
            actions += ai_actions(evidence, [a["title"] for a in actions])
        except Exception as e:  # the deterministic plan stands on its own
            activity.emit(f"Skipped the AI-tailored part of the plan ({str(e)[:80]}).", "warn")
    seen, unique = set(), []
    for a in actions:
        fp = fingerprint(a["category"], a["title"])
        if fp not in seen:
            seen.add(fp)
            unique.append({**a, "fp": fp})
    unique.sort(key=lambda a: (PRIORITY_ORDER.get(a["priority"], 2), IMPACT_ORDER.get(a["impact"], 1), EFFORT_ORDER.get(a["effort"], 1)))
    with session_scope() as s:
        _save(s, pid, run_id, unique)
    return len(unique)



def _save(s, pid: int, run_id: int | None, unique: list[dict]) -> None:
    prior = {old.fp: old.status for old in s.scalars(select(PlanAction).where(PlanAction.project_id == pid).order_by(PlanAction.id))}  # what the person did, by fingerprint
    for old in s.scalars(select(PlanAction).where(PlanAction.project_id == pid, PlanAction.run_id.is_(None) if run_id is None else PlanAction.run_id == run_id)):
        s.delete(old)
    for i, a in enumerate(unique, 1):
        keep = prior.get(a["fp"]) in ("done", "dismissed", "doing")
        s.add(PlanAction(project_id=pid, run_id=run_id, seq=i, category=a["category"], priority=a["priority"], title=a["title"], why=a["why"], steps=a["steps"], draft=a["draft"],
                         targets=a["targets"], impact=a["impact"], effort=a["effort"], owner=a["owner"], timeframe=a["timeframe"], verify=a["verify"], evidence=a["evidence"],
                         source=a["source"], fp=a["fp"], status=prior[a["fp"]] if keep else "todo"))


def generate_initial(project_id: int) -> int:
    """The starting plan, written straight after the first site scan (no round needed, no AI needed): technical and
    structured-data fixes with ready-to-paste drafts, Lighthouse findings, product basics and 'run your first round'."""
    with session_scope() as s:
        project = s.get(Project, project_id)
        ctx, _, data, _ = _context(s, project, None)
        has_rounds = s.scalar(select(func.count()).select_from(Run).where(Run.project_id == project_id)) > 0
    actions = starter(ctx, has_rounds) + from_audit(data["audit"]["findings"], ctx) + from_lighthouse(data.get("lighthouse"), ctx) + from_products(ctx["products"], {}, ctx)
    seen, unique = set(), []
    for a in actions:
        fp = fingerprint(a["category"], a["title"])
        if fp not in seen:
            seen.add(fp)
            unique.append({**a, "fp": fp})
    unique.sort(key=lambda a: (PRIORITY_ORDER.get(a["priority"], 2), IMPACT_ORDER.get(a["impact"], 1), EFFORT_ORDER.get(a["effort"], 1)))
    with session_scope() as s:
        _save(s, project_id, None, unique)
    return len(unique)


def current_run_id(s, project_id: int) -> int | None:
    """The round whose plan is current, or None when only the starting plan exists (or there is no plan)."""
    return s.scalar(select(func.max(PlanAction.run_id)).where(PlanAction.project_id == project_id))


def ensure_initial(project_id: int) -> None:
    """Write the starting plan for a project that was scanned but has no plan yet (scanned before starting plans existed)."""
    with session_scope() as s:
        need = s.scalar(select(func.count()).select_from(PlanAction).where(PlanAction.project_id == project_id)) == 0 and scan_mod.latest(s, project_id) is not None
    if need:
        generate_initial(project_id)


def current(s, project_id: int) -> list[PlanAction]:
    """The plan to show: the latest round's, else the starting plan."""
    rid = current_run_id(s, project_id)
    return list(s.scalars(select(PlanAction).where(PlanAction.project_id == project_id, PlanAction.run_id.is_(None) if rid is None else PlanAction.run_id == rid).order_by(PlanAction.seq)))


__all__ = ["generate", "generate_initial", "ensure_initial", "current", "domain_of"]
