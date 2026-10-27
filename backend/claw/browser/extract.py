"""Reading pages and search results.

Everything returned here comes from the web and is untrusted: callers pass it
to the model only as quoted data.
"""

from __future__ import annotations

from urllib.parse import parse_qs, unquote, urlparse

from claw.browser import search
from claw.config import BrowserSettings
from claw.tools.base import ToolError

MAX_PAGE_CHARS = 12000
MAX_LINKS = 80

# Runs inside the page. Prefers <main>/<article>, drops scripts, nav and hidden parts.
_READ_JS = """
() => {
  const root = document.querySelector('main, article, [role=main]') || document.body;
  if (!root) return '';
  const clone = root.cloneNode(true);
  clone.querySelectorAll('script,style,noscript,template,svg,nav,footer,[hidden],[aria-hidden=true]').forEach(n => n.remove());
  return clone.innerText || clone.textContent || '';
}
"""

_LINKS_JS = """
(scope) => {
  const root = scope ? (document.querySelector(scope) || document.body) : (document.querySelector('main, [role=main]') || document.body);
  const out = [];
  const seen = new Set();
  for (const a of root.querySelectorAll('a[href]')) {
    const href = a.href;
    if (!/^https?:/i.test(href) || seen.has(href)) continue;
    const text = (a.innerText || a.getAttribute('aria-label') || a.title || '').replace(/\\s+/g, ' ').trim();
    if (!text) continue;
    seen.add(href);
    out.push({ text: text.slice(0, 200), url: href });
  }
  return out;
}
"""

def search_url(settings: BrowserSettings, query: str) -> str:
    return search.build_url(settings.search_engine, query,
                            settings.custom_search_url, settings.searxng_url)


def clean_text(text: str, limit: int = MAX_PAGE_CHARS) -> tuple[str, bool]:
    lines = [" ".join(line.split()) for line in text.splitlines()]
    joined = "\n".join(line for line in lines if line)
    truncated = len(joined) > limit
    return joined[:limit], truncated


def unwrap_redirect(url: str) -> str:
    """DuckDuckGo's HTML results wrap targets as /l/?uddg=<target>."""
    parsed = urlparse(url)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg")
        if target:
            return unquote(target[0])
    return url


async def evaluate(page, script, arg=None):
    """Run a script in the page and turn Playwright's failures into plain words.

    A navigation that failed part-way leaves the page without an execution context,
    and the next read used to surface Playwright's own wording ("Execution context
    was destroyed") as an unhandled error rather than something the user can act on.
    """
    from playwright.async_api import Error as PWError

    try:
        return await (page.evaluate(script, arg) if arg is not None else page.evaluate(script))
    except PWError as exc:
        detail = str(exc).splitlines()[0]
        if "Execution context was destroyed" in detail or "navigating" in detail.lower():
            raise ToolError("The page changed while it was being read. Open it again and retry.",
                            transient=True) from exc
        raise ToolError(f"The page could not be read: {detail[:160]}", transient=True) from exc


async def read_page(page) -> dict:
    text, truncated = clean_text(await evaluate(page, _READ_JS))
    return {"url": page.url, "title": await page.title(), "text": text, "truncated": truncated}


async def page_links(page, scope: str | None = None, contains: str | None = None) -> list[dict]:
    if scope is not None and (len(scope) > 100 or any(c in scope for c in "{};")):
        raise ToolError("That page section selector is not allowed.")
    links = await evaluate(page, _LINKS_JS, scope)
    if contains:
        needle = contains.lower()
        links = [l for l in links if needle in l["text"].lower() or needle in l["url"].lower()]
    return links[:MAX_LINKS]


async def search_results(page, engine: str) -> list[dict]:
    results: list[dict] = []
    js = search.get(engine).results_js if engine in search.PROVIDERS else ""
    if js:
        results = await evaluate(page, js)
    if not results:
        # Custom engines, or a changed results layout: fall back to the main content's links.
        host = urlparse(page.url).netloc
        for link in await page_links(page):
            if engine != "custom" and urlparse(link["url"]).netloc == host:
                continue
            results.append({"title": link["text"], "url": link["url"], "snippet": ""})
    cleaned, seen = [], set()
    for r in results:
        url = unwrap_redirect(r["url"])
        if url in seen or not url.startswith(("http://", "https://")):
            continue
        seen.add(url)
        cleaned.append({"title": r["title"][:200], "url": url, "snippet": r.get("snippet", "")[:300]})
    return cleaned[:20]
