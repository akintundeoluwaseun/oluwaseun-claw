"""The honest end of a task: what was COMPLETED, what is UNVERIFIED, INCOMPLETE or BLOCKED.

Every task ends with this four-way account, built only from what Claw observed (step outcomes and the
files it made and re-checked), never from the brain's own summary. A click that was sent is not a
completed step; a file that was written but not re-read is UNVERIFIED; a step the person refused, or
one that needs them, is BLOCKED; a task that stopped part-way is INCOMPLETE.

Resuming builds on the same record: the steps that were completed are handed to the next attempt as
"already done, do not repeat", so an interrupted task carries on instead of starting over.
"""

from __future__ import annotations

from typing import Any

LOOKING = {"web_search", "open_search_result", "read_page", "open_url", "extract_links", "list_tabs", "new_tab",
           "switch_tab", "list_folder", "find_files", "read_file", "read_document_pages", "search_document",
           "summarize_document", "list_windows", "look_at_window", "describe_screen", "take_screenshot",
           "current_time", "disk_space", "is_program_running", "list_events", "check_whatsapp", "inspect_image",
           "look_at_page", "recall", "check_file"}


def _line(step: dict[str, Any]) -> str:
    detail = str(step.get("detail") or "").strip().split("\n")[0]
    return detail[:220] if detail else str(step.get("tool"))


def final_report(steps: list[dict[str, Any]], files: list[dict[str, Any]], status: str,
                 error: str | None = None) -> dict[str, list[str]]:
    rep: dict[str, list[str]] = {"completed": [], "unverified": [], "incomplete": [], "blocked": []}
    for s in steps:
        tool, out = s.get("tool"), s.get("outcome")
        if out in ("denied", "blocked"):
            rep["blocked"].append(f"{tool}: {_line(s)}")
        elif tool in LOOKING and tool != "check_file":
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
    return rep


def done_so_far(events: list[dict[str, Any]]) -> list[str]:
    """Completed (verified) steps of an earlier attempt, from its event log, oldest first, without repeats."""
    seen, out = set(), []
    for e in events:
        if e.get("kind") != "verified":
            continue
        d = e.get("data") or {}
        if d.get("tool") in LOOKING and d.get("tool") != "check_file":
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
