"""Reading pages and search results.

Everything returned here comes from the web and is untrusted: callers pass it
to the model only as quoted data.
"""

from __future__ import annotations

from urllib.parse import parse_qs, quote_plus, unquote, urlparse

from claw.config import BrowserSettings
from claw.tools.base import ToolError

MAX_PAGE_CHARS = 12000
MAX_LINKS = 80

SEARCH_URLS = {
    "duckduckgo": "https://html.duckduckgo.com/html/?q={query}",
    "bing": "https://www.bing.com/search?q={query}",
}

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

_RESULTS_JS = {
    "duckduckgo": """
() => Array.from(document.querySelectorAll('.result')).map(r => {
  const a = r.querySelector('a.result__a');
  const s = r.querySelector('.result__snippet');
  return a ? { title: a.innerText.trim(), url: a.href, snippet: s ? s.innerText.trim() : '' } : null;
}).filter(Boolean)
""",
    "bing": """
() => Array.from(document.querySelectorAll('#b_results > li.b_algo')).map(r => {
  const a = r.querySelector('h2 a');
  const s = r.querySelector('.b_caption p, p');
  return a ? { title: a.innerText.trim(), url: a.href, snippet: s ? s.innerText.trim() : '' } : null;
}).filter(Boolean)
""",
}


def search_url(settings: BrowserSettings, query: str) -> str:
    template = settings.custom_search_url if settings.search_engine == "custom" else SEARCH_URLS[settings.search_engine]
    return template.replace("{query}", quote_plus(query))


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


async def read_page(page) -> dict:
    text, truncated = clean_text(await page.evaluate(_READ_JS))
    return {"url": page.url, "title": await page.title(), "text": text, "truncated": truncated}


async def page_links(page, scope: str | None = None, contains: str | None = None) -> list[dict]:
    if scope is not None and (len(scope) > 100 or any(c in scope for c in "{};")):
        raise ToolError("That page section selector is not allowed.")
    links = await page.evaluate(_LINKS_JS, scope)
    if contains:
        needle = contains.lower()
        links = [l for l in links if needle in l["text"].lower() or needle in l["url"].lower()]
    return links[:MAX_LINKS]


async def search_results(page, engine: str) -> list[dict]:
    results: list[dict] = []
    js = _RESULTS_JS.get(engine)
    if js:
        results = await page.evaluate(js)
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
