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
#: The page's readable text, with one line per block.
#:
#: This used to clone the root, strip the unwanted elements and read innerText
#: off the clone. The clone is detached, a detached node has no layout, and
#: innerText needs layout - so it fell through to textContent and every block
#: ran into the next. "Email: hello@x.example" followed by "Phone: 0803 111
#: 2233" arrived as "Email: hello@x.examplePhone: 0803 111 2233". Measured in
#: Chromium, not inferred: the live element gives the newlines, the clone does
#: not.
#:
#: It mattered well beyond readability. compare_pages keeps only values that
#: appear in the page's own text, so a price at the end of a paragraph became
#: "$12Licence" and a true value was reported as "not found on the page" -
#: which reads exactly like the brain inventing it. clean_text's split on
#: lines, below, had nothing to split.
#:
#: Walking the tree rather than inserting the clone into the document: no
#: mutation of someone's page, no layout pass, and the same treatment of
#: CSS-hidden text as before (textContent included it, so this is not a
#: change). Blocks get a newline on each side; inline elements do not.
_READ_JS = """
(keepChrome) => {
  const root = keepChrome
    ? document.body
    : (document.querySelector('main, article, [role=main]') || document.body);
  if (!root) return '';
  const SKIP = new Set(keepChrome
    ? ['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'SVG', 'IFRAME']
    : ['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'SVG', 'NAV', 'FOOTER', 'IFRAME']);
  const BLOCK = new Set([
    'ADDRESS', 'ARTICLE', 'ASIDE', 'BLOCKQUOTE', 'BR', 'BUTTON', 'CAPTION', 'DD', 'DETAILS', 'DIALOG',
    'DIV', 'DL', 'DT', 'FIELDSET', 'FIGCAPTION', 'FIGURE', 'FORM', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6',
    'HEADER', 'HR', 'LABEL', 'LEGEND', 'LI', 'MAIN', 'OL', 'OPTION', 'P', 'PRE', 'SECTION', 'SUMMARY',
    'TABLE', 'TBODY', 'TD', 'TH', 'THEAD', 'TR', 'UL',
  ]);
  let out = '';
  const nl = () => { if (out && !out.endsWith('\\n')) out += '\\n'; };
  const walk = (node) => {
    if (node.nodeType === 3) { out += node.nodeValue; return; }
    if (node.nodeType !== 1) return;
    if (SKIP.has(node.tagName) || node.hasAttribute('hidden')
        || node.getAttribute('aria-hidden') === 'true') return;
    const block = BLOCK.has(node.tagName);
    if (block) nl();
    for (const child of node.childNodes) walk(child);
    if (block) nl();
  };
  walk(root);
  return out;
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


async def read_page(page, keep_chrome: bool = False) -> dict:
    """The page's readable text.

    By default the navigation, the footer and anything outside <main> are left
    out: for reading an article they are repetition that costs a small brain its
    context window.

    keep_chrome=True reads the whole body instead, for the one job where that
    furniture is the content - a business's address and telephone number are
    usually in the footer of every page and nowhere else on the site, so
    hunting for contact details with the footer stripped finds nothing and
    reports, wrongly, that the site does not publish them.
    """
    text, truncated = clean_text(await evaluate(page, _READ_JS, bool(keep_chrome)))
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
