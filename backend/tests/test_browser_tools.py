"""Browser tools against a real Chromium and the local test site."""

import asyncio
import sys
from pathlib import Path

import pytest

from claw.permissions.policy import canonical_path

from claw.tools.base import ToolError
from claw.tools.registry import build_registry

REG = build_registry()


async def call(ctx, name, **args):
    spec = REG.get(name)
    return await spec.handler(spec.parse_args(args), ctx)


async def test_search_open_read(tool_ctx, site):
    r = await call(tool_ctx, "web_search", query="motion graphics templates")
    assert r.ok and r.verified
    titles = [x["title"] for x in r.data["results"]]
    assert "Free Motion Graphics Templates 2026" in titles
    assert "Jollof Rice Recipe" not in titles
    r = await call(tool_ctx, "open_search_result", number=1)
    assert r.ok and r.verified and "/articles/" in r.data["url"]
    page = await call(tool_ctx, "read_page")
    assert page.verified and "motion graphics" in page.untrusted_text.lower()
    assert "Test site footer" not in page.untrusted_text  # footer/nav stripped


async def test_search_no_results(tool_ctx):
    r = await call(tool_ctx, "web_search", query="zzzz qqqq")
    assert r.ok and r.data["results"] == []


async def test_open_url_rejects_non_web(tool_ctx):
    for bad in ["file:///etc/passwd", "javascript:alert(1)", "chrome://settings"]:
        with pytest.raises(ToolError):
            await call(tool_ctx, "open_url", url=bad)


async def test_open_url_404_reported_as_failure(tool_ctx, site):
    r = await call(tool_ctx, "open_url", url=site.base_url + "/missing")
    assert not r.ok and not r.verified and "404" in r.summary


async def test_links_and_click_link(tool_ctx, site):
    await call(tool_ctx, "open_url", url=site.base_url + "/")
    links = await call(tool_ctx, "extract_links", contains="GSAP")
    assert len(links.data["links"]) == 1
    r = await call(tool_ctx, "click_link", text="GSAP Starter Pack for Motion Graphics")
    assert r.verified and r.data["url"].endswith("/articles/gsap-starter")
    with pytest.raises(ToolError):
        await call(tool_ctx, "click_link", text="No such link here")


async def test_tabs(tool_ctx, site):
    await call(tool_ctx, "open_url", url=site.base_url + "/")
    await call(tool_ctx, "new_tab", url=site.base_url + "/contact")
    tabs = (await call(tool_ctx, "list_tabs")).data["tabs"]
    assert len(tabs) == 2 and tabs[1]["active"]
    sw = await call(tool_ctx, "switch_tab", index=0)
    assert sw.data["title"] == "Test Site Home"
    await call(tool_ctx, "close_tab", index=1)
    assert len((await call(tool_ctx, "list_tabs")).data["tabs"]) == 1
    with pytest.raises(ToolError):
        await call(tool_ctx, "close_tab", index=0)


async def test_click_button_submits_form(tool_ctx, site):
    await call(tool_ctx, "open_url", url=site.base_url + "/contact")
    r = await call(tool_ctx, "click_button", text="Send message")
    assert r.ok and not r.verified  # effect must be checked separately
    assert site.form_submissions == [{"name": ["Test"]}]
    assert "Message sent" in (await call(tool_ctx, "read_page")).untrusted_text


async def test_save_links_only_seen_urls(tool_ctx, site, tmp_path):
    await call(tool_ctx, "web_search", query="motion graphics")
    seen = tool_ctx.browser.last_results[0]
    with pytest.raises(ToolError, match="not seen"):
        await call(tool_ctx, "save_links", file_name="x", links=[{"title": "Made up", "url": "https://invented.example/x"}])
    r = await call(tool_ctx, "save_links", file_name="motion links", links=[{"title": seen["title"], "url": seen["url"]}])
    assert r.verified
    saved = tmp_path / "saved" / "motion links.md"
    assert seen["url"] in saved.read_text()
    r2 = await call(tool_ctx, "save_links", file_name="motion links", links=[{"title": seen["title"], "url": seen["url"]}])
    assert r2.data["path"].endswith("motion links (2).md")  # never overwrites


@pytest.mark.parametrize("sneaky", ["..\\..\\evil", "../../evil", "..\\..\\..\\Windows\\System32\\evil", "C:\\Windows\\evil"])
async def test_save_links_name_cannot_escape_folder(tool_ctx, tmp_path, sneaky):
    await call(tool_ctx, "web_search", query="motion graphics")
    seen = tool_ctx.browser.last_results[0]
    r = await call(tool_ctx, "save_links", file_name=sneaky, links=[{"title": "t", "url": seen["url"]}])
    written = Path(r.data["path"])
    # Compare canonical paths: save_links returns the path the policy canonicalised,
    # which on Windows is case-folded, so matching the raw spelling would fail there
    # even though the file is exactly where it should be.
    saved_root = canonical_path(tmp_path / "saved")
    assert canonical_path(written) != saved_root
    assert saved_root in canonical_path(written).parents, f"{written} escaped {saved_root}"
    assert written.is_file()
    # The separators are gone from the name itself, not merely resolved away.
    assert "/" not in written.name and "\\" not in written.name and ".." not in written.name


async def test_save_links_needs_authorized_folder(tool_ctx):
    tool_ctx.settings.permissions.authorized_folders.clear()
    await call(tool_ctx, "web_search", query="motion graphics")
    seen = tool_ctx.browser.last_results[0]
    with pytest.raises(ToolError, match="No folders"):
        await call(tool_ctx, "save_links", file_name="x", links=[{"title": "t", "url": seen["url"]}])


async def test_history_of_agent_browser(tool_ctx, site):
    """Real Chromium history: visit pages, close the browser so it flushes, then search.

    Headless Chromium writes no History database at all on Windows (measured on a
    runner: headless gave 50 profile files and no History, headful 156 with one),
    while headless on Linux does. So the browser is made visible on Windows only --
    which is also Claw's own default, so this is the shipped configuration either way.
    """
    if sys.platform == "win32":
        tool_ctx.settings.browser.headless = False
    await call(tool_ctx, "open_url", url=site.base_url + "/articles/ai-video")
    await call(tool_ctx, "open_url", url=site.base_url + "/articles/cooking")
    await tool_ctx.browser.close()
    tool_ctx.browser.reset_task_state()
    history = Path(tool_ctx.data_dir) / "browser-profile" / "Default" / "History"
    for _ in range(100):  # the write is asynchronous and slower on Windows
        if history.is_file() and history.stat().st_size:
            break
        await asyncio.sleep(0.1)
    assert history.is_file(), "Chromium never wrote its history database"
    r = await call(tool_ctx, "search_browser_history", phrase="AI video", days=1, source="claw")
    urls = [e["url"] for e in r.data["entries"]]
    assert urls == [site.base_url + "/articles/ai-video"]
    assert set(r.data["entries"][0]) == {"url", "title", "last_visit"}  # nothing else is exposed
    assert site.base_url + "/articles/ai-video" in tool_ctx.browser.seen_urls


async def test_history_chrome_only_on_windows(tool_ctx):
    import sys

    if sys.platform == "win32":
        pytest.skip("Windows path is exercised manually")
    with pytest.raises(ToolError, match="only supported on Windows"):
        await call(tool_ctx, "search_browser_history", phrase="ai", source="chrome")


def test_bad_args_rejected_before_running():
    spec = REG.get("web_search")
    with pytest.raises(ToolError):
        spec.parse_args({"query": ""})
    with pytest.raises(ToolError):
        spec.parse_args({"query": "x", "extra": 1})
    with pytest.raises(ToolError):
        spec.parse_args("not an object")


@pytest.fixture
def hanging_port():
    """A server that accepts the connection and then never answers."""
    import socket
    import threading

    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    stop = threading.Event()

    def accept_and_hang():
        held = []  # keep the sockets open so the browser keeps waiting
        while not stop.is_set():
            try:
                srv.settimeout(0.5)
                conn, _ = srv.accept()
                held.append(conn)
            except OSError:
                pass

    threading.Thread(target=accept_and_hang, daemon=True).start()
    yield srv.getsockname()[1]
    stop.set()
    srv.close()


async def test_navigation_timeout_is_reported_not_treated_as_a_visit(tool_ctx, hanging_port):
    """A page that never loads must fail readably, and must not count as opened."""
    tool_ctx.settings.browser.navigation_timeout_s = 3
    url = f"http://127.0.0.1:{hanging_port}/slow"
    with pytest.raises(ToolError) as got:
        await call(tool_ctx, "open_url", url=url)
    assert "too long to load" in str(got.value)
    assert got.value.transient  # the executor may retry a timeout
    assert url not in tool_ctx.browser.seen_urls  # never citable as a source


# ---------- what the user is told when the web is unreachable ----------
def test_network_errors_are_explained_in_plain_words():
    from claw.browser.session import explain_network_error

    assert explain_network_error("Page.goto: net::ERR_NAME_NOT_RESOLVED at https://x/") == (
        "that web address does not exist, or this computer has no internet connection (ERR_NAME_NOT_RESOLVED)")
    assert "not connected to the internet" in explain_network_error("net::ERR_INTERNET_DISCONNECTED")
    # An unrecognised failure is passed through rather than guessed at.
    assert explain_network_error("something else entirely") == "something else entirely"


async def test_an_unreachable_site_says_so_without_a_bare_error_code(tool_ctx):
    """Runs for real against a port nothing is listening on - no mock, no internet needed."""
    from claw.tools.base import ToolError
    from claw.tools.registry import build_registry

    spec = build_registry().get("open_url")
    with pytest.raises(ToolError) as caught:
        # A high port nothing listens on; Chromium refuses low ports like 9 outright.
        await spec.handler(spec.parse_args({"url": "http://127.0.0.1:49231/"}), tool_ctx)
    message = str(caught.value)
    assert "refused the connection" in message and "ERR_CONNECTION_REFUSED" in message
    assert "net::" not in message


async def test_reading_after_a_failed_navigation_gives_a_clean_message(tool_ctx, site):
    """A real failure, not a mock: the navigation below genuinely cannot complete.

    It used to leave the page with no execution context, and the next read raised
    Playwright's own "Execution context was destroyed" straight at the user.
    """
    from claw.tools.base import ToolError
    from claw.tools.registry import build_registry

    reg = build_registry()
    opener, reader = reg.get("open_url"), reg.get("read_page")
    await opener.handler(opener.parse_args({"url": site.base_url + "/articles/motion-templates"}), tool_ctx)
    with pytest.raises(ToolError):
        await opener.handler(opener.parse_args({"url": "http://127.0.0.1:49231/"}), tool_ctx)
    try:
        out = await reader.handler(reader.parse_args({}), tool_ctx)
        assert out.ok                      # the page survived: reading it is fine
    except ToolError as exc:
        assert "Execution context" not in str(exc)
        assert "Open it again" in str(exc) or "could not be read" in str(exc)


# ---------- which search engine, and the evidence for the answer ----------
def test_every_provider_builds_its_own_address():
    from claw.browser import search

    assert search.build_url("duckduckgo", "a b").endswith("?q=a+b")
    assert search.build_url("bing", "a b").startswith("https://www.bing.com/search?q=")
    assert (search.build_url("searxng", "a b", searxng_url="https://s.example.com/")
            == "https://s.example.com/search?q=a+b")
    # A host typed with /search already on the end must not become /search/search.
    assert (search.build_url("searxng", "x", searxng_url="https://s.example.com/search")
            == "https://s.example.com/search?q=x")
    assert search.build_url("custom", "x", custom_url="https://o.test/?s={query}") == "https://o.test/?s=x"
    with pytest.raises(ValueError, match=r"\{query\}"):
        search.build_url("custom", "x", custom_url="https://o.test/no-placeholder")
    with pytest.raises(KeyError):
        search.build_url("altavista", "x")


def test_a_searxng_host_is_required_when_it_is_chosen():
    from claw.config import BrowserSettings

    with pytest.raises(Exception, match="SearXNG"):
        BrowserSettings(search_engine="searxng")
    ok = BrowserSettings(search_engine="searxng", searxng_url="https://s.example.com")
    assert ok.searxng_url == "https://s.example.com"


async def test_search_records_where_the_answer_came_from(tool_ctx, site):
    """Runs a real search against a real page served locally - no mocked results."""
    from claw.tools.registry import build_registry

    tool_ctx.settings.browser.search_engine = "custom"
    tool_ctx.settings.browser.custom_search_url = site.base_url + "/search?q={query}"
    spec = build_registry().get("web_search")
    r = await spec.handler(spec.parse_args({"query": "templates"}), tool_ctx)
    assert r.data["provider"]["id"] == "custom"
    assert r.data["search_url"].startswith(site.base_url)
    assert r.data["count"] == len(r.data["results"]) >= 1
    assert r.data["took_ms"] >= 0 and r.data["fetched_at"]
    assert all(x["url"].startswith("http") for x in r.data["results"])


async def test_an_unreadable_results_page_does_not_invent_results(tool_ctx, site):
    """A layout Claw cannot read falls back to the page's own links, not to guesses."""
    from claw.browser import extract
    from claw.tools.registry import build_registry

    opener = build_registry().get("open_url")
    await opener.handler(opener.parse_args({"url": site.base_url + "/articles/motion-templates"}), tool_ctx)
    page = await tool_ctx.browser.page()
    # Bing's selectors match nothing on this page; the fallback then keeps only links
    # that leave the search host, so an article page yields nothing rather than its
    # own navigation presented as search results.
    results = await extract.search_results(page, "bing")
    assert all(r["url"].startswith("http") for r in results)
    assert not any(site.base_url in r["url"] for r in results)
