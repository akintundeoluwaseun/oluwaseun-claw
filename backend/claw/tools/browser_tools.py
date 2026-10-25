"""Browser tools. Each one validates its arguments and reports what it verified."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from pydantic import Field

from claw.agent.schemas import Capability
from claw.browser import extract
from claw.browser.history import HISTORY_SOURCES, history_path, search_history
from claw.browser.session import validate_web_url
from claw.permissions.policy import RiskLevel
from claw.tools.base import NoArgs, ToolArgs, ToolContext, ToolError, ToolRegistry, ToolResult, ToolSpec


def _remember(ctx: ToolContext, urls) -> None:
    ctx.browser.seen_urls.update(u for u in urls if u)


def _format_results(results: list[dict]) -> str:
    return "\n".join(f"[{i}] {r['title']}\n    {r['url']}\n    {r['snippet']}".rstrip() for i, r in enumerate(results, 1))


# ---------- web_search ----------
class SearchArgs(ToolArgs):
    query: str = Field(min_length=1, max_length=300)


async def web_search(args: SearchArgs, ctx: ToolContext) -> ToolResult:
    s = ctx.settings.browser
    url = extract.search_url(s, args.query)
    info = await ctx.browser.goto(url)
    page = await ctx.browser.page()
    results = await extract.search_results(page, s.search_engine)
    ctx.browser.last_results = results
    _remember(ctx, [r["url"] for r in results])
    expected_host = urlparse(url).netloc
    verified = urlparse(info["url"]).netloc == expected_host and (info["status"] or 200) < 400
    if not results:
        return ToolResult(True, f"Searched for '{args.query}' but found no results on the page.", {"results": []}, verified)
    return ToolResult(
        True,
        f"Found {len(results)} results for '{args.query}'.",
        {"results": results, "search_url": info["url"]},
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
    rows = search_history(history_path(args.source, ctx.data_dir), args.phrase, args.days)
    _remember(ctx, [r["url"] for r in rows])
    text = "\n".join(f"- {r['last_visit']}  {r['title']} — {r['url']}" for r in rows)
    return ToolResult(
        True,
        f"Found {len(rows)} history entries matching '{args.phrase}' in the last {args.days} day(s).",
        {"entries": rows, "source": args.source},
        verified=True,
        untrusted_text=text,
    )


def register_browser_tools(reg: ToolRegistry) -> None:
    B, R = Capability.BROWSER, RiskLevel.READ_ONLY
    reg.register(ToolSpec("web_search", "Search the web and list the results.", B, R, SearchArgs, web_search))
    reg.register(ToolSpec("open_url", "Open a web address in the agent's browser.", B, R, OpenUrlArgs, open_url))
    reg.register(ToolSpec("open_search_result", "Open one of the results from the last web_search by its number.", B, R, ResultArgs, open_search_result))
    reg.register(ToolSpec("read_page", "Read the main text of the current page.", B, R, NoArgs, read_page))
    reg.register(ToolSpec("extract_links", "List the links on the current page.", B, R, LinksArgs, extract_links))
    reg.register(ToolSpec("click_link", "Follow a link on the current page by its visible text.", B, R, ClickLinkArgs, click_link))
    reg.register(ToolSpec("click_button", "Click a button on the current page (may submit a form).", B, RiskLevel.EXTERNAL, ClickButtonArgs, click_button))
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
