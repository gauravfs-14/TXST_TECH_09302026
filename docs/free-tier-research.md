# Free AI APIs for testing Confiance

Researched 2026-09-30 from provider documentation. Limits change without notice; anything not confirmed on a
provider page is marked *unverified*.

## Verdict: Google Gemini is the best free option to test with

| | Gemini (Google AI Studio) | Groq | OpenRouter `:free` models | Ollama (local) |
|---|---|---|---|---|
| Cost | Free tier, no card | Free tier, no card | Free, needs account | Free, uses your hardware |
| OpenAI-compatible | Yes: `https://generativelanguage.googleapis.com/v1beta/openai/` | Yes | Yes | Yes |
| Structured JSON output | **Native** (`response_format` with a JSON Schema) | JSON mode, model dependent | Model dependent | Unreliable on small models (what we saw) |
| Tool calling + streaming | Yes | Yes | Model dependent | Yes |
| Free-tier limits | **Not published in docs.** Shown per project in your AI Studio dashboard. | Per model, in account settings | 20 requests/min and 50/day (1,000/day after $10 lifetime credit) | none |
| Data use | Free tier: **content may be used to improve Google products** | Check terms *(unverified)* | Varies by model | Stays on your machine |

Why not the others: OpenRouter's 50 requests a day is far below what one Confiance run needs. Groq is a good
second choice (very fast, OpenAI-compatible) but its free per-minute token limits are tight for long tool
loops. Ollama is free and private but small local models were unreliable at JSON.

Gemini models on the free tier (from the pricing page): the Flash and Flash-Lite lines (3.8 / 3.7 / 3.6 /
3.5 Flash, 3.5 and 3.1 Flash-Lite, and the older 2.5 series). **Pro models are not on the free tier.** Google
notes the 2.5 series now has access restrictions and recommends the 3.x models.

## Being strategic about the limits

Real runs make a lot of small calls (pretend customers x questions x tries x search steps), and a free daily
allowance is small, so Confiance treats calls as a budget:

1. **Two model roles.** A *main* model (newest Flash) is used sparingly for the optimizer. A *fast* model (newest
   Flash-Lite) handles the high-volume work: knowledge-base extraction, pretend customers, question suggestions, and the
   simulated assistant that gets tested. The app pre-selects both from your model list.
2. **Run size is a visible choice.** Quick / Standard / Thorough, each with an estimated number of AI
   requests, plus the requests used in the last 24 hours. Quick is the default. For a business with 6 questions,
   a Quick round is roughly 90 requests instead of several hundred.
3. **Adaptive speed (parallel, but safe).** Requests run several at once, but the safe number is unknown, so
   Confiance behaves like a network connection: it starts gently (half the ceiling), speeds up by one after every
   8 successes, and at the first "too many requests" reply halves what runs at once and learns a per-minute
   limit of its own, creeping back up if things stay calm. The configured values are *ceilings*
   (`CONFIANCE_LLM_MAX_CONCURRENCY`, `CONFIANCE_LLM_RPM`; Gemini's preset is 4 at once, up to 15 a minute). A
   local model on one GPU gains nothing from more parallelism, so its ceiling is 2.
4. **Smart retries.** A per-minute limit waits (honouring `Retry-After`) and retries. A *daily* quota error stops
   at once with a plain message instead of hammering the service.
5. **Fewer conversations.** After the optimizer proposes changes, only the questions those changes are meant to
   help are asked again; the others can't be affected. The before/after numbers cover the same questions.
6. **Extras are off by default.** The optional AI judge (one extra call per answer) is off; the deterministic
   scoring stays on.
7. **Thinking is never turned down.** Models think at their own default depth. Token limits are generous
   (12k to 16k) because thinking tokens count against the output limit.
8. **Unfinished work is kept.** A run that hits a limit stops at that stage and resumes there later; earlier
   stages are not repeated.

## Unverified / needs a live check with a real key

- The exact free limits for your project (read them at aistudio.google.com/rate-limit).
- How Gemini's OpenAI-compatible endpoint returns "thought signatures" for tool calls in multi-turn tool use.
  Confiance echoes back any extra fields on tool calls, which is the expected mechanism, but this is untested.
- The exact error body for a 429. Confiance classifies by content (`quota_exceeded`, "daily", "per minute").

## Sources

- Gemini API pricing (free tier availability): https://ai.google.dev/gemini-api/docs/pricing
- Gemini rate limits: https://ai.google.dev/gemini-api/docs/rate-limits
- Gemini OpenAI compatibility: https://ai.google.dev/gemini-api/docs/openai
- Gemini structured output: https://ai.google.dev/gemini-api/docs/structured-output
- Gemini API errors: https://ai.google.dev/gemini-api/docs/api-errors
- Free-tier comparison (third party): https://benchlm.ai/md/free-tier.md
