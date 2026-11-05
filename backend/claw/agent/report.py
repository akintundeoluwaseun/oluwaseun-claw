"""The honest end of a task: what was COMPLETED, what is UNVERIFIED, INCOMPLETE or BLOCKED.

Every task ends with this four-way account, built only from what Claw observed (step outcomes and the
files it made and re-checked), never from the brain's own summary. A click that was sent is not a
completed step; a file that was written but not re-read is UNVERIFIED; a step the person refused, or
one that needs them, is BLOCKED; a task that stopped part-way is INCOMPLETE.

Resuming builds on the same record: the steps that were completed are handed to the next attempt as
"already done, do not repeat", so an interrupted task carries on instead of starting over.
"""

from __future__ import annotations

import re
from typing import Any

from claw.tools.kinds import is_looking  # noqa: E402


def _line(step: dict[str, Any]) -> str:
    detail = str(step.get("detail") or "").strip().split("\n")[0]
    return detail[:220] if detail else str(step.get("tool"))


#: Challenge 17.18 - compare the final output against the original request.
#:
#: Only things that can be checked, never judged. A request that names the file
#: it wants, the folder it wants it in, or the format it wants it in, has said
#: something a saved file either satisfies or does not. Anything vaguer than
#: that ("make it nice") is not checked here, because a guess in this list
#: would be exactly the kind of confident wrongness the rest of the report
#: exists to prevent.
_WANTS_NAME = re.compile(
    r"\b(?:call(?:ed)? it|name(?:d|s)? it|save (?:it |them )?as|into a file (?:called|named))\s+"
    r"[\"'\u201c]?([\w .-]{1,60}\.[A-Za-z0-9]{2,5})", re.I)
#: A DESTINATION, which needs a verb that puts something somewhere. Without
#: one, "tell me what is in my Downloads folder" reads as a request to save
#: into Downloads and every answer looks like it went to the wrong place.
_WANTS_FOLDER = re.compile(
    # The verb is case-insensitive - a request usually starts with it, capitalised -
    # but the folder is not: a capital is most of what tells "Backup" the folder
    # from "backup" the noun.
    r"(?i:\b(?:save|saves|saved|saving|put|puts|write|writes|export|exports|place|places|"
    r"move|moves|copy|copies|download|downloads|store|stores|keep|keeps)\b)"
    # Up to a few words in between. A full stop ends the sentence and the claim
    # with it, but a dot inside a word (sales.csv) does not.
    r"(?:[^.\n]|\.(?=\w)){0,40}?"
    r"(?i:\b(?:in|into|to|inside|onto)\s+(?:my\s+|the\s+)?)"
    r"(Documents|Desktop|Downloads|Pictures|Videos|Music|[A-Z][\w -]{2,30}?)\s*(?:folder)?\b")
#: "as a PDF" and friends, with the extensions that satisfy each.
_FORMATS = {
    "pdf": (".pdf",), "spreadsheet": (".xlsx", ".csv"), "excel": (".xlsx",), "csv": (".csv",),
    "word document": (".docx",), "word": (".docx",), "document": (".docx", ".pdf", ".txt", ".md"),
    "presentation": (".pptx",), "powerpoint": (".pptx",), "slide deck": (".pptx",),
    "text file": (".txt",), "image": (".png", ".jpg", ".jpeg"), "picture": (".png", ".jpg", ".jpeg"),
    "video": (".mp4", ".mov"), "zip": (".zip",), "archive": (".zip",),
}
_WANTS_FORMAT = re.compile(r"\bas an? ([a-z ]{2,16}?)\b", re.I)


def unmet_requirements(task: str, files: list[dict[str, Any]]) -> list[str]:
    """What the request plainly asked for that the saved files do not show.

    Checked against the files Claw actually recorded, so this cannot be
    satisfied by the brain saying it did something.
    """
    line = (task or "").split("\n")[0]
    if not line:
        return []
    paths = [str(f.get("path", "")).replace("\\", "/") for f in files]
    names = [p.rsplit("/", 1)[-1].lower() for p in paths]
    out: list[str] = []

    wanted = _WANTS_NAME.search(line)
    if wanted:
        asked = wanted.group(1).strip().lower()
        if asked and asked not in names:
            out.append(f"You asked for a file called {wanted.group(1).strip()}; "
                       + (f"what was saved is {', '.join(sorted(set(names)))}." if names
                          else "no file was saved."))

    folder = _WANTS_FOLDER.search(line)
    if folder and paths:
        where = folder.group(1)
        if not any(f"/{where.lower()}/" in p.lower() for p in paths):
            out.append(f"You asked for it in {where}; it was saved to "
                       + ", ".join(sorted({p.rsplit("/", 1)[0] for p in paths})) + ".")

    for match in _WANTS_FORMAT.finditer(line):
        want = match.group(1).strip().lower()
        suffixes = _FORMATS.get(want)
        if suffixes and names and not any(n.endswith(suffixes) for n in names):
            out.append(f"You asked for it as a {want}; "
                       f"what was saved is {', '.join(sorted(set(names)))}.")
            break
    return out


def final_report(steps: list[dict[str, Any]], files: list[dict[str, Any]], status: str,
                 error: str | None = None, task: str = "") -> dict[str, list[str]]:
    rep: dict[str, list[str]] = {"completed": [], "unverified": [], "incomplete": [], "blocked": []}
    for s in steps:
        tool, out = s.get("tool"), s.get("outcome")
        if out in ("denied", "blocked"):
            rep["blocked"].append(f"{tool}: {_line(s)}")
        elif is_looking(tool) and tool != "check_file":
            continue  # looking is how work is done, not work done
        elif out == "verified":
            rep["completed"].append(_line(s))
        elif out == "done_unverified":
            rep["unverified"].append(_line(s))
    for f in files:
        name = str(f.get("path", "")).replace("\\", "/").split("/")[-1]
        if not f.get("verified"):
            rep["unverified"].append(f"{name}: written, but its contents were not confirmed" + (f" ({f['note']})" if f.get("note") else ""))
    if status in ("failed", "stopped", "cancelled", "interrupted", "incomplete", "timed_out"):
        why = {"cancelled": "You stopped it.", "interrupted": "S-CLAW stopped before it finished (closed or crashed)."}.get(status, error or "")
        rep["incomplete"].append(f"The task did not finish. {why}".strip())
    elif status == "completed" and not rep["completed"] and not rep["unverified"] and any(s.get("outcome") == "failed" for s in steps):
        rep["incomplete"].append("Nothing that was tried worked.")
    if any(s.get("tool") == "pause_for_me" for s in steps if s.get("outcome") != "verified"):
        rep["blocked"].append("Waiting for you: a sign-in, code or CAPTCHA.")
    # Challenge 17.18: the request, checked against what is actually on disk.
    rep["incomplete"] += unmet_requirements(task, files)
    return rep


def done_so_far(events: list[dict[str, Any]]) -> list[str]:
    """Completed (verified) steps of an earlier attempt, from its event log, oldest first, without repeats."""
    seen, out = set(), []
    for e in events:
        if e.get("kind") != "verified":
            continue
        d = e.get("data") or {}
        if is_looking(d.get("tool")) and d.get("tool") != "check_file":
            continue
        line = f"{d.get('tool')}: {str(d.get('detail') or '')[:200]}"
        if line not in seen:
            seen.add(line)
            out.append(line)
    return out


def resume_text(task_text: str, done: list[str]) -> str:
    if not done:
        return task_text + "\n\n(This is a second attempt; the first one stopped before anything was finished.)"
    lines = "\n".join(f"- {d}" for d in done[:20])
    return (f"{task_text}\n\nThis continues an earlier attempt that stopped part-way. These steps were already done and "
            f"checked - do NOT repeat them; carry on with what is left:\n{lines}")
