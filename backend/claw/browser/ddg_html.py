"""DuckDuckGo's plain HTML results page, read without a browser.

Ported from OpenClaw (MIT, (c) 2026 OpenClaw Foundation),
extensions/duckduckgo/src/ddg-client.ts: the endpoint, the result/snippet patterns, the
uddg redirect unwrapping and the bot-challenge check. Rewritten in Python for S-CLAW.

Why: in the real-brain trial on Windows the browser loaded DuckDuckGo's normal page and
"no results could be read from it". The HTML endpoint is a stable, simple page made for
exactly this, so it is tried when the browser's page gives nothing.
"""

from __future__ import annotations

import html as _html
import re
from urllib.parse import parse_qs, urlparse

import httpx

ENDPOINT = "https://html.duckduckgo.com/html"
USER_AGENT = "s-claw-duckduckgo/0.5 (+https://github.com/akintundeoluwaseun/oluwaseun-claw)"

_RESULT = re.compile(r'<a\b(?=[^>]*\bclass="[^"]*\bresult__a\b[^"]*")([^>]*)>([\s\S]*?)</a>', re.I)
_NEXT = re.compile(r'<a\b(?=[^>]*\bclass="[^"]*\bresult__a\b[^"]*")[^>]*>', re.I)
_SNIPPET = re.compile(r'<a\b(?=[^>]*\bclass="[^"]*\bresult__snippet\b[^"]*")[^>]*>([\s\S]*?)</a>', re.I)
_CHALLENGE = re.compile(r'g-recaptcha|are you a human|id="challenge-form"|name="challenge"', re.I)


class SearchChallenge(Exception):
    """DuckDuckGo answered with a 'are you a human' page instead of results."""


def _strip(markup: str) -> str:
    # Match highlights can sit inside words, so <b> is removed without adding a space.
    text = re.sub(r"</?b\b[^>]*>", "", markup, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return _html.unescape(re.sub(r"\s+", " ", text)).strip()


def _real_url(raw: str) -> str:
    url = _html.unescape(raw)
    try:
        parsed = urlparse("https:" + url if url.startswith("//") else url)
        uddg = parse_qs(parsed.query).get("uddg")
        if uddg:
            return uddg[0]
    except ValueError:
        pass
    return url


def parse(page: str, count: int = 10) -> list[dict]:
    if not re.search(r'class="[^"]*\bresult__a\b', page, re.I) and _CHALLENGE.search(page):
        raise SearchChallenge("DuckDuckGo asked whether this is a person, so no results were read.")
    results: list[dict] = []
    for m in _RESULT.finditer(page):
        href = re.search(r'\bhref="([^"]*)"', m.group(1), re.I)
        tail = page[m.end():]
        nxt = _NEXT.search(tail)
        scoped = tail[: nxt.start()] if nxt else tail
        snip = _SNIPPET.search(scoped)
        title, url = _strip(m.group(2)), _real_url(href.group(1) if href else "")
        if title and url.startswith(("http://", "https://")):
            results.append({"title": title[:200], "url": url, "snippet": _strip(snip.group(1))[:300] if snip else ""})
            if len(results) >= count:
                break
    return results


async def search(query: str, count: int = 10, timeout: float = 20.0) -> list[dict]:
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
        r = await client.get(ENDPOINT, params={"q": query, "kp": "-1"})
        r.raise_for_status()
        return parse(r.text, count)
