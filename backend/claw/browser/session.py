"""A browser the agent controls through Playwright (Apache-2.0).

It always uses a dedicated profile inside the app's data folder, never the
user's everyday Chrome/Edge profile, so the agent has no access to the user's
cookies, saved passwords or sessions.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from urllib.parse import urlparse

from claw.config import BrowserSettings
from claw.logging_setup import log_event
from claw.tools.base import ToolError

log = logging.getLogger("claw.browser")

ALLOWED_SCHEMES = {"http", "https"}
PROFILE_DIRNAME = "browser-profile"

_CHANNEL_NAMES = {"msedge": "Microsoft Edge", "chrome": "Google Chrome", "chromium": "Chromium"}


def validate_web_url(url: str) -> str:
    url = url.strip()
    if len(url) > 2048:
        raise ToolError("That web address is too long.")
    parsed = urlparse(url)
    if not parsed.scheme and parsed.path and "." in parsed.path.split("/")[0]:
        url = "https://" + url
        parsed = urlparse(url)
    if parsed.scheme.lower() not in ALLOWED_SCHEMES or not parsed.netloc:
        raise ToolError(f"Only http:// and https:// web addresses can be opened (got '{url[:100]}').")
    return url


class BrowserSession:
    def __init__(self, data_dir: Path, settings_getter):
        self.profile_dir = data_dir / PROFILE_DIRNAME
        self._settings_getter = settings_getter  # callable returning current BrowserSettings
        self._pw = None
        self._context = None
        self._current = 0
        self._lock = asyncio.Lock()
        self.last_results: list[dict[str, str]] = []
        # Every address the agent actually saw in the current task. Saving a link
        # that is not in here is refused, so the model cannot invent sources.
        self.seen_urls: set[str] = set()

    def reset_task_state(self) -> None:
        self.last_results = []
        self.seen_urls = set()

    @property
    def settings(self) -> BrowserSettings:
        return self._settings_getter()

    @property
    def started(self) -> bool:
        return self._context is not None

    async def _start(self) -> None:
        from playwright.async_api import Error as PWError
        from playwright.async_api import async_playwright

        s = self.settings
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        kwargs: dict = {
            "user_data_dir": str(self.profile_dir),
            "headless": s.headless,
            "accept_downloads": False,
            "no_viewport": not s.headless,
        }
        override = os.environ.get("CLAW_BROWSER_EXECUTABLE")
        if override:
            kwargs["executable_path"] = override
        elif s.channel != "chromium":
            kwargs["channel"] = s.channel
        self._pw = await async_playwright().start()
        try:
            self._context = await self._pw.chromium.launch_persistent_context(**kwargs)
        except PWError as exc:
            await self._pw.stop()
            self._pw = None
            name = _CHANNEL_NAMES.get(s.channel, s.channel)
            text = str(exc)
            if "Executable doesn't exist" in text or "is not found" in text or "not found at" in text:
                hint = (
                    "Run `python -m playwright install chromium` in the backend folder."
                    if s.channel == "chromium"
                    else f"Install {name}, or choose another browser in Settings."
                )
                raise ToolError(f"{name} was not found on this computer. {hint}") from exc
            if "ProcessSingleton" in text or "profile" in text.lower() and "in use" in text.lower():
                raise ToolError("The agent's browser profile is already open in another window. Close it and try again.") from exc
            raise ToolError(f"The browser could not be started: {text.splitlines()[0][:300]}") from exc
        self._context.set_default_navigation_timeout(s.navigation_timeout_s * 1000)
        self._context.set_default_timeout(15000)
        if not self._context.pages:
            await self._context.new_page()
        self._current = 0
        log_event(log, "browser started", channel=s.channel, headless=s.headless, override=bool(override))

    async def ensure(self):
        if self._context is None:
            await self._start()
        return self._context

    def _pages(self):
        return [p for p in self._context.pages if not p.is_closed()] if self._context else []

    async def page(self):
        await self.ensure()
        pages = self._pages()
        if not pages:
            pages = [await self._context.new_page()]
        self._current = min(self._current, len(pages) - 1)
        return pages[self._current]

    async def goto(self, url: str) -> dict:
        from playwright.async_api import Error as PWError
        from playwright.async_api import TimeoutError as PWTimeout

        url = validate_web_url(url)
        page = await self.page()
        try:
            response = await page.goto(url, wait_until="domcontentloaded")
        except PWTimeout as exc:
            raise ToolError(f"The page took too long to load: {url}", transient=True) from exc
        except PWError as exc:
            raise ToolError(f"Could not open {url}: {str(exc).splitlines()[0][:200]}", transient=True) from exc
        status = response.status if response else None
        return {"url": page.url, "title": await page.title(), "status": status}

    async def new_tab(self, url: str | None) -> dict:
        await self.ensure()
        page = await self._context.new_page()
        self._current = self._pages().index(page)
        if url:
            return await self.goto(url)
        return {"url": page.url, "title": ""}

    async def tabs(self) -> list[dict]:
        await self.ensure()
        out = []
        for i, p in enumerate(self._pages()):
            out.append({"index": i, "url": p.url, "title": await p.title(), "active": i == self._current})
        return out

    async def switch(self, index: int) -> dict:
        pages = self._pages() if self._context else []
        if not 0 <= index < len(pages):
            raise ToolError(f"There is no tab number {index}. Open tabs: {len(pages)}.")
        self._current = index
        await pages[index].bring_to_front()
        return {"url": pages[index].url, "title": await pages[index].title()}

    async def close_tab(self, index: int) -> int:
        pages = self._pages() if self._context else []
        if not 0 <= index < len(pages):
            raise ToolError(f"There is no tab number {index}.")
        if len(pages) == 1:
            raise ToolError("The last tab cannot be closed.")
        await pages[index].close()
        self._current = max(0, min(self._current, len(self._pages()) - 1))
        return len(self._pages())

    async def close(self) -> None:
        async with self._lock:
            if self._context is not None:
                try:
                    await self._context.close()
                except Exception:  # noqa: BLE001 — closing must not fail shutdown
                    log.warning("browser close failed", exc_info=True)
                self._context = None
            if self._pw is not None:
                await self._pw.stop()
                self._pw = None
