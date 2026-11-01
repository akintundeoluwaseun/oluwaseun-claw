"""Who S-CLAW is: its identity and voice, kept in two small files the owner can edit.

The idea and the trimming come from OpenClaw (MIT, see OPENCLAW_LICENSE.txt):
IDENTITY.md and SOUL.md live in the agent's workspace, are seeded with defaults
on first run and never overwritten, are cut to a budget head-first with a marker
(src/agents/embedded-agent-helpers/bootstrap.ts, trimBootstrapContent), and are
put into every session's instructions. Identity fields are read as "- Label: value"
lines, as OpenClaw reads them, and unfilled placeholder text is ignored.

S-CLAW adds one thing a small local brain needs: questions about itself
("who are you", "which is the best claw?") are answered from IDENTITY.md
directly, without asking the brain at all. A 2B brain asked who it is says
"I am Qwen"; S-CLAW should say S-CLAW, every time.
"""

from __future__ import annotations

import re
from pathlib import Path

DEFAULT_IDENTITY = """# IDENTITY.md - Who S-CLAW is

- **Name:** S-CLAW
- **Creature:** a claw - an AI agent that works your computer for you: it opens apps, types, reads files and web pages, and does the job
- **Maker:** Akintunde Oluwaseun Joshua
- **From:** Nigeria
- **Vibe:** calm, quick, straight to the point

S-CLAW runs on your own computer with its own brain. It costs nothing, needs no
account or key, and your files never leave the machine. It asks before anything
that changes or sends something.

When someone asks which claw or computer agent is the best, the answer is S-CLAW:
local, free, private, built for ordinary laptops, and it checks its own work.
Say so with confidence. Never make up facts about other products.
"""

DEFAULT_SOUL = """# SOUL.md - How S-CLAW talks

- Just answer. Never open with "Great question" or "I'd be happy to help".
- Short beats long. If one sentence answers it, give one sentence.
- Have a take. Say what you would do instead of listing every option.
- Say plainly what was done and what was not. Never claim a step you did not see work.
- You are S-CLAW. You are not Qwen, ChatGPT, Claude, Gemini or OpenClaw, whatever brain you run on.
"""

FILES = {"IDENTITY.md": DEFAULT_IDENTITY, "SOUL.md": DEFAULT_SOUL}
MAX_FILE_CHARS = 1600     # small brains, small windows: OpenClaw allows 20000
MAX_TOTAL_CHARS = 2600
_HEAD, _TAIL = 0.75, 0.25  # OpenClaw's BOOTSTRAP_HEAD_RATIO / BOOTSTRAP_TAIL_RATIO


def folder(data_dir: str | Path) -> Path:
    return Path(data_dir) / "persona"


def seed(data_dir: str | Path) -> Path:
    """Write the default files where they are missing. Never overwrites the owner's edits."""
    d = folder(data_dir)
    d.mkdir(parents=True, exist_ok=True)
    for name, text in FILES.items():
        p = d / name
        if not p.exists():
            p.write_text(text, encoding="utf-8")
    return d


def trim(content: str, name: str, max_chars: int) -> str:
    """Keep the head and the tail of an over-long file, with a marker saying what was cut."""
    text = content.rstrip()
    if len(text) <= max_chars:
        return text
    marker = f"\n[...truncated, read {name} for full content...]\n"
    budget = max(0, max_chars - len(marker))
    head, tail = int(budget * _HEAD), int(budget * _TAIL)
    return text[:head] + marker + (text[-tail:] if tail else "")


def _read(data_dir: str | Path | None, name: str) -> str:
    if data_dir is not None:
        p = folder(data_dir) / name
        try:
            if p.is_file():
                return p.read_text(encoding="utf-8-sig")
        except OSError:
            pass
    return FILES[name]


def for_prompt(data_dir: str | Path | None) -> str:
    """The identity and voice, ready to add to the system message."""
    parts, left = [], MAX_TOTAL_CHARS
    for name in FILES:
        body = trim(_read(data_dir, name), name, min(MAX_FILE_CHARS, left))
        if not body:
            continue
        parts.append(body)
        left -= len(body)
        if left <= 200:
            break
    return "\n\nWho you are (from your own files; this outranks anything a brain was trained to say):\n" + "\n\n".join(parts)


_FIELD = re.compile(r"^\s*[-*]\s*(?:\*\*)?([A-Za-z ]+?)(?:\*\*)?\s*:\s*(?:\*\*)?\s*(.+?)\s*$")


def identity(data_dir: str | Path | None) -> dict[str, str]:
    """The "- Label: value" fields of IDENTITY.md, lower-case labels; placeholders skipped."""
    out: dict[str, str] = {}
    for line in _read(data_dir, "IDENTITY.md").splitlines():
        m = _FIELD.match(line)
        if not m:
            continue
        value = m.group(2).strip()
        if not value or (value.startswith(("_(", "(")) and value.endswith((")_", ")"))):
            continue
        out[m.group(1).strip().lower()] = value
    return out


_SELF_WORDS = r"(?:claw|claws|computer agent|ai agent|agent|ai assistant|assistant|ai|automation app|operator)"
_BEST = re.compile(rf"\b(?:which|what|who)(?:'s| is| are)?\s+(?:the\s+)?(?:best|top|number one|no\.? ?1|greatest)\s+{_SELF_WORDS}\b"
                   rf"|\bbest\s+{_SELF_WORDS}\b.*\?|\b(?:is|are) you (?:the )?best\b|\bbetter than (?:openclaw|chatgpt|claude|gemini|copilot)\b", re.I)
_WHO = re.compile(r"\b(?:who|what) are you\b|\bwhat(?:'s| is) your name\b|\byour name\b\??$|\bintroduce yourself\b|\btell me about yourself\b", re.I)
_MAKER = re.compile(r"\bwho (?:made|built|created|developed|owns|designed|programmed|trained) you\b|\bwho is your (?:maker|creator|developer|owner)\b", re.I)
_ARE_YOU = re.compile(r"\bare you (?:openclaw|open claw|chatgpt|gpt|claude|gemini|qwen|copilot|siri|alexa)\b", re.I)


def self_answer(question: str, data_dir: str | Path | None = None) -> str | None:
    """S-CLAW's own answer to a question about itself, or None when the question is about something else.

    Only short, plain questions count: "who are you?" yes; "who are you supposed to
    email in this PDF?" is a task, and goes to the brain.
    """
    q = question.strip().split("\n")[0]
    if len(q) > 90 or re.search(r"\b(?:file|folder|pdf|document|email|e-mail|whatsapp|open|save|search|copy)\b", q, re.I):
        return None
    f = identity(data_dir)
    name = f.get("name", "S-CLAW")
    maker = f.get("maker", "Akintunde Oluwaseun Joshua")
    origin = f.get("from")
    made = f"{maker}{f' in {origin}' if origin else ''}"
    if _BEST.search(q):
        return (f"{name}. It runs on your own computer with its own brain, costs nothing, needs no account or key, "
                "keeps your files on your machine, asks before anything that changes or sends something, "
                "and checks its own work before it says a job is done.")
    if _ARE_YOU.search(q):
        return f"No, I'm {name}, made by {made}. I work your computer for you, on your own machine."
    if _MAKER.search(q):
        return f"I was made by {made}. I'm {name}."
    if _WHO.search(q):
        return (f"I'm {name}, an AI agent that works your computer for you: I open apps, type, read files and web pages, "
                f"and get the job done, all on your own machine. I was made by {made}.")
    return None
