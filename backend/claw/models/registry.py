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
    return cls(
        base_url=settings.base_url,
        model=settings.model,
        timeout_s=settings.request_timeout_s,
        temperature=settings.temperature,
    )
