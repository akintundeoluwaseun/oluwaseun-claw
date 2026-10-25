"""Google Gemini over the internet, using the user's own (free) API key.

Endpoint and auth follow Google's REST docs:
  POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent
  header x-goog-api-key: <key>
Claw picks the model itself from the account's model list, preferring
Flash-Lite (the largest free daily allowance), and moves to the next model
when one hits its daily limit.

Not yet tested against Google's live service (no internet in the build
workspace): tested against a stand-in server that follows the documented format.
"""

from __future__ import annotations

import copy
import re
import time
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

GEMINI_BASE = "https://generativelanguage.googleapis.com"


def gemini_base() -> str:
    """Tests may point at a local stand-in server; nothing else may redirect the key."""
    import os
    from urllib.parse import urlparse

    override = os.environ.get("CLAW_GEMINI_BASE", "")
    if override and urlparse(override).hostname in ("127.0.0.1", "localhost"):
        return override.rstrip("/")
    return GEMINI_BASE
KEY_PAGE = "https://aistudio.google.com/apikey"
_SKIP = re.compile(r"tts|live|image|embedding|audio|transcribe|translate|robotics|computer-use|native|aqa|learnlm|gemma", re.I)


class QuotaExhausted(ModelError):
    pass


def rank_models(names: list[str]) -> list[str]:
    """Best free choice first: Flash-Lite, then Flash, then others; stable before preview; newest first."""

    def version(n: str) -> tuple:
        m = re.search(r"gemini-(\d+)(?:\.(\d+))?", n)
        return (int(m.group(1)), int(m.group(2) or 0)) if m else (0, 0)

    def score(n: str):
        family = 0 if "flash-lite" in n else 1 if "flash" in n else 2
        unstable = 1 if re.search(r"preview|exp", n) else 0
        major, minor = version(n)
        return (family, unstable, -major, -minor, n)

    usable = [n for n in names if n.startswith("gemini") and not _SKIP.search(n)]
    return sorted(usable, key=score)


def inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Replace $ref/$defs with the definitions themselves (simpler for the service)."""
    defs = schema.get("$defs", {})

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node and node["$ref"].startswith("#/$defs/"):
                return walk(copy.deepcopy(defs[node["$ref"].split("/")[-1]]))
            return {k: walk(v) for k, v in node.items() if k not in ("$defs", "title")}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(schema)


class GeminiAdapter(ModelAdapter):
    provider = "gemini"
    # Shared across adapter instances: models that hit today's free limit, with the time they did.
    _exhausted: dict[str, float] = {}
    _schema_style: str = "responseFormat"  # switches to "legacy" if the service rejects the newer form

    def __init__(self, api_key: str, model: str = "", timeout_s: float = 90, temperature: float = 0.2, base_url: str | None = None):
        super().__init__(base_url or gemini_base(), model, timeout_s, temperature)
        self.api_key = api_key

    def missing_model_hint(self) -> str:
        return "Claw picks a Google model automatically."

    async def list_models(self) -> list[ModelInfo]:
        names: list[str] = []
        page_token = ""
        for _ in range(5):
            path = "/v1beta/models?pageSize=200" + (f"&pageToken={page_token}" if page_token else "")
            data = await self._request("GET", path, timeout=20)
            for m in data.get("models", []):
                if isinstance(m, dict) and "generateContent" in (m.get("supportedGenerationMethods") or []):
                    names.append(str(m.get("name", "")).removeprefix("models/"))
            page_token = data.get("nextPageToken") or ""
            if not page_token:
                break
        return [ModelInfo(name=n) for n in rank_models(names)]

    async def pick(self) -> list[str]:
        if getattr(self, "_ranked", None) is None:
            self._ranked = [m.name for m in await self.list_models()]
        if not self._ranked:
            raise ModelNotFound("This Google AI key has no usable models.", "Create a new key at " + KEY_PAGE)
        now = time.time()
        fresh = [n for n in self._ranked if now - self._exhausted.get(n, 0) > 6 * 3600]
        return fresh or list(self._ranked)

    async def status(self):
        from claw.models.base import ModelStatus

        try:
            order = await self.pick()
        except ModelError as exc:
            return ModelStatus(
                server_reachable=not isinstance(exc, ModelServerUnavailable), model_available=False,
                provider=self.provider, base_url=self.base_url, model="", message=f"{exc.message} {exc.hint}".strip(),
            )
        self.model = self.model or order[0]
        return ModelStatus(
            server_reachable=True, model_available=True, provider=self.provider, base_url=self.base_url,
            model=self.model, message=f"Ready: Google {self.model}", available_models=order,
        )

    async def chat(self, messages: list[ChatMessage], json_schema: dict[str, Any] | None = None) -> str:
        order = await self.pick()
        if self.model in order:  # keep using the model that worked last
            order.remove(self.model)
            order.insert(0, self.model)
        last: ModelError | None = None
        for model in order:
            try:
                text = await self._generate(model, messages, json_schema)
                self.model = model
                return text
            except QuotaExhausted as exc:
                GeminiAdapter._exhausted[model] = time.time()
                last = exc
        raise last or ModelError("No Google model could answer.")

    async def _generate(self, model: str, messages: list[ChatMessage], json_schema: dict[str, Any] | None) -> str:
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        contents: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "system":
                continue
            role = "model" if m.role == "assistant" else "user"
            if contents and contents[-1]["role"] == role:
                contents[-1]["parts"][0]["text"] += "\n\n" + m.content
            else:
                contents.append({"role": role, "parts": [{"text": m.content}]})
        if not contents:
            contents = [{"role": "user", "parts": [{"text": "Continue."}]}]
        body: dict[str, Any] = {"contents": contents, "generationConfig": {"temperature": self.temperature}}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if json_schema is not None:
            schema = inline_refs(json_schema)
            if GeminiAdapter._schema_style == "responseFormat":
                body["generationConfig"]["responseFormat"] = {"text": {"mimeType": "APPLICATION_JSON", "schema": schema}}
            else:
                body["generationConfig"]["responseMimeType"] = "application/json"
                body["generationConfig"]["responseJsonSchema"] = schema
        try:
            data = await self._request("POST", f"/v1beta/models/{model}:generateContent", json=body, timeout=self.timeout_s)
        except ModelError as exc:
            if json_schema is not None and GeminiAdapter._schema_style == "responseFormat" and "responseFormat" in exc.message:
                GeminiAdapter._schema_style = "legacy"  # older API shape; remember for next calls
                return await self._generate(model, messages, json_schema)
            raise
        candidates = data.get("candidates") or []
        if not candidates:
            reason = (data.get("promptFeedback") or {}).get("blockReason")
            raise ModelResponseError(f"Google returned no answer{f' (blocked: {reason})' if reason else ''}.")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
        if not text:
            raise ModelResponseError(f"Google returned an empty answer ({candidates[0].get('finishReason', 'unknown')}).")
        return text

    async def _request(self, method: str, path: str, *, timeout: float, json: Any = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        headers = {"x-goog-api-key": self.api_key}
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.request(method, url, json=json, headers=headers)
        except httpx.ConnectError as exc:
            raise ModelServerUnavailable("Could not reach Google AI.", "Check the internet connection.") from exc
        except httpx.TimeoutException as exc:
            raise ModelServerUnavailable("Google AI took too long to answer.", "Try again in a moment.") from exc
        except httpx.HTTPError as exc:
            raise ModelServerUnavailable(f"Network problem talking to Google AI: {type(exc).__name__}") from exc
        if resp.status_code >= 400:
            detail = _google_error(resp)
            if resp.status_code == 429:
                raise QuotaExhausted(
                    "Today's free Google AI limit has been reached.",
                    "It resets at about 8–9 AM Lagos time. You can switch Claw to the offline brain in Settings.",
                )
            if resp.status_code in (400, 401, 403) and re.search(r"api.?key|permission|unauthenticated", detail, re.I):
                raise ModelError("Google did not accept this AI key.", "Create a new free key and connect it again in Settings.")
            if resp.status_code == 404:
                raise ModelNotFound(f"Google does not offer that model to this key: {detail}")
            raise ModelError(f"Google AI returned an error ({resp.status_code}): {detail}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise ModelResponseError("Google AI sent a reply that could not be read.") from exc
        return data if isinstance(data, dict) else {}


def _google_error(resp: httpx.Response) -> str:
    try:
        err = resp.json().get("error", {})
        return str(err.get("message") or err.get("status") or resp.text)[:400]
    except (ValueError, AttributeError):
        return resp.text[:400]
