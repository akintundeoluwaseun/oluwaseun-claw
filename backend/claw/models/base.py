"""Model adapter interface shared by every local (and future cloud) provider."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal

from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ModelInfo(BaseModel):
    name: str
    size_bytes: int | None = None
    details: dict[str, Any] = {}


class ModelStatus(BaseModel):
    server_reachable: bool
    model_available: bool
    provider: str
    base_url: str
    model: str
    message: str
    available_models: list[str] = []


class ModelError(Exception):
    """Base error carrying a user-facing message and a suggested fix."""

    def __init__(self, message: str, hint: str = ""):
        super().__init__(message)
        self.message = message
        self.hint = hint


class ModelServerUnavailable(ModelError):
    pass


class ModelNotFound(ModelError):
    pass


class ModelResponseError(ModelError):
    pass


class ModelAdapter(ABC):
    provider: str

    def __init__(self, base_url: str, model: str, timeout_s: float, temperature: float):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s
        self.temperature = temperature

    @abstractmethod
    async def list_models(self) -> list[ModelInfo]:
        """Return the models the local server can serve."""

    @abstractmethod
    async def chat(self, messages: list[ChatMessage], json_schema: dict[str, Any] | None = None) -> str:
        """Return the assistant's reply text. When a schema is given, request JSON output."""

    async def status(self) -> ModelStatus:
        base = dict(provider=self.provider, base_url=self.base_url, model=self.model)
        try:
            models = await self.list_models()
        except ModelError as exc:
            return ModelStatus(
                server_reachable=False, model_available=False, message=f"{exc.message} {exc.hint}".strip(), **base
            )
        names = [m.name for m in models]
        if not self.model:
            return ModelStatus(
                server_reachable=True,
                model_available=False,
                message="The model server is running, but no model is selected. Choose one in Settings.",
                available_models=names,
                **base,
            )
        if not _model_in(self.model, names):
            return ModelStatus(
                server_reachable=True,
                model_available=False,
                message=f"The model '{self.model}' is not installed on the server. {self.missing_model_hint()}",
                available_models=names,
                **base,
            )
        return ModelStatus(
            server_reachable=True,
            model_available=True,
            message=f"Ready: {self.model}",
            available_models=names,
            **base,
        )

    def missing_model_hint(self) -> str:
        return "Pick an installed model in Settings."

    def require_model(self) -> None:
        if not self.model:
            raise ModelNotFound("No model is selected.", "Open Settings and choose a model.")


def _model_in(name: str, available: list[str]) -> bool:
    if name in available:
        return True
    # Ollama treats "qwen2.5" and "qwen2.5:latest" as the same model.
    return f"{name}:latest" in available or name.removesuffix(":latest") in available
