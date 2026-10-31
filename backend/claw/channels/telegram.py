"""A minimal Telegram Bot API client: long polling, send, inline buttons.

No library: the Bot API is a handful of HTTPS calls, and httpx is already here.
(OpenClaw's Telegram channel uses grammY in TypeScript; this follows the same shape -
long-poll getUpdates, reply in the same chat, buttons for yes/no - in a few lines.)
"""

from __future__ import annotations

import httpx

API = "https://api.telegram.org"


class TelegramError(Exception):
    pass


class TelegramClient:
    def __init__(self, token: str, base: str = API, timeout: float = 40.0):
        if not token or ":" not in token:
            raise TelegramError("That does not look like a Telegram bot token (it has the form 123456:ABC...).")
        self._url = f"{base.rstrip('/')}/bot{token}"
        self._http = httpx.AsyncClient(timeout=timeout)

    async def _call(self, method: str, **params):
        try:
            r = await self._http.post(f"{self._url}/{method}", json=params)
        except httpx.HTTPError as exc:
            raise TelegramError(f"Telegram could not be reached: {exc.__class__.__name__}") from exc
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if not data.get("ok"):
            raise TelegramError(data.get("description") or f"Telegram answered {r.status_code}")
        return data["result"]

    async def me(self) -> dict:
        return await self._call("getMe")

    async def updates(self, offset: int, wait: int = 25) -> list[dict]:
        return await self._call("getUpdates", offset=offset, timeout=wait, allowed_updates=["message", "callback_query"])

    async def send(self, chat_id: int, text: str, buttons: list[tuple[str, str]] | None = None) -> dict:
        params = {"chat_id": chat_id, "text": text[:4000], "disable_web_page_preview": True}
        if buttons:
            params["reply_markup"] = {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in buttons]]}
        return await self._call("sendMessage", **params)

    async def answered(self, callback_id: str, text: str = "") -> None:
        await self._call("answerCallbackQuery", callback_query_id=callback_id, text=text[:180])

    async def close(self) -> None:
        await self._http.aclose()
