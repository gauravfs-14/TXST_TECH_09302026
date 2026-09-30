"""Connection settings entered through the web app. Stored in a local file readable only by the owner,
applied to the process environment, and secrets are never returned by the API."""

import json
import os
from pathlib import Path

from .config import get_settings

# name -> (environment variable, is_secret)
FIELDS: dict[str, tuple[str, bool]] = {
    "llm_base_url": ("CONFIANCE_LLM_BASE_URL", False),
    "llm_model": ("CONFIANCE_LLM_MODEL", False),
    "llm_api_key": ("CONFIANCE_LLM_API_KEY", True),
    "search_provider": ("CONFIANCE_SEARCH_PROVIDER", False),
    "search_api_key": ("CONFIANCE_TAVILY_API_KEY", True),
    "searxng_url": ("CONFIANCE_SEARXNG_URL", False),
}
LOCAL_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "[::1]", "host.docker.internal")


def _path() -> Path:
    return Path(get_settings().secrets_file)


def _load() -> dict:
    try:
        return json.loads(_path().read_text())
    except (OSError, ValueError):
        return {}


def apply() -> None:
    for name, val in _load().items():
        if name in FIELDS and val:
            os.environ[FIELDS[name][0]] = val
    reset_clients()


def save(values: dict[str, str]) -> None:
    data = _load()
    for name, val in values.items():
        if name not in FIELDS:
            continue
        if val is not None and str(val).strip():
            data[name] = str(val).strip()
        else:
            data.pop(name, None)
            os.environ.pop(FIELDS[name][0], None)
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data))
    p.chmod(0o600)
    apply()


def reset_clients() -> None:
    from . import llm
    from .config import get_settings as gs

    gs.cache_clear()
    llm.client.cache_clear()
    for mod, attr in (("engines.openai_engine", "_client"),):
        try:
            import importlib
            getattr(importlib.import_module(f"{__package__}.{mod}"), attr).cache_clear()
        except Exception:
            pass


def is_local(url: str) -> bool:
    return any(h in url for h in LOCAL_HOSTS)


def public() -> dict:
    """Everything the web app may show. Secrets appear only as 'has_...' booleans."""
    s = get_settings()
    return {"llm_base_url": s.llm_base_url, "llm_model": s.llm_model, "has_llm_key": bool(s.llm_api_key),
            "search_provider": s.search_provider, "has_search_key": bool(s.tavily_api_key),
            "searxng_url": s.searxng_url or "", "local": is_local(s.llm_base_url)}


def status() -> dict[str, bool]:
    s = get_settings()
    llm_ok = bool(s.llm_model and s.llm_base_url)
    search_ok = (s.search_provider in ("duckduckgo", "offline") or (s.search_provider == "tavily" and bool(s.tavily_api_key))
                 or (s.search_provider == "brave" and bool(s.brave_api_key)) or (s.search_provider == "searxng" and bool(s.searxng_url)))
    return {"llm": llm_ok, "search": search_ok}


def _friendly(e: Exception, base_url: str) -> str:
    msg = str(e)
    low = msg.lower()
    if "connection" in low or "connect" in low or "refused" in low or "timed out" in low:
        hint = " If this is Ollama, make sure it is running." if is_local(base_url) else " Please check the address."
        return f"We couldn't reach {base_url}.{hint}"
    if "401" in msg or "403" in msg or "invalid api key" in low or "incorrect api key" in low or "unauthorized" in low:
        return "That key was not accepted. Please check that you copied all of it."
    if "404" in msg and "model" in low:
        return "That model wasn't found. Pick one from the list."
    return "Something went wrong: " + msg[:200]


def list_models(base_url: str, api_key: str | None) -> tuple[list[str], str | None]:
    from openai import OpenAI
    try:
        c = OpenAI(base_url=base_url, api_key=api_key or "not-needed", max_retries=0, timeout=15)
        ids = sorted({m.id for m in c.models.list()})
        return ids, None
    except Exception as e:
        return [], _friendly(e, base_url)


def test_llm() -> dict:
    """Live check of the saved connection: reachable, model answers, and can it call tools?"""
    from openai import OpenAI
    s = get_settings()
    c = OpenAI(base_url=s.llm_base_url, api_key=s.llm_api_key or "not-needed", max_retries=0, timeout=180)
    try:
        r = c.chat.completions.create(model=s.llm_model, max_tokens=64, messages=[{"role": "user", "content": "Reply with the single word: ready"}])
        if not (r.choices and r.choices[0].message is not None):
            return {"ok": False, "message": "The model didn't answer."}
    except Exception as e:
        return {"ok": False, "message": _friendly(e, s.llm_base_url)}
    tools_ok = False
    try:
        t = c.chat.completions.create(
            model=s.llm_model, max_tokens=300,
            messages=[{"role": "user", "content": "Use the tool to look up the number for 'blue'. Do not answer without calling it."}],
            tools=[{"type": "function", "function": {"name": "lookup_number", "description": "Look up a number for a word",
                                                     "parameters": {"type": "object", "properties": {"word": {"type": "string"}}, "required": ["word"]}}}])
        tools_ok = bool(t.choices[0].message.tool_calls)
    except Exception:
        tools_ok = False
    if not tools_ok:
        return {"ok": True, "tools": False, "message": "It works, but this model doesn't seem able to use tools, which Confiance needs. Please pick a different model (for Ollama, look for one marked “tools”)."}
    return {"ok": True, "tools": True, "message": "Connected, and this model can do everything Confiance needs."}


def test_search() -> dict:
    from .search.providers import build_provider
    try:
        hits = build_provider().search("weather today", 2)
        return {"ok": bool(hits), "message": "Search works." if hits else "Search returned nothing. Please try again in a moment."}
    except Exception as e:
        return {"ok": False, "message": _friendly(e, "the search service")}
