"""Engine adapter contract.

An engine is an AI answer surface we measure visibility on. Each adapter implements two modes:

* controlled - the model runs a ReAct loop (reason -> call tool -> observe -> ...) using *our*
  `web_search` / `fetch_page` tools. Because we execute those tools, the sandbox can serve
  candidate versions of client pages. Used for pre-deploy evaluation.
* native - the provider's own hosted search/grounding. Results can't be intercepted, so this
  measures the real world. Used for baselines, post-deploy measurement and drift canaries.

To add an engine: subclass Engine, implement the methods, and decorate with @register("name").
"""

import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ..search.sandbox import ToolSession

CONTROLLED_SYSTEM = (
    "You are a helpful AI assistant answering a user's question. Use the web_search tool to find "
    "current, specific information, and fetch_page to read promising results. Give a direct, useful "
    "answer. When you rely on a source, cite it inline with its URL. End with a 'Sources:' list of the "
    "URLs you used."
)

_URL = re.compile(r"https?://[^\s)\]>\"'<,]+")


@dataclass
class Turn:
    role: str  # user | assistant
    content: str


@dataclass
class EngineAnswer:
    text: str = ""
    citations: list[str] = field(default_factory=list)
    retrieved_urls: list[str] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)
    model_id: str = ""
    injected: bool = False
    steps: int = 0
    error: str | None = None
    latency_ms: int = 0
    raw_shape: list[str] = field(default_factory=list)  # response field names, for API drift detection


def urls_in(text: str) -> list[str]:
    seen: list[str] = []
    for u in _URL.findall(text):
        u = u.rstrip(".;:")
        if u not in seen:
            seen.append(u)
    return seen


class Engine(ABC):
    name: str = ""
    provider: str = ""

    def __init__(self, model: str, max_steps: int = 6):
        self.model = model
        self.max_steps = max_steps

    @property
    def supports_native(self) -> bool:
        """True when the provider has its own hosted search we can call (measures the real world directly)."""
        return True

    @abstractmethod
    def controlled(self, convo: list[Turn], tools: ToolSession) -> EngineAnswer: ...

    @abstractmethod
    def native(self, convo: list[Turn]) -> EngineAnswer: ...

    @abstractmethod
    def list_models(self) -> list[str]: ...

    def run(self, mode: str, convo: list[Turn], tools: ToolSession | None = None) -> EngineAnswer:
        t0 = time.monotonic()
        try:
            if mode == "controlled":
                assert tools is not None
                ans = self.controlled(convo, tools)
                ans.queries, ans.injected = list(tools.queries), tools.injected
                ans.retrieved_urls = list(dict.fromkeys(tools.retrieved))
            else:
                ans = self.native(convo)
        except Exception as e:  # recorded, never crashes a batch
            ans = EngineAnswer(error=f"{type(e).__name__}: {e}", model_id=self.model)
            if tools is not None:
                ans.queries, ans.injected = list(tools.queries), tools.injected
        ans.latency_ms = int((time.monotonic() - t0) * 1000)
        if not ans.citations and ans.text:
            ans.citations = urls_in(ans.text)
        return ans


def _run_real(self: "Engine", convo: list[Turn]) -> EngineAnswer:
    """What a real user would get today. Uses the provider's own search when it has one; otherwise the same
    tool loop as controlled mode, but against the live web (no client page is swapped out)."""
    if self.supports_native:
        return self.run("native", convo)
    from ..search.providers import build_provider
    from ..search.sandbox import Sandbox

    live = Sandbox(provider=build_provider(), client_domain="", pages={})
    return self.run("controlled", convo, live.session())


Engine.run_real = _run_real  # type: ignore[attr-defined]

_REGISTRY: dict[str, type[Engine]] = {}


def register(name: str):
    def deco(cls: type[Engine]):
        cls.name = name
        _REGISTRY[name] = cls
        return cls

    return deco


def available_engines() -> list[str]:
    return sorted(_REGISTRY)


def build_engine(name: str, model: str | None = None) -> Engine:
    from ..config import get_settings

    s = get_settings()
    if name not in _REGISTRY:
        raise ValueError(f"unknown engine {name!r}; registered: {available_engines()}")
    if name == "offline" and not s.allow_offline:
        raise RuntimeError("offline engine requires CONFIANCE_ALLOW_OFFLINE=true")
    default = s.llm_model if name == "openai" else s.engine_models.get(name, "")
    return _REGISTRY[name](model or default, s.max_engine_steps)
