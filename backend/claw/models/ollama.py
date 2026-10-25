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
    # Set by the model manager: leave processor cores free, and don't hold memory forever.
    num_thread: int | None = None
    keep_alive: str | None = None

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
        if self.num_thread:
            body["options"]["num_thread"] = self.num_thread
        if self.keep_alive is not None:
            body["keep_alive"] = self.keep_alive
        if json_schema is not None:
            body["format"] = json_schema
        data = await self._request("POST", "/api/chat", json=body, timeout=self.timeout_s)
        message = data.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise ModelResponseError("The Ollama server returned a reply without any message content.")
        return message["content"]

    async def see(self, png: bytes, question: str) -> str:
        """Ask a vision model (e.g. qwen2.5vl) about a screenshot."""
        import base64

        self.require_model()
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": question, "images": [base64.b64encode(png).decode("ascii")]}],
            "stream": False,
            "options": {"temperature": 0.1, **({"num_thread": self.num_thread} if self.num_thread else {})},
        }
        if self.keep_alive is not None:
            body["keep_alive"] = self.keep_alive
        data = await self._request("POST", "/api/chat", json=body, timeout=self.timeout_s)
        message = data.get("message") or {}
        if not isinstance(message.get("content"), str) or not message["content"]:
            raise ModelResponseError("The seeing model returned no description.")
        return message["content"]

    async def pull(self):
        """Download the model, yielding Ollama's progress objects."""
        import json as _json

        url = f"{self.base_url}/api/pull"
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=600), trust_env=False) as client:
                async with client.stream("POST", url, json={"model": self.model, "stream": True}) as resp:
                    if resp.status_code >= 400:
                        await resp.aread()
                        raise ModelError(f"Ollama could not download {self.model}: {_error_text(resp)}")
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            item = _json.loads(line)
                        except ValueError:
                            continue
                        if "error" in item:
                            raise ModelError(f"Ollama could not download {self.model}: {item['error']}")
                        yield item
        except httpx.ConnectError as exc:
            raise ModelServerUnavailable(f"Could not connect to Ollama at {self.base_url}.") from exc
        except httpx.TimeoutException as exc:
            raise ModelError("The download stalled. Claw will try again.") from exc
        except httpx.HTTPError as exc:
            raise ModelError(f"Download interrupted: {exc}") from exc

    async def unload(self) -> None:
        """Release the model's memory now (Ollama: empty chat with keep_alive 0)."""
        await self._request("POST", "/api/chat", json={"model": self.model, "messages": [], "keep_alive": 0}, timeout=15)

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
