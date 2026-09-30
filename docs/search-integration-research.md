# Built-in (integrated) search vs. external search

Researched 2026-09-29 from the providers' own documentation (links at the bottom). Anything I could not
confirm from a documentation page is marked *unverified*.

## What each provider offers

| | OpenAI | Anthropic (Claude) | Ollama / other OpenAI-compatible servers |
|---|---|---|---|
| Built-in search | Yes: `web_search` tool in the **Responses API**. Chat Completions only through special search-only models with fewer controls. | Yes: server-side `web_search` tool in the Messages API (versions `web_search_20250305`, `_20260209` adds dynamic filtering, `_20260318` adds `response_inclusion`). | **No.** Ollama has a separate hosted Web Search API (`POST ollama.com/api/web_search`, needs a free account key, max 10 results). Other compatible servers (LM Studio, vLLM, OpenRouter, Groq) have none. |
| Who runs the search | OpenAI, inside the request. | Anthropic, inside the request. | n/a: you supply a tool. |
| What you get back | A `web_search_call` item (action: search / open page / find in page, and the queries) plus the answer with `url_citation` annotations (url, title, character span). Full source list and raw results can be requested with `include`. | `server_tool_use` (the query), `web_search_tool_result` (url, title, page age, **`encrypted_content`**), and answer text with citations (url, title, up to 150 chars of cited text). | Whatever your own tool returns. |
| Can you read the result text? | Yes, via `include`. | **No.** The page content is encrypted; it must be sent back untouched or the next request fails with a 400. | Yes (you wrote the tool). |
| Can you change what the model sees? | **No.** | **No.** | **Yes.** It is your tool. |
| Controls | Allowed/blocked domains (up to 100), user location, search context size (low/medium/high), cached-only mode. | `max_uses`, allowed *or* blocked domains (not both), user location. | Up to you. |
| Cost | Per tool call, on top of tokens (rate not confirmed in the page I read). | **$10 per 1,000 searches** plus tokens (search results count as input tokens). Errors are not billed. | Free for local models. Ollama's search API has a free tier (limits not documented). |
| Not available on | | Amazon Bedrock. Dynamic-filtering versions are limited on Google Cloud / Azure-hosted Foundry. | |

Ollama's OpenAI-compatible endpoint supports Chat Completions with tools and streaming, JSON mode through
`response_format`, and a stateless Responses API. `tool_choice` is **not** supported and the API key is ignored
locally (base URL `http://localhost:11434/v1`).

## What this means for Confiance

1. **Integrated search cannot be used for the "modified page" experiment.** In both OpenAI and Claude the
   search runs on the provider's side. We can neither alter the results nor (for Claude) even read them. The
   counterfactual sandbox therefore *has to* use search as a tool we execute ourselves. That is why
   controlled mode uses an external search provider.
2. **Integrated search is exactly right for measuring the real world.** It is what a real user of that
   assistant gets. Confiance uses it for the before/after live measurement and drift checks whenever the
   provider has one (real OpenAI today).
3. **Providers without built-in search (Ollama and friends) get the same treatment through our tools.** For
   those, "real world" measurement runs the same tool loop against the live web, with none of our snapshots
   swapped in. This is implemented (`Engine.run_real`).
4. **Cost.** For paid APIs integrated search is a per-search fee; for testing, a local model plus free
   DuckDuckGo search costs nothing.

## What was built from this

- One **OpenAI-compatible** connection (base URL, optional key, model) drives the internal agents *and* the assistant
  under test. It uses Chat Completions because every compatible server supports it. JSON output degrades
  gracefully (json_schema, then json_object, then tolerant parsing with one repair retry).
- Native mode (Responses API + `web_search`) switches on automatically only for `api.openai.com`.
- Free keyless search (DuckDuckGo) is the default; Tavily, Brave and self-hosted SearXNG are also supported.
- The Claude and Gemini adapters are still in the code, but are not exposed in the app for now.

## Sources

- OpenAI, Web search guide: https://developers.openai.com/api/docs/guides/tools-web-search
- Anthropic, Web search tool: https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool
- Ollama, OpenAI compatibility: https://docs.ollama.com/api/openai-compatibility
- Ollama, Web search: https://docs.ollama.com/capabilities/web-search
- *Unverified:* the OpenAI page summary named specific current model IDs; I did not rely on them.
