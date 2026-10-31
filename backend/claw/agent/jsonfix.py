"""Reading a model's JSON when it is nearly right.

repair() is ported from OpenClaw (MIT, (c) 2026 OpenClaw Foundation),
packages/ai/src/utils/json-parse.ts (repairJson), rewritten in Python for S-CLAW.
It escapes raw control characters inside strings and doubles a backslash that does not
start a valid escape. Its Windows-path rule matters here more than anywhere: a brain that
writes {"path": "C:\\Users\\Ada\\Documents\\notes.txt"} with single backslashes produces
"\\U", "\\A", "\\D", "\\n" - invalid or, worse, a silent newline in the middle of a path.

loads() also takes the first {...} object out of surrounding chatter or ``` fences,
which small brains add despite being told not to.
"""

from __future__ import annotations

import json
import re

_SIMPLE = set('"\\/bfnrt')
_CONTROL = set("bfnrt")
_WIN_PATH = re.compile(r'(?:^|[^A-Za-z0-9])[A-Za-z]:(?:[\\/][^"\\/:*?<>|\r\n]*)*$')


def repair(text: str) -> str:
    if not re.search(r"[\\\x00-\x1f]", text):
        return text
    out: list[str] = []
    in_str = False
    prefix = ""
    i = 0
    while i < len(text):
        ch = text[i]
        if not in_str:
            out.append(ch)
            if ch == '"':
                in_str, prefix = True, ""
            i += 1
            continue
        if ch == '"':
            out.append(ch)
            in_str, prefix = False, ""
            i += 1
            continue
        if ch == "\\":
            nxt = text[i + 1] if i + 1 < len(text) else ""
            if not nxt:
                out.append("\\\\")
                i += 1
                continue
            if nxt == "u" and re.fullmatch(r"[0-9a-fA-F]{4}", text[i + 2:i + 6] or ""):
                out.append(text[i:i + 6])
                prefix += text[i:i + 6]
                i += 6
                continue
            if nxt in _CONTROL:
                prefix = prefix[-160:]
                if _WIN_PATH.search(prefix):          # C:\Users\new -> keep the backslash
                    out.append("\\\\")
                    prefix += "\\"
                    i += 1
                    continue
            if nxt in _SIMPLE:
                out.append("\\" + nxt)
                prefix += "\\" if nxt == "\\" else "\\" + nxt
                i += 2
                continue
            out.append("\\\\")
            prefix += "\\"
            i += 1
            continue
        out.append(json.dumps(ch)[1:-1] if ord(ch) <= 0x1F else ch)
        prefix += ch
        i += 1
    return "".join(out)


def _first_object(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    text = text.strip()
    if text.startswith("{"):
        return text
    start = text.find("{")
    if start < 0:
        return text
    depth, in_str, esc = 0, False, False
    for j in range(start, len(text)):
        c = text[j]
        if in_str:
            esc = (c == "\\" and not esc)
            if c == '"' and not esc:
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start:j + 1]
    return text[start:]


def loads(text: str):
    """json.loads for model output: fences and chatter removed, then repaired if needed."""
    body = _first_object(text)
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return json.loads(repair(body))
