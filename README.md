# CONFIANCE

Agentic Generative Engine Optimization (GEO): make a client's website findable, citable and correctly
described by AI answer engines. Today the assistant under test is any OpenAI-compatible model; more adapters
(Claude and Gemini adapters exist in the code but are switched off in the app) plug into `engines/`.

```
onboard (brief: goals + constraints) -> knowledge base -> personas -> baseline sim
   -> optimizer agent (ReAct) -> constraint guard -> candidate sim -> paired evaluation
   -> HUMAN APPROVAL -> deploy (git draft PR / CMS / export) -> live measurement -> next iteration
                     drift monitor + audit trail + versioned snapshots run alongside
```

## Run it

```bash
./start.sh        # installs what it needs, starts everything, opens http://localhost:5173
```

The web app walks a non-technical person through everything: connect an AI model, enter a business name and
website address, confirm suggested customer questions, say what must never change, then press **Find
improvements**. There is no JSON, code or configuration to touch. Settings entered in the app are stored in
`backend/data/secrets.json` (owner-only permissions); keys are never sent back to the browser.

### Connecting an AI model (no paid API needed to try it)

Confiance talks to **any OpenAI-compatible endpoint**, and the same connection powers the internal agents and the
assistant that gets tested:

| Provider | Address | Key |
|---|---|---|
| Google Gemini (free tier) | `https://generativelanguage.googleapis.com/v1beta/openai/` | yes, free at aistudio.google.com/apikey |
| Ollama (free, local) | `http://localhost:11434/v1` | none |
| OpenAI | `https://api.openai.com/v1` | yes |
| OpenRouter, Groq, LM Studio, vLLM, ... | their `/v1` address | usually |

While a round runs, the app shows a real progress bar, a heartbeat (time since last activity), the current speed, and a live feed
of what is being asked, searched, read and proposed. Speed adapts to the service's limits (see the doc below).

Two model roles: a **main** model for the hard, occasional work and an optional **fast** model for the many small jobs
(the app suggests both for Gemini). Run size (Quick / Standard / Thorough) is chosen per round and shows an estimate of AI
requests, because free tiers allow few. Details and sources: [docs/free-tier-research.md](docs/free-tier-research.md).

Pick a model that supports **tool calling** (the connection test checks this). Web search defaults to free
DuckDuckGo, so a local model plus free search costs nothing. Tavily, Brave and self-hosted SearXNG are also supported.
Why built-in provider search is not used for experiments: [docs/search-integration-research.md](docs/search-integration-research.md).

Developers: `cd backend && uv run pytest` (67 tests, no network or keys). `backend/scripts/seed_demo.py` fills a
throwaway database with a scripted practice round (fake data) so the app can be explored with nothing connected.
Advanced settings are `CONFIANCE_*` env vars (`backend/src/confiance/config.py`).

## How the sandbox works (counterfactual injection)

Search is a tool call, so the sandbox intercepts it in code during the agent loop. In **controlled mode**
each engine's model runs a real ReAct loop (reason -> `web_search` / `fetch_page` -> observe -> ...) against
tools *we* execute (`search/sandbox.py`). Third-party results come from a real search API. Results and
fetches for the client's own domain are served from our snapshot store:
the **baseline arm gets the live version, the candidate arm gets the modified version**. Both arms share one
cache of real search results, and personas/questions/samples are paired, so a measured difference is
attributable to the page change.

**Native mode** calls a provider's own hosted search (only real OpenAI among the compatible providers). It cannot be
intercepted, so it is used for what the real world sees. Providers without built-in search (Ollama etc.) get the same
"real world" measurement by running the tool loop against the live web, with no snapshots swapped in.

## Constraints: what can and cannot change

The brief (versioned, immutable) holds `editable_url_globs`, `locked_selectors`, `locked_phrases`,
`allowed_ops`, `forbidden_claims`, `max_change_ratio`. `optimizer/guard.py` enforces them **in code**, plus
platform rules: no invented numbers (must appear on the page or in the KB), no hidden text, no
instructions aimed at AI models, valid JSON-LD. A blocked proposal returns to the agent as an observation,
so it can revise, but it cannot override the guard. The optimizer only emits structured ops
(`optimizer/ops.py`), never raw page rewrites.

## Token cost controls

- One-time KB build, skipped when page content hash is unchanged; agents get a compact card, not the site.
- The card + brief + tool list are a prompt-cache prefix for the optimizer, persona and judge calls.
- Cheap model (Haiku) for personas, phrasing and judging; strong model only for the optimizer.
- Stages persist output, so a resumed run never repeats finished (paid) stages.
- Every call lands in `usage_records` (per component / run / model) - see the **cost** tab.

## Safety, audit, versioning

- **Audit**: append-only, hash-chained (`audit.py`); `GET /api/audit/verify` detects any edit or deletion.
  Every tool call, guard verdict, approval, deploy and alert is logged.
- **Snapshots**: page content is stored content-addressed and never overwritten; briefs are versioned.
  Deploy refuses if the live page changed since the proposal (no clobbering client edits).
  Rollback re-deploys the previous version as a new version, so history is only ever appended.
- **Approval gate is mandatory**: nothing deploys unapproved. PR / CMS-draft deploys stay `draft_open`
  until a human confirms it is live, and only then does the live pointer move and measurement start.

## Drift monitor

`drift/monitor.py` runs a fixed canary panel per engine on a schedule (default daily) and alerts on: reported
model id changed, configured model missing from the provider's list (deprecation), response shape changed
(API change), search-use / citation / length shifts (with confidence intervals), canary error rate.
Baselines only move when a human accepts them. Alerts go to the UI, Slack and email, deduplicated.

## Known limitations (be aware before relying on it)

1. **The sandbox measures content effects, not ranking effects.** Findability (is the site in real search results?) is
   checked and reported separately and never simulated. The practice test guarantees your page is among the results in
   both rounds, so it measures how well the page works when found. See
   [docs/measuring-improvement.md](docs/measuring-improvement.md). Only the post-publish check is real evidence of
   ranking changes.
2. **API != consumer app.** Engines are tested through provider APIs; answers in chatgpt.com or AI Overviews can
   differ, and a small local model is not ChatGPT: results with Ollama show the *mechanics* work, not how a
   particular commercial assistant will behave. Google AI Overviews has no API and is not covered.
3. **Only the local-model path has been run live.** The real-OpenAI native search and the deployers were written
   against documentation and are unit-tested only. The WordPress connector is not exposed in the app.
4. Git-PR deploy writes the new HTML to the page's `source_path`, so it suits static-HTML sites. For
   framework-built sites use the CMS connector or the export package.
5. Retrieval is BM25 (no vector DB) and storage is SQLite by default. For Postgres, serialise audit writes
   (e.g. `pg_advisory_xact_lock`) to keep the hash chain linear under concurrency.
6. Live measurement needs time: engines re-crawl slowly (`post_deploy_measure_after_hours`, default 72).
