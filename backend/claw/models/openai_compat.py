"""OpenAI-compatible adapter for local servers such as llama.cpp's `llama-server` (MIT).

The same interface can later point at a cloud provider, but this app never
requires one: the default and tested path is a server on this computer.
"""

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


class OpenAICompatAdapter(ModelAdapter):
    provider = "openai_compatible"

    def missing_model_hint(self) -> str:
        return "Start the server with that model loaded, or pick a model the server lists."

    async def list_models(self) -> list[ModelInfo]:
        data = await self._request("GET", "/v1/models", timeout=10)
        items = data.get("data")
        if not isinstance(items, list):
            raise ModelResponseError("The model server returned an unexpected model list.")
        return [ModelInfo(name=m["id"]) for m in items if isinstance(m, dict) and isinstance(m.get("id"), str)]

    async def chat(self, messages: list[ChatMessage], json_schema: dict[str, Any] | None = None) -> str:
        self.require_model()
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [m.model_dump() for m in messages],
            "temperature": self.temperature,
            "stream": False,
        }
        if json_schema is not None:
            # llama-server: schema-constrained JSON via response_format.json_object.schema
            body["response_format"] = {"type": "json_object", "schema": json_schema}
        data = await self._request("POST", "/v1/chat/completions", json=body, timeout=self.timeout_s)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelResponseError("The model server returned a reply without message content.") from exc
        if not isinstance(content, str):
            raise ModelResponseError("The model server returned non-text content.")
        return content

    async def _request(self, method: str, path: str, *, timeout: float, json: Any = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                resp = await client.request(method, url, json=json)
        except httpx.ConnectError as exc:
            raise ModelServerUnavailable(
                f"Could not connect to the model server at {self.base_url}.",
                "Start it first, for example:  llama-server -m path\\to\\model.gguf --port 8080",
            ) from exc
        except httpx.TimeoutException as exc:
            raise ModelServerUnavailable(
                f"The model server at {self.base_url} did not answer in time.",
                "Try a smaller model or raise the timeout in Settings.",
            ) from exc
        except httpx.HTTPError as exc:
            raise ModelServerUnavailable(f"Network error talking to the model server: {exc}") from exc
        if resp.status_code == 404:
            raise ModelNotFound(f"The server does not provide the model '{self.model}'.", self.missing_model_hint())
        if resp.status_code >= 400:
            raise ModelError(f"The model server returned an error ({resp.status_code}): {resp.text[:500]}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise ModelResponseError("The model server returned a reply that is not valid JSON.") from exc
        if not isinstance(data, dict):
            raise ModelResponseError("The model server returned an unexpected reply.")
        return data
