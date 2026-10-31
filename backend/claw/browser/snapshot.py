"""Page snapshots with numbered refs - the way OpenClaw lets a model work a web page.

Ported from OpenClaw (MIT, (c) 2026 OpenClaw Foundation),
extensions/browser/src/browser/pw-role-snapshot.ts and snapshot-roles.ts:
the role sets, the snapshot-line parser, the interactive filter, the compact tree
and the truncation that keeps only refs on complete lines. Rewritten in Python.

Playwright (1.5x+) writes an "AI" accessibility snapshot in which every element carries
a ref such as e7, and `page.locator("aria-ref=e7")` finds that exact element again. So
the brain reads a short outline - `- button "Pay now" [ref=e12]` - and says "click e12"
instead of guessing selectors or label text, which small brains get wrong.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

INTERACTIVE_ROLES = {
    "button", "checkbox", "combobox", "link", "listbox", "menuitem", "menuitemcheckbox", "menuitemradio",
    "option", "radio", "searchbox", "slider", "spinbutton", "switch", "tab", "textbox", "treeitem",
}
STRUCTURAL_ROLES = {
    "application", "directory", "document", "generic", "grid", "group", "ignored", "list", "menu", "menubar",
    "none", "presentation", "row", "rowgroup", "table", "tablist", "toolbar", "tree", "treegrid",
}
TRUNCATED = "[...TRUNCATED - page too large]"
_LINE = re.compile(r"^(\s*-\s+)(.*)$", re.S)
_REF_OK = re.compile(r"^(?:f\d+)?e\d+$|^\d{1,9}$", re.I)


@dataclass
class Snapshot:
    text: str
    refs: dict[str, dict] = field(default_factory=dict)   # ref -> {"role":..., "name":...}
    urls: list[str] = field(default_factory=list)
    truncated: bool = False


def _indent(line: str) -> int:
    return (len(line) - len(line.lstrip())) // 2


def parse_line(line: str) -> dict | None:
    m = _LINE.match(line)
    if not m:
        return None
    content = m.group(2)
    quoted = re.match(r"^'((?:[^']|'')*)'(.*)$", content, re.S)
    key = quoted.group(1).replace("''", "'") if quoted else content
    km = re.match(r'^(\w+)(?:\s+("(?:\\.|[^"\\])*"))?(.*)$', key, re.S)
    if not km:
        return None
    role_raw, name_tok, suffix = km.group(1), km.group(2), km.group(3)
    attrs = re.match(r"^(?:\s+\[[^\][]*\])*", suffix).group(0)
    ref = re.search(r"\[ref=([^\][]+)\]", attrs)
    name = None
    if name_tok:
        try:
            name = json.loads(name_tok)
        except ValueError:
            name = name_tok.strip('"')
    return {"role": role_raw.lower(), "role_raw": role_raw, "name": name, "ref": ref.group(1) if ref else None,
            "suffix": suffix + (quoted.group(2) if quoted else "")}


def _compact(lines: list[str]) -> str:
    entries: list[dict] = []
    stack: list[dict] = []

    def finish():
        cur = stack.pop()
        cur["keep"] = cur["keep"] or cur["has_ref"]
        if cur["has_ref"] and stack:
            stack[-1]["has_ref"] = True

    for line in lines:
        ind = _indent(line)
        while stack and stack[-1]["indent"] >= ind:
            finish()
        p = parse_line(line)
        has_ref = bool(p and p["ref"])
        choice = bool(p and p["role"] in INTERACTIVE_ROLES)      # e.g. the options of a dropdown
        e = {"line": line, "keep": has_ref or choice or (":" in line and not line.rstrip().endswith(":")),
             "has_ref": has_ref, "indent": ind}
        entries.append(e)
        stack.append(e)
    while stack:
        finish()
    return "\n".join(e["line"] for e in entries if e["keep"]) or "(empty)"


def build(ai_snapshot: str, *, interactive: bool = False, compact: bool = True, max_chars: int = 6000) -> Snapshot:
    """Turn Playwright's AI snapshot into what the brain sees, and the refs it may use."""
    refs: dict[str, dict] = {}
    urls = re.findall(r"^\s*-\s+/url:\s*(\S+)", ai_snapshot, re.M)
    out: list[str] = []
    for line in ai_snapshot.split("\n"):
        p = parse_line(line)
        if not p:
            if not interactive and not re.match(r"^\s*-\s+/url:", line):
                out.append(line)
            continue
        ref = p["ref"] if p["ref"] and _REF_OK.match(p["ref"]) else None
        if interactive:
            if p["role"] in INTERACTIVE_ROLES and ref:
                refs[ref] = {"role": p["role"], "name": p["name"] or ""}
                s = f"- {p['role_raw']}" + (f" {json.dumps(p['name'])}" if p["name"] else "") + f" [ref={ref}]"
                out.append(s + p["suffix"].replace(f" [ref={ref}]", "").replace(" [cursor=pointer]", ""))
            continue
        if compact and p["role"] in STRUCTURAL_ROLES and not p["name"]:
            continue
        if ref:
            refs[ref] = {"role": p["role"], "name": p["name"] or ""}
        out.append(line.replace(" [cursor=pointer]", ""))
    if interactive:
        text = "\n".join(out) or "(no interactive elements)"
    else:
        text = _compact(out) if compact else "\n".join(out)
    truncated = len(text) > max_chars
    if truncated:
        kept, total = [], 0
        for line in text.split("\n"):
            if total + len(line) + 1 + len(TRUNCATED) + 2 > max_chars:
                break
            kept.append(line)
            total += len(line) + 1
        text = "\n".join(kept) + "\n\n" + TRUNCATED
    visible = set(re.findall(r"\[ref=([^\][]+)\]", text))
    return Snapshot(text, {r: v for r, v in refs.items() if r in visible}, urls, truncated)
