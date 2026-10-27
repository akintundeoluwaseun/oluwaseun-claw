"""Build the configured model adapter."""

from __future__ import annotations

from claw.config import ModelSettings
from claw.models.base import ModelAdapter
from claw.models.ollama import OllamaAdapter
from claw.models.openai_compat import OpenAICompatAdapter

_ADAPTERS: dict[str, type[ModelAdapter]] = {
    "ollama": OllamaAdapter,
    "openai_compatible": OpenAICompatAdapter,
}


def build_adapter(settings: ModelSettings) -> ModelAdapter:
    cls = _ADAPTERS[settings.provider]
    adapter = cls(
        base_url=settings.base_url,
        model=settings.model,
        timeout_s=settings.request_timeout_s,
        temperature=settings.temperature,
    )
    # The OpenAI-compatible adapter carries a key as an attribute rather than a
    # constructor argument; cloud mode is the only place a user-supplied one is used.
    if settings.api_key and hasattr(adapter, "api_key"):
        adapter.api_key = settings.api_key
    return adapter
