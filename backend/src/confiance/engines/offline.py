"""Deterministic fixture engine for tests and keyless demos. It is NOT a model of any real engine:
it searches, fetches the top result and quotes it, exercising the same tool loop as real adapters."""

import re

from ..search.sandbox import ToolSession
from .base import Engine, EngineAnswer, Turn, register


@register("offline")
class OfflineEngine(Engine):
    provider = "offline"

    def controlled(self, convo: list[Turn], tools: ToolSession) -> EngineAnswer:
        question = convo[-1].content
        hits = tools.web_search(question)
        parts, cites = [], []
        for h in hits[:3]:
            page = tools.fetch_page(h["url"])
            sentence = re.split(r"(?<=[.!?])\s+", page.split("\n\n", 1)[-1])[0][:240]
            parts.append(f"{h['title']}: {sentence}")
            cites.append(h["url"])
        text = "\n".join(parts) or "I could not find relevant information."
        return EngineAnswer(text=text + "\nSources: " + " ".join(cites), citations=cites, model_id=self.model,
                            steps=len(hits) + 1, raw_shape=["text", "citations"])

    def native(self, convo: list[Turn]) -> EngineAnswer:
        return EngineAnswer(error="offline engine has no native mode", model_id=self.model)

    def list_models(self) -> list[str]:
        return [self.model]
