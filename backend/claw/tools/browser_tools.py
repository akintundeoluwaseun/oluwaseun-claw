"""Browser tools. Each one validates its arguments and reports what it verified."""

from __future__ import annotations

import re
from pathlib import Path
import time
from datetime import datetime
from urllib.parse import urlparse

from pydantic import Field

from claw.agent.schemas import Capability
from claw.browser import ddg_html, extract
import httpx
import sys

from claw.browser.history import HISTORY_SOURCES, history_path, search_history
from claw.browser.session import validate_web_url
from claw.permissions.policy import RiskLevel
from claw.tools.base import NoArgs, ToolArgs, ToolContext, ToolError, ToolRegistry, ToolResult, ToolSpec, escalate_by_label


def _remember(ctx: ToolContext, urls) -> None:
    ctx.browser.seen_urls.update(u for u in urls if u)


def _format_results(results: list[dict]) -> str:
    return "\n".join(f"[{i}] {r['title']}\n    {r['url']}\n    {r['snippet']}".rstrip() for i, r in enumerate(results, 1))


# ---------- web_search ----------
class SearchArgs(ToolArgs):
    query: str = Field(min_length=1, max_length=300)


async def web_search(args: SearchArgs, ctx: ToolContext) -> ToolResult:
    s = ctx.settings.browser
    provider = extract.search.describe(s.search_engine, s.custom_search_url, s.searxng_url)
    url = extract.search_url(s, args.query)
    started = time.monotonic()
    info = await ctx.browser.goto(url)
    page = await ctx.browser.page()
    results = await extract.search_results(page, s.search_engine)
    fallback_note = ""
    if not results and s.search_engine == "duckduckgo":
        # The browser's page gave nothing (seen on Windows); DuckDuckGo's HTML results
        # page usually does. Approach ported from OpenClaw; see browser/ddg_html.py.
        try:
            results = await ddg_html.search(args.query)
            fallback_note = " (read from DuckDuckGo's plain results page)"
        except (ddg_html.SearchChallenge, httpx.HTTPError) as exc:
            fallback_note = f" The plain results page did not help either: {exc}"
    took_ms = round((time.monotonic() - started) * 1000)
    ctx.browser.last_results = results
    _remember(ctx, [r["url"] for r in results])
    expected_host = urlparse(url).netloc
    verified = urlparse(info["url"]).netloc == expected_host and (info["status"] or 200) < 400
    # Where the answer came from, from which page, and when. Without this a result
    # is just text, and a stale answer looks exactly like a fresh one.
    evidence = {
        "provider": provider, "search_url": info["url"], "page_title": info.get("title", ""),
        "status": info.get("status"), "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "took_ms": took_ms, "count": len(results),
    }
    if not results:
        return ToolResult(
            True,
            f"Searched {provider['name']} for '{args.query}' and the page loaded, "
            f"but no results could be read from it.{fallback_note}",
            {"results": [], **evidence}, verified,
        )
    return ToolResult(
        True,
        f"Found {len(results)} result(s) for '{args.query}' on {provider['name']} ({took_ms} ms){fallback_note}.",
        {"results": results, **evidence},
        verified,
        untrusted_text=_format_results(results),
    )


# ---------- open_url ----------
class OpenUrlArgs(ToolArgs):
    url: str = Field(min_length=4, max_length=2048)


async def open_url(args: OpenUrlArgs, ctx: ToolContext) -> ToolResult:
    target = validate_web_url(args.url)
    info = await ctx.browser.goto(target)
    _remember(ctx, [info["url"], target])
    ok_status = info["status"] is None or info["status"] < 400
    return ToolResult(
        ok_status,
        f"Opened {info['title'] or info['url']}" + ("" if ok_status else f" (server answered {info['status']})"),
        info,
        verified=ok_status and info["url"].startswith(("http://", "https://")),
    )


# ---------- open_search_result ----------
class ResultArgs(ToolArgs):
    number: int = Field(ge=1, le=20, description="Result number from the last web_search, starting at 1")


async def open_search_result(args: ResultArgs, ctx: ToolContext) -> ToolResult:
    results = ctx.browser.last_results
    if not results:
        raise ToolError("There are no search results yet. Use web_search first.")
    if args.number > len(results):
        raise ToolError(f"There are only {len(results)} results.")
    chosen = results[args.number - 1]
    info = await ctx.browser.goto(chosen["url"])
    _remember(ctx, [info["url"]])
    ok_status = info["status"] is None or info["status"] < 400
    return ToolResult(ok_status, f"Opened result {args.number}: {info['title'] or info['url']}", info, verified=ok_status)


# ---------- read_page ----------
async def read_page(args: NoArgs, ctx: ToolContext) -> ToolResult:
    page = await ctx.browser.page()
    if page.url in ("about:blank", ""):
        raise ToolError("No page is open. Open a web address or search first.")
    content = await extract.read_page(page)
    _remember(ctx, [content["url"]])
    words = len(content["text"].split())
    note = " (cut to the first part)" if content["truncated"] else ""
    return ToolResult(
        True,
        f"Read '{content['title'] or content['url']}' — about {words} words{note}.",
        {"url": content["url"], "title": content["title"], "words": words, "truncated": content["truncated"]},
        verified=words > 0,
        untrusted_text=content["text"],
    )


# ---------- extract_links ----------
class LinksArgs(ToolArgs):
    contains: str | None = Field(default=None, max_length=100, description="Only links whose text or address contains this")


async def extract_links(args: LinksArgs, ctx: ToolContext) -> ToolResult:
    page = await ctx.browser.page()
    links = await extract.page_links(page, contains=args.contains)
    _remember(ctx, [l["url"] for l in links])
    text = "\n".join(f"- {l['text']} — {l['url']}" for l in links)
    return ToolResult(True, f"Found {len(links)} links on the page.", {"links": links}, verified=True, untrusted_text=text)


# ---------- click_link ----------
class ClickLinkArgs(ToolArgs):
    text: str = Field(min_length=1, max_length=200, description="Visible text of the link")


async def click_link(args: ClickLinkArgs, ctx: ToolContext) -> ToolResult:
    page = await ctx.browser.page()
    links = await extract.page_links(page, scope="body")
    needle = args.text.lower()
    exact = [l for l in links if l["text"].lower() == needle]
    partial = [l for l in links if needle in l["text"].lower()]
    match = (exact or partial or [None])[0]
    if match is None:
        raise ToolError(f"No link with the text '{args.text}' was found on this page.")
    before = page.url
    # Following a link is a plain page load (GET), so it is treated as read-only.
    info = await ctx.browser.goto(match["url"])
    _remember(ctx, [info["url"]])
    return ToolResult(True, f"Followed '{match['text']}' to {info['title'] or info['url']}", info, verified=info["url"] != before)


# ---------- click_button ----------
class ClickButtonArgs(ToolArgs):
    text: str = Field(min_length=1, max_length=200, description="Visible label of the button")


async def click_button(args: ClickButtonArgs, ctx: ToolContext) -> ToolResult:
    from playwright.async_api import Error as PWError

    page = await ctx.browser.page()
    locator = page.get_by_role("button", name=re.compile(re.escape(args.text), re.I))
    count = await locator.count()
    if count == 0:
        raise ToolError(f"No button labelled '{args.text}' was found on this page.")
    if count > 1:
        raise ToolError(f"{count} buttons match '{args.text}'. Use the exact label.")
    before = page.url
    try:
        await locator.click(timeout=10000)
        await page.wait_for_load_state("domcontentloaded", timeout=10000)
    except PWError as exc:
        raise ToolError(f"The button could not be clicked: {str(exc).splitlines()[0][:200]}", transient=True) from exc
    after = page.url
    return ToolResult(
        True,
        f"Clicked '{args.text}'." + (f" The page changed to {after}." if after != before else " The page address did not change."),
        {"url_before": before, "url_after": after},
        verified=False,  # whether the click achieved its purpose must be checked by reading the page
    )


# ---------- tabs ----------
async def list_tabs(args: NoArgs, ctx: ToolContext) -> ToolResult:
    tabs = await ctx.browser.tabs()
    text = "\n".join(f"[{t['index']}] {'* ' if t['active'] else ''}{t['title']} — {t['url']}" for t in tabs)
    return ToolResult(True, f"{len(tabs)} tab(s) open.", {"tabs": tabs}, verified=True, untrusted_text=text)


class NewTabArgs(ToolArgs):
    url: str | None = Field(default=None, max_length=2048)


async def new_tab(args: NewTabArgs, ctx: ToolContext) -> ToolResult:
    info = await ctx.browser.new_tab(args.url)
    if args.url:
        _remember(ctx, [info["url"]])
    return ToolResult(True, f"Opened a new tab{(' at ' + info['url']) if args.url else ''}.", info, verified=True)


class TabArgs(ToolArgs):
    index: int = Field(ge=0, le=50)


async def switch_tab(args: TabArgs, ctx: ToolContext) -> ToolResult:
    info = await ctx.browser.switch(args.index)
    return ToolResult(True, f"Switched to tab {args.index}: {info['title'] or info['url']}", info, verified=True)


async def close_tab(args: TabArgs, ctx: ToolContext) -> ToolResult:
    remaining = await ctx.browser.close_tab(args.index)
    return ToolResult(True, f"Closed tab {args.index}; {remaining} tab(s) left.", {"remaining": remaining}, verified=True)


# ---------- search_history ----------
class HistoryArgs(ToolArgs):
    phrase: str = Field(min_length=2, max_length=100, description="Words to look for in page titles or addresses")
    days: int = Field(default=7, ge=1, le=90, description="How many days back to look")
    source: str = Field(default="edge", description="Which browser: edge, chrome, or claw (the agent's own browser)")


async def search_browser_history(args: HistoryArgs, ctx: ToolContext) -> ToolResult:
    if args.source not in HISTORY_SOURCES:
        raise ToolError(f"Unknown browser '{args.source}'. Use one of: {', '.join(HISTORY_SOURCES)}.")
    try:
        rows = search_history(history_path(args.source, ctx.data_dir), args.phrase, args.days)
    except ToolError:
        # Chromium keeps no history database in headless mode on Windows, so Claw's own
        # history is genuinely absent there rather than merely unread. Say which it is.
        if args.source == "claw" and ctx.settings.browser.headless and sys.platform == "win32":
            raise ToolError(
                "Claw keeps no browsing history while the browser is hidden on Windows.",
            ) from None
        raise
    _remember(ctx, [r["url"] for r in rows])
    text = "\n".join(f"- {r['last_visit']}  {r['title']} — {r['url']}" for r in rows)
    return ToolResult(
        True,
        f"Found {len(rows)} history entries matching '{args.phrase}' in the last {args.days} day(s).",
        {"entries": rows, "source": args.source},
        verified=True,
        untrusted_text=text,
    )


# ---------- fill_field ----------
# Claw never types secrets into web pages: passwords, card numbers, PINs and one-time codes are
# for the user to enter themselves.
_SECRET_AUTOCOMPLETE = re.compile(r"password|cc-|one-time-code|card", re.I)
_SECRET_LABEL = re.compile(r"password|passcode|\bpin\b|card number|cvv|cvc|security code|one[- ]time|otp", re.I)


class FillArgs(ToolArgs):
    field: str = Field(min_length=1, max_length=200, description="The field's visible label, placeholder or name")
    value: str = Field(max_length=5000, description="Text to enter; for a dropdown the option to choose; for a checkbox 'yes' or 'no'")


async def _find_field(page, label: str):
    for loc in (page.get_by_label(label, exact=False), page.get_by_placeholder(label, exact=False),
                page.locator(f'[name="{label}" i]'), page.get_by_role("textbox", name=re.compile(re.escape(label), re.I))):
        try:
            if await loc.count() == 1:
                return loc
            if await loc.count() > 1:
                raise ToolError(f"{await loc.count()} fields match '{label}'. Use the field's full label.")
        except ToolError:
            raise
        except Exception:  # noqa: BLE001 — a selector form that this page can't evaluate
            continue
    raise ToolError(f"No form field labelled '{label}' was found on this page.")


async def fill_field(args: FillArgs, ctx: ToolContext) -> ToolResult:
    from playwright.async_api import Error as PWError

    page = await ctx.browser.page()
    loc = await _find_field(page, args.field)
    info = await loc.evaluate(
        "el => ({tag: el.tagName.toLowerCase(), type: (el.type || '').toLowerCase(), "
        "ac: el.autocomplete || '', name: el.name || '', disabled: !!el.disabled, readonly: !!el.readOnly})"
    )
    if info["type"] == "password" or _SECRET_AUTOCOMPLETE.search(info["ac"]) or _SECRET_LABEL.search(args.field + " " + info["name"]):
        raise ToolError("That is a password, card or code field. Claw never types those; please enter it yourself.")
    if info["type"] == "file":
        raise ToolError("Claw does not upload files to websites.")
    if info["disabled"] or info["readonly"]:
        raise ToolError(f"The field '{args.field}' can't be changed right now.")
    try:
        if info["tag"] == "select":
            await loc.select_option(label=args.value)
            got = await loc.evaluate("el => el.options[el.selectedIndex] ? el.options[el.selectedIndex].text : ''")
            ok = got.strip().lower() == args.value.strip().lower()
        elif info["type"] in ("checkbox", "radio"):
            want = args.value.strip().lower() in ("yes", "true", "on", "1", "check", "checked")
            await (loc.check() if want else loc.uncheck())
            ok = await loc.is_checked() == want
            got = "checked" if want else "unchecked"
        else:
            await loc.fill(args.value)
            got = await loc.input_value()
            ok = got == args.value
    except PWError as exc:
        raise ToolError(f"The field could not be filled: {str(exc).splitlines()[0][:200]}") from exc
    return ToolResult(True, f"Filled '{args.field}'" + (" and checked the value is there." if ok else ", but the page shows a different value."),
                      {"field": args.field, "kind": info["tag"] if info["tag"] == "select" else info["type"] or info["tag"]},
                      verified=ok)


# ---------- download_file ----------
# Programs and scripts are never downloaded: they could run on the computer.
BLOCKED_DOWNLOADS = {".exe", ".msi", ".bat", ".cmd", ".com", ".scr", ".ps1", ".vbs", ".vbe", ".js", ".jse", ".wsf",
                     ".hta", ".jar", ".lnk", ".reg", ".dll", ".sys", ".cpl", ".msc", ".appx", ".msix", ".iso", ".img"}
MAX_DOWNLOAD_BYTES = 500 * 1024**2


class DownloadArgs(ToolArgs):
    link_text: str | None = Field(default=None, max_length=200, description="Visible text of the download link on the current page")
    url: str | None = Field(default=None, max_length=2048, description="Or the file's address")
    folder: str | None = Field(default=None, max_length=500, description="Authorized folder to save into; default the first one")


def check_download(args: DownloadArgs, ctx: ToolContext) -> None:
    from claw.tools.file_tools import resolve_folder

    if not (args.link_text or args.url):
        raise ToolError("Say which link to download (its text) or give the file's address.")
    if args.url:
        validate_web_url(args.url)
        if Path(urlparse(args.url).path).suffix.lower() in BLOCKED_DOWNLOADS:
            raise ToolError("Claw does not download programs or scripts.")
    resolve_folder(ctx, args.folder)


async def download_file(args: DownloadArgs, ctx: ToolContext) -> ToolResult:
    from playwright.async_api import Error as PWError
    from playwright.async_api import TimeoutError as PWTimeout

    from claw.tools.file_tools import resolve_folder, safe_file_name, unique_path

    check_download(args, ctx)
    folder = resolve_folder(ctx, args.folder)
    page = await ctx.browser.page()
    try:
        async with page.expect_download(timeout=60000) as dl_info:
            if args.url:
                url = validate_web_url(args.url)
                # Navigating to a file that downloads raises "Download is starting"; that is expected.
                try:
                    await page.goto(url)
                except PWError as exc:
                    if "download is starting" not in str(exc).lower():
                        raise
            else:
                links = await extract.page_links(page, scope="body")
                needle = args.link_text.lower()
                match = next((l for l in links if l["text"].lower() == needle), None) or next(
                    (l for l in links if needle in l["text"].lower()), None)
                if match is None:
                    raise ToolError(f"No link with the text '{args.link_text}' was found on this page.")
                if Path(urlparse(match["url"]).path).suffix.lower() in BLOCKED_DOWNLOADS:
                    raise ToolError("Claw does not download programs or scripts.")
                await page.get_by_role("link", name=re.compile(re.escape(match["text"]), re.I)).first.click()
        download = await dl_info.value
    except PWTimeout as exc:
        raise ToolError("No download started within 60 seconds. The link may open a page instead of a file.", transient=True) from exc
    except PWError as exc:
        raise ToolError(f"The download failed: {str(exc).splitlines()[0][:200]}", transient=True) from exc
    name = download.suggested_filename or "download"
    ext = Path(name).suffix.lower()
    if ext in BLOCKED_DOWNLOADS:
        await download.cancel()
        raise ToolError(f"The site sent a program or script ({name}). Claw did not save it.")
    failure = await download.failure()
    if failure:
        raise ToolError(f"The download did not finish: {failure}", transient=True)
    tmp = Path(await download.path())
    size = tmp.stat().st_size
    if size > MAX_DOWNLOAD_BYTES:
        raise ToolError(f"The file is {size / 1024**2:.0f} MB; Claw downloads at most 500 MB.")
    target = unique_path(folder / safe_file_name(Path(name).stem, ext or ".bin"))
    ctx.policy.check_path(target, write=True)
    await download.save_as(target)
    ok = target.is_file() and target.stat().st_size == size and size > 0
    _remember(ctx, [download.url])
    ctx.memory.outputs.append({"path": str(target), "kind": "download", "verified": ok,
                               "note": "" if ok else "The saved file size does not match the download."})
    return ToolResult(ok, f"Downloaded {name} ({size:,} bytes) to {target}." if ok else f"Saved {target}, but it looks incomplete.",
                      {"path": str(target), "bytes": size, "from": download.url}, verified=ok)


def register_browser_tools(reg: ToolRegistry) -> None:
    B, R = Capability.BROWSER, RiskLevel.READ_ONLY
    reg.register(ToolSpec("web_search", "Search the web and list the results.", B, R, SearchArgs, web_search))
    reg.register(ToolSpec("open_url", "Open a web address in the agent's browser.", B, R, OpenUrlArgs, open_url))
    reg.register(ToolSpec("open_search_result", "Open one of the results from the last web_search by its number.", B, R, ResultArgs, open_search_result))
    reg.register(ToolSpec("read_page", "Read the main text of the current page.", B, R, NoArgs, read_page))
    reg.register(ToolSpec("extract_links", "List the links on the current page.", B, R, LinksArgs, extract_links))
    reg.register(ToolSpec("click_link", "Follow a link on the current page by its visible text.", B, R, ClickLinkArgs, click_link))
    reg.register(
        ToolSpec(
            "click_button", "Click a button on the current page (may submit a form).", B, RiskLevel.EXTERNAL,
            ClickButtonArgs, click_button, risk_for=lambda a, c: escalate_by_label(a.text, RiskLevel.EXTERNAL),
        )
    )
    reg.register(ToolSpec("fill_field", "Type into a form field (or choose a dropdown option / tick a box) on the current page. "
                          "Does not submit; never for passwords, cards or codes.", B, RiskLevel.LOCAL_WRITE, FillArgs, fill_field))
    reg.register(ToolSpec("download_file", "Download a file from a link on the current page (or an address) into an authorized folder. "
                          "Programs and scripts are refused.", B, RiskLevel.LOCAL_WRITE, DownloadArgs, download_file,
                          precheck=check_download))
    reg.register(ToolSpec("list_tabs", "List open browser tabs.", B, R, NoArgs, list_tabs))
    reg.register(ToolSpec("new_tab", "Open a new browser tab, optionally at an address.", B, R, NewTabArgs, new_tab))
    reg.register(ToolSpec("switch_tab", "Switch to a browser tab by its index from list_tabs.", B, R, TabArgs, switch_tab))
    reg.register(ToolSpec("close_tab", "Close a browser tab by its index.", B, R, TabArgs, close_tab))
    reg.register(
        ToolSpec(
            "search_browser_history",
            "Search the user's browsing history (titles and addresses only). Needs the user's permission.",
            B, R, HistoryArgs, search_browser_history, sensitive_scope="browser_history",
        )
    )
