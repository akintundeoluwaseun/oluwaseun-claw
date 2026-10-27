"""What today looks like, assembled from what this computer actually knows.

A briefing is only worth reading if it is complete or says where it is not. So
this does two jobs: it gathers today's events and the work that did not finish,
and it names the things it cannot see — there is no mailbox here, and no
message history beyond what the person opens themselves.

The assembly is a pure function over events, tasks and a moment. Nothing here
reads a clock, a file or a database, so a briefing can be tested for any day.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from claw.calendar.ics import VEvent
from claw.calendar.store import _moment

#: Task outcomes worth putting in front of someone the next morning.
UNFINISHED = {"failed", "stopped", "incomplete", "needs_approval", "running"}
#: How far back to look for work that did not finish.
LOOK_BACK = timedelta(days=3)
MAX_EVENTS = 20
MAX_TASKS = 5

#: Said plainly, every time. A briefing that silently omits a source teaches
#: people to trust it for things it never covered.
NOT_INCLUDED = [
    "E-mail is not included: S-CLAW has no mailbox access, by design.",
    "Messages are not included: it reads a chat only when you open one with it.",
]


def _local(value: datetime | date) -> datetime:
    return _moment(value).astimezone()


@dataclass
class Item:
    """One line of the briefing's agenda."""

    summary: str
    at: str                  # "09:30", or "All day"
    location: str = ""
    starts_at: datetime | None = None
    all_day: bool = False
    past: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"summary": self.summary, "at": self.at, "location": self.location,
                "all_day": self.all_day, "past": self.past,
                "starts_at": self.starts_at.isoformat() if self.starts_at else None}


@dataclass
class Brief:
    day: date
    agenda: list[Item] = field(default_factory=list)
    unfinished: list[dict[str, str]] = field(default_factory=list)
    not_included: list[str] = field(default_factory=lambda: list(NOT_INCLUDED))
    made_at: datetime | None = None

    @property
    def next_up(self) -> Item | None:
        return next((i for i in self.agenda if not i.past), None)

    def headline(self) -> str:
        """One sentence, because most mornings deserve exactly one."""
        ahead = [i for i in self.agenda if not i.past]
        if not self.agenda:
            return "Nothing in your calendar today."
        if not ahead:
            return f"{len(self.agenda)} thing(s) today, all of them already past."
        first = ahead[0]
        when = "all day" if first.all_day else f"at {first.at}"
        return (f"{len(ahead)} thing(s) left today. Next: {first.summary} {when}."
                if len(ahead) > 1 else f"One thing today: {first.summary} {when}.")

    def as_text(self) -> str:
        lines = [f"{self.day:%A %d %B}", "", self.headline()]
        if self.agenda:
            lines.append("")
            for item in self.agenda:
                mark = "·" if not item.past else "✓"
                where = f" — {item.location}" if item.location else ""
                lines.append(f"  {mark} {item.at:>8}  {item.summary}{where}")
        if self.unfinished:
            lines += ["", "Did not finish:"]
            lines += [f"  · {t['task_text']} ({t['status']})" for t in self.unfinished]
        lines += ["", *self.not_included]
        return "\n".join(lines)

    def as_dict(self) -> dict[str, Any]:
        return {"day": self.day.isoformat(), "headline": self.headline(),
                "agenda": [i.as_dict() for i in self.agenda],
                "unfinished": self.unfinished, "not_included": self.not_included,
                "made_at": (self.made_at or datetime.now(timezone.utc)).isoformat(),
                "text": self.as_text()}


def assemble(events: list[tuple[str, VEvent]], tasks: list[dict[str, Any]],
             now: datetime) -> Brief:
    """The briefing for the day `now` falls on. Pure: everything comes in as an argument."""
    here = now.astimezone()
    day = here.date()
    agenda: list[Item] = []
    for _calendar, event in events:
        if event.start is None or event.status.upper() == "CANCELLED":
            continue
        starts = _local(event.start)
        if event.all_day:
            if event.start != day and not (isinstance(event.start, date) and event.start == day):
                continue
            agenda.append(Item(event.summary or "(no title)", "All day", event.location,
                               starts, all_day=True))
            continue
        if starts.date() != day:
            continue
        agenda.append(Item(event.summary or "(no title)", f"{starts:%H:%M}", event.location,
                           starts, past=starts < here))
    agenda.sort(key=lambda i: (i.all_day is False, i.starts_at or here))
    agenda = agenda[:MAX_EVENTS]

    cutoff = now - LOOK_BACK
    unfinished = []
    for task in tasks:
        if task.get("status") not in UNFINISHED:
            continue
        when = task.get("updated_at") or task.get("created_at") or ""
        try:
            stamp = datetime.fromisoformat(str(when).replace("Z", "+00:00"))
        except ValueError:
            continue
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        if stamp < cutoff:
            continue
        unfinished.append({"id": str(task.get("id", "")),
                           "task_text": str(task.get("task_text", ""))[:160],
                           "status": str(task.get("status", ""))})
        if len(unfinished) >= MAX_TASKS:
            break
    return Brief(day=day, agenda=agenda, unfinished=unfinished, made_at=now)


def window(now: datetime) -> tuple[datetime, datetime]:
    """Midnight to midnight, in the computer's own time zone."""
    here = now.astimezone()
    start = datetime.combine(here.date(), time.min).astimezone()
    return start, start + timedelta(days=1)
