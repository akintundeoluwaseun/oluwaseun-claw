"""Where Claw searches, and how it reads the answer.

One engine's HTML is a bad thing to be married to: DuckDuckGo can change a class
name and Claw silently finds nothing. So the engine is a value, not a hard-coded
branch, and every provider carries three things — how to build the query URL, how
to read that engine's result layout, and what to tell the user when it fails.

A provider whose layout stops matching does not fail silently: reading falls back
to the links in the page's main content (see `extract.search_results`), and the
result records which provider answered and when.

SearXNG is included because it is the practical way to stop depending on one
engine: it is a metasearch service the user or operator runs, reached over HTTP.
It is AGPL-3.0, so Claw talks to it and never bundles or links it.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote_plus, urlparse


@dataclass(frozen=True)
class SearchProvider:
    id: str
    name: str
    #: contains {query}; for the providers the user configures it is built at run time
    template: str
    #: JavaScript run in the result page; "" means go straight to the link fallback
    results_js: str
    #: the user must supply an address (a SearXNG host, or a whole custom template)
    needs_address: bool = False
    note: str = ""


# Each selector set is the layout that engine serves today. When one stops
# matching, the fallback in search_results still returns the page's links, and
# the result says how many were found, so a broken selector looks like a thin
# result rather than a confident "nothing exists".
_DDG_JS = """
() => Array.from(document.querySelectorAll('.result')).map(r => {
  const a = r.querySelector('a.result__a');
  const s = r.querySelector('.result__snippet');
  return a ? { title: a.innerText.trim(), url: a.href, snippet: s ? s.innerText.trim() : '' } : null;
}).filter(Boolean)
"""

_BING_JS = """
() => Array.from(document.querySelectorAll('#b_results > li.b_algo')).map(r => {
  const a = r.querySelector('h2 a');
  const s = r.querySelector('.b_caption p, p');
  return a ? { title: a.innerText.trim(), url: a.href, snippet: s ? s.innerText.trim() : '' } : null;
}).filter(Boolean)
"""

# SearXNG's own result markup. Both spellings are present across its themes.
_SEARXNG_JS = """
() => Array.from(document.querySelectorAll('article.result, .result.result-default')).map(r => {
  const a = r.querySelector('a.url_wrapper, h3 a, a[href^="http"]');
  const s = r.querySelector('.content, p.content');
  return a ? { title: (r.querySelector('h3') || a).innerText.trim(), url: a.href,
               snippet: s ? s.innerText.trim() : '' } : null;
}).filter(Boolean)
"""

PROVIDERS: dict[str, SearchProvider] = {
    "duckduckgo": SearchProvider(
        "duckduckgo", "DuckDuckGo", "https://html.duckduckgo.com/html/?q={query}", _DDG_JS,
        note="No account. The plain HTML version, which is lighter and easier to read.",
    ),
    "bing": SearchProvider(
        "bing", "Bing", "https://www.bing.com/search?q={query}", _BING_JS,
        note="No account.",
    ),
    "searxng": SearchProvider(
        "searxng", "A SearXNG server", "", _SEARXNG_JS, needs_address=True,
        note="A metasearch server you or your organisation runs. Claw only talks to it; "
             "it is not part of Claw, and it still needs the internet of its own.",
    ),
    "custom": SearchProvider(
        "custom", "A search address of your own", "", "", needs_address=True,
        note="Any address containing {query}. Results are read from the page's links.",
    ),
}


def get(engine: str) -> SearchProvider:
    provider = PROVIDERS.get(engine)
    if provider is None:
        raise KeyError(f"unknown search provider {engine!r}")
    return provider


def searxng_template(base_url: str) -> str:
    """A SearXNG host's search address, from whatever the user typed."""
    base = base_url.strip().rstrip("/")
    if base.endswith("/search"):
        base = base[: -len("/search")]
    return f"{base}/search?q={{query}}"


def build_url(engine: str, query: str, custom_url: str = "", searxng_url: str = "") -> str:
    provider = get(engine)
    if engine == "custom":
        template = custom_url
    elif engine == "searxng":
        template = searxng_template(searxng_url)
    else:
        template = provider.template
    if "{query}" not in template:
        raise ValueError(f"the address for {provider.name} must contain {{query}}")
    return template.replace("{query}", quote_plus(query))


def describe(engine: str, custom_url: str = "", searxng_url: str = "") -> dict:
    """What the interface and the task log should say about where a search went."""
    provider = get(engine)
    host = ""
    try:
        host = urlparse(build_url(engine, "x", custom_url, searxng_url)).netloc
    except (ValueError, KeyError):
        host = ""
    return {"id": provider.id, "name": provider.name, "host": host, "note": provider.note}
