"""OpenAI-compatible adapter for local servers such as llama.cpp's `llama-server` (MIT).

The same interface can later point at a cloud provider, but this app never
requires one: the default and tested path is a server on this computer.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from claw.models.base import (
    ChatMessage,
    ModelAdapter,
    ModelAuthFailed,
    ModelError,
    ModelInfo,
    ModelNotFound,
    ModelRateLimited,
    ModelResponseError,
    ModelServerUnavailable,
)


class OpenAICompatAdapter(ModelAdapter):
    provider = "openai_compatible"
    api_key: str = ""  # Claw's own engine uses a random key per launch
    vision: bool = False
    max_tokens: int = 1536  # bounds every answer so a confused model can't run forever

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
            "max_tokens": self.max_tokens,
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

    async def see(self, png: bytes, question: str) -> str:
        """Ask about a screenshot (needs a model loaded with its vision file)."""
        import base64

        if not self.vision:
            raise ModelError("This brain can't read images.", "Use a brain that reads screenshots (Settings → Claw's brain).")
        url = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": [{"type": "text", "text": question}, {"type": "image_url", "image_url": {"url": url}}]}],
            "temperature": 0.1,
            "max_tokens": 800,
            "stream": False,
        }
        data = await self._request("POST", "/v1/chat/completions", json=body, timeout=self.timeout_s)
        try:
            return str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelResponseError("The brain returned no description of the image.") from exc

    async def _request(self, method: str, path: str, *, timeout: float, json: Any = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                resp = await client.request(method, url, json=json, headers=headers)
        except httpx.ConnectError as exc:
            raise ModelServerUnavailable(
                f"Could not connect to the model server at {self.base_url}.",
                "Start it first, for example:  llama-server -m model.gguf --port 8080",
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
        if resp.status_code >= 500 and re.search(r"does not match|failed to parse|parse error|grammar", resp.text, re.I):
            # The answer came out malformed or was cut off: a bad reply, not a broken engine.
            raise ModelResponseError("The brain's answer was cut off or malformed.")
        if resp.status_code in (401, 403):
            # The provider answered: the credential is the problem, not the network.
            # The body is not repeated here because a provider may echo the key back.
            raise ModelAuthFailed(
                "The AI service refused the API key.",
                "Check the key and the address in Settings → Claw's brain.",
            )
        if resp.status_code == 429:
            raise ModelRateLimited(
                "The AI service is rate limiting this key.",
                "Wait a moment and try again, or check your plan's limits.",
            )
        if resp.status_code >= 400:
            raise ModelError(f"The model server returned an error ({resp.status_code}): {resp.text[:500]}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise ModelResponseError("The model server returned a reply that is not valid JSON.") from exc
        if not isinstance(data, dict):
            raise ModelResponseError("The model server returned an unexpected reply.")
        return data
