# Configuration

Normal use needs **no configuration**: connect a model and a search provider in the app. This page lists everything
else. Settings come from, in order: environment variables (`CONFIANCE_*`), a `.env` file in the working directory, then
defaults. Values entered in the app are stored in `secrets.json` on the data volume and applied at start-up.

Source of truth: [`backend/src/confiance/config.py`](../backend/src/confiance/config.py).

## Model connection

| Variable | Default | Notes |
|---|---|---|
| `CONFIANCE_LLM_BASE_URL` | `https://api.openai.com/v1` | Any OpenAI-compatible `/v1` address. From Docker, reach Ollama at `http://host.docker.internal:11434/v1`. |
| `CONFIANCE_LLM_API_KEY` | none | Not needed for Ollama / LM Studio. |
| `CONFIANCE_LLM_MODEL` | none | Main model (optimizer, plan). Must support tool calling. |
| `CONFIANCE_LLM_WORKER_MODEL` | main model | Optional cheaper model for personas, phrasing and judging. |
| `CONFIANCE_LLM_TIMEOUT_S` | 300 | Max silence between streamed chunks. |
| `CONFIANCE_LLM_MAX_CONCURRENCY` | 4 | Simultaneous AI calls. Lower for free tiers and small GPUs. |
| `CONFIANCE_LLM_RPM` | 0 | Client-side requests per minute; 0 = none (retries still back off on 429). |
| `CONFIANCE_LLM_REASONING_EFFORT` | provider default | Confiance never lowers thinking on its own. |

## Search

| Variable | Default | Notes |
|---|---|---|
| `CONFIANCE_SEARCH_PROVIDER` | `duckduckgo` | `duckduckgo` (no key), `searxng`, `tavily`, `brave`. |
| `CONFIANCE_SEARXNG_URL` | none | For `searxng`. |
| `CONFIANCE_TAVILY_API_KEY`, `CONFIANCE_BRAVE_API_KEY` | none | For those providers. |
| `CONFIANCE_LIGHTHOUSE` | `auto` | `off` skips Lighthouse. |
| `CONFIANCE_PAGESPEED_API_KEY` | none | Reliable PageSpeed Insights fallback when Chrome is not installed (e.g. in Docker). |

## Simulation and cost

| Variable | Default | Notes |
|---|---|---|
| `CONFIANCE_SAMPLES_PER_QUESTION` | 3 | More samples give tighter intervals and cost more. |
| `CONFIANCE_MAX_ENGINE_STEPS` | 6 | Tool-loop steps per conversation. |
| `CONFIANCE_MAX_PARALLEL_CALLS` | 6 | Parallel conversations. |
| `CONFIANCE_USE_LLM_JUDGE` | false | Extra AI call per answer; deterministic metrics stay on regardless. |

Per-round options (loops 1-10, patience, minimum effect, new pages, round size) are set on the Optimize page and stored
per project; the code clamps them to safe limits.

## Monitoring and alerts

| Variable | Default | Notes |
|---|---|---|
| `CONFIANCE_ENABLE_SCHEDULER` | true | Drift checks and post-deploy wake-ups. |
| `CONFIANCE_DRIFT_INTERVAL_MINUTES` | 1440 | Canary panel frequency. |
| `CONFIANCE_DRIFT_CANARY_SAMPLES` | 3 | Samples per canary question. |
| `CONFIANCE_POST_DEPLOY_MEASURE_AFTER_HOURS` | 72 | Delay before the real-world check. |
| `CONFIANCE_SLACK_WEBHOOK_URL` | none | Alert webhook. |
| `CONFIANCE_SMTP_HOST` / `_PORT` / `_USER` / `_PASSWORD` | none / 587 | Email alerts. |
| `CONFIANCE_ALERT_EMAIL_FROM` / `_TO` | none | Email addresses. |

## Storage and serving

| Variable | Default | Docker image |
|---|---|---|
| `CONFIANCE_DATABASE_URL` | `sqlite:///./confiance.db` | `sqlite:////data/confiance.db` |
| `CONFIANCE_BLOB_DIR` | `./data/blobs` | `/data/blobs` |
| `CONFIANCE_SECRETS_FILE` | `./data/secrets.json` | `/data/secrets.json` |
| `CONFIANCE_STATIC_DIR` | `../frontend/dist` | `/app/frontend/dist` |
| `CONFIANCE_CORS_ORIGINS` | `["http://localhost:5173"]` | only needed when the UI is hosted elsewhere |
| `CONFIANCE_ALLOW_OFFLINE` | false | Enables the offline test engine and search fixtures (demo and tests only). |

## Launcher

| Variable | Default | Notes |
|---|---|---|
| `PORT` | 8000 | Port for `./run.sh` (Docker publishes the same port). |
| `NO_BROWSER` | unset | `1` = do not open a browser tab. |
