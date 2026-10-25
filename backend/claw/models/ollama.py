"""Ollama adapter (https://github.com/ollama/ollama, MIT). Talks to the local HTTP API."""

from __future__ import annotations

from typing import Any

import httpx

from claw.models.base import (
    ChatMessage,
    ModelAdapter,
    ModelError,
    ModelInfo,
    ModelNotFound,
    ModelResponseError,
    ModelServerUnavailable,
)


class OllamaAdapter(ModelAdapter):
    provider = "ollama"

    def missing_model_hint(self) -> str:
        return f"Install it with:  ollama pull {self.model}"

    async def list_models(self) -> list[ModelInfo]:
        data = await self._request("GET", "/api/tags", timeout=10)
        models = data.get("models")
        if not isinstance(models, list):
            raise ModelResponseError("The Ollama server returned an unexpected model list.")
        result = []
        for m in models:
            if isinstance(m, dict) and isinstance(m.get("name"), str):
                result.append(
                    ModelInfo(name=m["name"], size_bytes=m.get("size"), details=m.get("details") or {})
                )
        return result

    async def chat(self, messages: list[ChatMessage], json_schema: dict[str, Any] | None = None) -> str:
        self.require_model()
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [m.model_dump() for m in messages],
            "stream": False,
            "options": {"temperature": self.temperature},
        }
        if json_schema is not None:
            body["format"] = json_schema
        data = await self._request("POST", "/api/chat", json=body, timeout=self.timeout_s)
        message = data.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise ModelResponseError("The Ollama server returned a reply without any message content.")
        return message["content"]

    async def _request(self, method: str, path: str, *, timeout: float, json: Any = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                resp = await client.request(method, url, json=json)
        except httpx.ConnectError as exc:
            raise ModelServerUnavailable(
                f"Could not connect to Ollama at {self.base_url}.",
                "Make sure Ollama is installed and running (start the Ollama app, or run `ollama serve`).",
            ) from exc
        except httpx.TimeoutException as exc:
            raise ModelServerUnavailable(
                f"Ollama at {self.base_url} did not answer in time.",
                "The model may still be loading or be too large for this computer. "
                "Try again, choose a smaller model, or raise the timeout in Settings.",
            ) from exc
        except httpx.HTTPError as exc:
            raise ModelServerUnavailable(f"Network error talking to Ollama: {exc}") from exc

        if resp.status_code == 404:
            raise ModelNotFound(f"Ollama does not have the model '{self.model}'.", self.missing_model_hint())
        if resp.status_code >= 400:
            detail = _error_text(resp)
            raise ModelError(f"Ollama returned an error ({resp.status_code}): {detail}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise ModelResponseError("Ollama returned a reply that is not valid JSON.") from exc
        if not isinstance(data, dict):
            raise ModelResponseError("Ollama returned an unexpected reply.")
        return data


def _error_text(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        if isinstance(data, dict) and "error" in data:
            return str(data["error"])[:500]
    except ValueError:
        pass
    return resp.text[:500] or resp.reason_phrase
