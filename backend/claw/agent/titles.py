"""Chat titles: short names for a conversation, like a person would give it — not the request pasted back.

The model writes the real title while it plans (one field in the plan it already returns, so it costs no
extra call). Until then — or when no brain is available — a title is made from the request itself: polite
openers and filler are dropped and it is cut at the first natural break, so "Can you please open Notepad and
type my shopping list" becomes "Open Notepad".
"""

from __future__ import annotations

import re

MAX_WORDS = 7
_OPENERS = re.compile(
    r"^(hey|hi|hello|ok(ay)?|so|um+|please|kindly|claw|s-claw)\b[,!.\s]*|"
    r"^(can|could|would|will) you( please)?\s+|^(i (want|need|would like) (you )?to|help me( to)?|i'd like (you )?to|"
    r"go ahead and|try to|let'?s)\s+",
    re.I,
)
_VERBS = r"(?:save|send|tell|show|put|make|create|open|check|type|write|read|compare|copy|email|print|remind|summari[sz]e|give|list|find)"
_BREAK = re.compile(r"\s*(?:[,;:!?\n]|\.(?:\s|$)| and then | then | and (?=" + _VERBS + r"\b))", re.I)
_WEB = re.compile(r"\b(search|look)( up)?( (on )?(the web|online|google|the internet))?( for)?\s+", re.I)
_SMALL = {"a", "an", "the", "of", "for", "to", "in", "on", "and", "or", "my", "with", "at", "by", "from"}


def fallback_title(request: str) -> str:
    text = " ".join(request.strip().split())
    for _ in range(3):  # "Hi, can you please …" has several openers in a row
        text = _OPENERS.sub("", text).strip()
    first = _BREAK.split(text, maxsplit=1)[0].strip() or text
    # "search the web for X" -> "search X", keeping the case it had (mid-sentence stays lower case).
    first = _WEB.sub(lambda m: m.group(1) + " ", first, count=1)
    words = first.split()
    if len(words) > MAX_WORDS:
        words = words[:MAX_WORDS]
        while words and words[-1].lower() in _SMALL:
            words.pop()
    title = " ".join(words).strip(" -–—'\"")
    return (title[:1].upper() + title[1:]) if title else "New chat"


def clean_model_title(title: str | None) -> str | None:
    """A model's title, tidied; None if it is unusable (empty, a sentence, or just the request repeated)."""
    if not title:
        return None
    t = " ".join(str(title).split()).strip(" .\"'`*#")
    if not t or len(t) > 60 or len(t.split()) > 8:
        return None
    return t[:1].upper() + t[1:]
