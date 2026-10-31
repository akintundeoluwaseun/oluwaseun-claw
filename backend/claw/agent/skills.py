"""Skills: short written recipes Claw adds to a task when they fit it.

The idea and the file format come from OpenClaw (MIT, (c) 2026 OpenClaw Foundation):
a folder per skill holding SKILL.md, YAML front matter with `name` and `description`,
then plain instructions. OpenClaw lists skills and lets a large model open the one it
wants; a 2B brain will not, so here Claw picks the best match itself (words of the
request against the skill's name, description and `triggers`) and puts its text next
to the task.

Two places are read: the skills that ship with Claw (claw/skills/) and the person's own
(%APPDATA%\\S-CLAW\\skills\\<name>\\SKILL.md, or any *.md there). A skill written for
OpenClaw that only carries instructions works as it is; one that needs a command-line
program Claw does not have is skipped when its front matter says so (requires.bins).
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

BUILTIN = Path(__file__).resolve().parent.parent / "skills"
MAX_BODY = 1400
_WORD = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "my", "it", "is", "with", "me", "this",
         "that", "from", "into", "at", "by", "be", "use", "when", "what", "how", "do", "can", "you", "i", "your"}


@dataclass
class Skill:
    name: str
    description: str
    body: str
    path: Path
    triggers: list[str] = field(default_factory=list)

    def words(self) -> set[str]:
        text = " ".join([self.name.replace("-", " "), self.description, " ".join(self.triggers)]).lower()
        return {w for w in _WORD.findall(text) if w not in _STOP and len(w) > 2}


def _field(front: str, key: str) -> str:
    m = re.search(rf"^{key}:\s*(.+)$", front, re.M)
    return m.group(1).strip().strip("\"'") if m else ""


def parse(text: str, path: Path) -> Skill | None:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if not m:
        return None
    front, body = m.group(1), m.group(2).strip()
    name, desc = _field(front, "name"), _field(front, "description")
    if not name or not desc or not body:
        return None
    bins = re.search(r'"bins"\s*:\s*\[([^\]]*)\]', front)
    if bins:
        needed = re.findall(r'"([^"]+)"', bins.group(1))
        if any(shutil.which(b) is None for b in needed):
            return None                   # an OpenClaw skill for a program this computer lacks
    trig = _field(front, "triggers")
    triggers = [t.strip() for t in re.split(r"[,;]", trig.strip("[]")) if t.strip()] if trig else []
    return Skill(name[:60], desc[:300], body, path, triggers)


def load(*dirs: Path) -> list[Skill]:
    found: dict[str, Skill] = {}
    for d in dirs:
        if not d or not d.is_dir():
            continue
        for f in sorted(list(d.glob("*/SKILL.md")) + list(d.glob("*.md"))):
            try:
                s = parse(f.read_text(encoding="utf-8-sig")[:20000], f)
            except OSError:
                continue
            if s:
                found[s.name] = s         # the person's own skill replaces a built-in of the same name
    return list(found.values())


def pick(task: str, skills: list[Skill], minimum: int = 2) -> Skill | None:
    want = {w for w in _WORD.findall(task.lower().split("\n")[0]) if w not in _STOP and len(w) > 2}
    best, score = None, 0
    for s in skills:
        sw = s.words()
        n = len(want & sw) + sum(2 for t in s.triggers if t.lower() in task.lower())
        if n > score:
            best, score = s, n
    return best if score >= minimum else None


def for_prompt(skill: Skill) -> str:
    body = skill.body if len(skill.body) <= MAX_BODY else skill.body[:MAX_BODY].rsplit("\n", 1)[0] + "\n…"
    return f"\n\nA recipe that fits this task ({skill.name}). Follow it where it helps:\n{body}"
