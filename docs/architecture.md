# Architecture

A module-by-module walkthrough. For diagrams and the product overview see the [README](../README.md#-architecture).

## Design principles

1. **Agents propose, code disposes.** Every AI output passes deterministic checks (`optimizer/guard.py`) before it is
   tested, and a human before it ships.
2. **Measure, never assume.** Every claim of improvement carries a confidence interval; "inconclusive" is a normal,
   honest outcome.
3. **Everything is resumable and append-only.** Stages persist output; snapshots, versions and the audit log are never
   rewritten.
4. **Plain language at the edge.** The API and UI speak in business terms; technical detail is one click away.

## Request and data flow

```
browser ──/api──▶ FastAPI ──▶ pipeline.orchestrator ──▶ stage workers ──▶ SQL + blob store
                     │                 ▲                      │
                     │                 └── scheduler ─────────┤  (drift checks, post-deploy wake-ups)
                     └── activity feed (polled by the UI) ◀───┘
```

The UI polls lightweight endpoints (`/api/runs/{id}/live`, `/api/projects/{id}/overview`) instead of holding sockets
open. Long work runs in background tasks; each AI call, search and page read emits an *activity event* that the UI shows
as a plain-language live feed.

## Modules

| Module | Responsibility |
|---|---|
| `api/app.py`, `simple.py`, `v2.py` | REST endpoints. `simple.py` is the non-technical onboarding surface; `v2.py` serves dashboard views. `app.py` also serves the built web app from `frontend/dist` when present. |
| `pipeline/orchestrator.py` | The round as a resumable state machine: `requirements → research → baseline → loop → finalize → awaiting_approval → deploy → awaiting_live → awaiting_measure → measure → done`. Claims runs atomically, persists each stage, recovers interrupted runs on startup. |
| `pipeline/plans.py` | Round sizes (Quick / Standard / Thorough) and the estimate of AI requests shown before you start. |
| `settings.py` | Per-project optimization settings with hard limits (loops 1-10, patience, minimum effect, new pages). |
| `discovery/` | Reads robots.txt, sitemaps and llms.txt; classifies pages; audits structured data; finds products; runs Lighthouse (local or PageSpeed Insights). |
| `research/run.py` | Deterministic research: real search for each question, who wins, competitor page features, coverage of the question by your site, fit classification (*winning / in reach / needs content*). |
| `sim/` | `personas.py` (simulated customers and prompt phrasing), `runner.py` (engines × personas × questions × samples, in parallel), `metrics.py` (retrieved / used page / mentioned / cited / linked), `stats.py` (Wilson and bootstrap intervals), `verdict.py` (plain-language verdict), `findability.py` (real-search rank, no AI). |
| `search/` | `providers.py` (DuckDuckGo, Tavily, Brave, SearXNG, offline fixture), `base.py` (shared cache), `sandbox.py` (the counterfactual tool session). |
| `engines/` | Assistant adapters behind one `Engine` contract (`controlled()` tool loop, `native()` hosted search, `list_models()`). OpenAI-compatible is exposed; Claude, Gemini and an offline fixture exist. |
| `optimizer/` | `agent.py` (ReAct optimizer), `ops.py` (structured edit operations and schema), `guard.py` (client constraints + platform safety), `newpage.py` (brand-new pages). |
| `kb/store.py` | Knowledge base: page import with content-hash cache, extraction of summary and facts, BM25 passage retrieval, compact "card". |
| `plan/` | Layered improvement plan (audit, research, tested edits, products, AI-tailored) with ready-to-use drafts (robots.txt, sitemap, llms.txt, JSON-LD, page briefs). |
| `reports.py` | HTML and Markdown report of a round. |
| `deploy/` | `Deployer` contract; `export.py` (zip package), `git_pr.py` (draft pull request), `wordpress.py` (CMS draft); `service.py` adds the approval gate, stale-base protection, snapshots and rollback. |
| `snapshots.py` | Content-addressed blobs (SHA-256) and a parent chain of page versions. |
| `audit.py` | Append-only hash-chained audit log and `verify_chain`. |
| `drift/monitor.py` | Canary panel per engine, baseline fingerprints, alert rules, `accept_baseline`. |
| `scheduler.py` | APScheduler jobs: periodic drift check; 15-minute wake-up for runs waiting on a live confirmation or a measurement delay. |
| `notify.py` | Alerts to the UI, Slack and email, de-duplicated. |
| `llm.py`, `usage.py` | Single OpenAI-compatible client with pacing, retries, prompt-cache prefixes and the per-call cost ledger. |
| `secrets_store.py` | Owner-only `secrets.json` for settings entered in the UI. |

## The optimization loop in detail

1. **Prompt set.** Personas phrase each target question once; the set is generated once per run and reused by every arm
   so arms are paired.
2. **Baseline arm.** The sandbox serves your *live* page versions; the assistant runs a tool loop; metrics are scored.
3. **Draft.** The optimizer reads the KB card, the brief, research and (from loop 2) the previous loop's per-question
   results. Each `propose` call is validated by the guard; violations come back as observations.
4. **Candidate arm.** Same prompts, same cached real search results, but the sandbox serves the *modified* versions.
5. **Decide.** Paired deltas → bootstrap interval → verdict. The loop continues if there is room under `max_loops` and
   the gain beats `min_gain`; it stops after `patience` loops without progress. The best loop is what you review.
6. **Finalize.** Plan, report and a package of approved changes.

## Metrics

| Metric | Meaning |
|---|---|
| Found in real search | Your domain appears in the top results for the question (real search, never simulated). |
| Retrieved / opened | The assistant's search surfaced your page / it opened it. |
| Used your page | The answer drew on the page's content. |
| Named you / product | The answer mentioned your brand or the specific product. |
| Linked | The answer cited your URL. |

Two things are deliberately **not** blended into one score: findability and usefulness-when-found
(see [measuring-improvement.md](measuring-improvement.md)).

## Persistence

SQLAlchemy models live in `models.py`: `Project`, `Brief` (versioned), `Page` / `PageVersion`, `KnowledgeItem`,
`Persona`, `Run` / `RunLoop`, `SimulationBatch` / `SimulationResult`, `ChangeProposal`, `Deployment`, `PlanAction`,
`Product`, `SiteAudit`, `DriftBaseline` / `DriftCheck`, `Alert`, `AuditEvent`, `UsageRecord`. SQLite is the default;
blobs are stored on disk under `blob_dir` by hash. Existing data is migrated automatically when the API starts.

## Extension points

- **New assistant:** subclass `Engine`, implement `controlled`, `native`, `list_models`, decorate with `@register("name")`.
- **New search provider:** implement the `SearchProvider` protocol in `search/base.py` and add it to `build_provider`.
- **New deploy target:** subclass `Deployer` in `deploy/`; it receives approved, guard-checked `Change` objects and
  returns `applied`, `draft_open` or `failed`.
- **New guard rule:** add a check in `optimizer/guard.py`; the agent will see violations automatically.

## Packaging

The Docker image is a two-stage build: Node builds `frontend/dist`; a Python 3.13 slim image installs locked backend
dependencies with `uv`, copies the built web app, runs as a non-root user and stores state under `/data`. The API
serves the web app itself (`CONFIANCE_STATIC_DIR`), so one container and one port is the whole product.
