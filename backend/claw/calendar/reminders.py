"""Telling the person about an event before it happens.

A calendar that cannot do this is a list of dates. The reminder itself lives in
the `.ics` file as a VALARM, so Outlook and Google ring it too; this module is
only about deciding, right now, which ones are due on this computer.

Two decisions worth stating, because neither is obvious:

**A laptop that was switched off does not produce a flood.** Anything whose
moment passed more than `GRACE` ago is marked as seen without being shown. Ten
reminders at once, all for things that already happened, is noise that teaches
people to ignore the real one.

**A repeating event is never guessed at.** RRULE is parsed by nothing here, so
an event carrying one is skipped and said to be skipped, rather than reminded
about on the wrong day.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from claw.calendar.ics import ALL_DAY_HOUR, VEvent

#: How late a reminder may still be shown. After this it is silently retired.
GRACE = timedelta(hours=1)
MAX_SEEN = 5_000


def anchor(event: VEvent) -> datetime | None:
    """The moment a reminder counts from: the start, or 09:00 for an all-day event."""
    if event.start is None:
        return None
    if isinstance(event.start, datetime):
        return event.start.astimezone(timezone.utc) if event.start.tzinfo \
            else event.start.replace(tzinfo=timezone.utc)
    if isinstance(event.start, date):
        local = datetime.combine(event.start, time(hour=ALL_DAY_HOUR))
        return local.astimezone().astimezone(timezone.utc)
    return None


@dataclass(frozen=True)
class Due:
    """One reminder that should be shown now."""

    uid: str
    calendar: str
    summary: str
    location: str
    starts_at: datetime
    all_day: bool
    minutes_until: int

    def as_dict(self) -> dict:
        return {"uid": self.uid, "calendar": self.calendar, "summary": self.summary,
                "location": self.location, "starts_at": self.starts_at.isoformat(),
                "all_day": self.all_day, "minutes_until": self.minutes_until}


def find_due(items: list[tuple[str, VEvent]], now: datetime,
             seen: dict[str, str]) -> tuple[list[Due], list[tuple[str, str]]]:
    """Which reminders to show now, and which to retire without showing.

    Pure on purpose: everything that decides the answer is an argument, so the
    rules can be tested at any date without waiting for one.
    """
    due: list[Due] = []
    retire: list[tuple[str, str]] = []
    for calendar, event in items:
        if event.remind_minutes is None or not event.uid:
            continue
        if event.status.upper() == "CANCELLED":
            continue
        if any(name in {"RRULE", "RDATE"} for name in event.unsupported):
            continue                      # repeating: the occurrences are not known here
        moment = anchor(event)
        if moment is None:
            continue
        key = moment.isoformat()
        if seen.get(event.uid) == key:
            continue
        if now < moment - timedelta(minutes=event.remind_minutes):
            continue                      # not yet
        if now > moment + GRACE:
            retire.append((event.uid, key))   # long past: retired, never shown
            continue
        due.append(Due(
            uid=event.uid, calendar=calendar, summary=event.summary or "(no title)",
            location=event.location, starts_at=moment, all_day=event.all_day,
            minutes_until=round((moment - now).total_seconds() / 60),
        ))
    due.sort(key=lambda d: d.starts_at)
    return due, retire


def phrase(item: Due) -> str:
    """How a reminder reads to a person: 'in 15 minutes', 'now', 'today'."""
    if item.all_day:
        return "today"
    m = item.minutes_until
    if m <= 0:
        return "now"
    if m == 1:
        return "in a minute"
    if m < 60:
        return f"in {m} minutes"
    hours, mins = divmod(m, 60)
    if hours >= 24:
        return "tomorrow" if hours < 48 else f"in {round(hours / 24)} days"
    return f"in {hours}h" if mins == 0 else f"in {hours}h {mins}m"


@dataclass
class SeenReminders:
    """Which reminders have already been shown, kept beside the calendars.

    A JSON file rather than a row in the database: it belongs to the calendar
    folder, it is readable, and losing it costs one repeated reminder.
    """

    path: Path

    def load(self) -> dict[str, str]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}

    def save(self, seen: dict[str, str]) -> None:
        if len(seen) > MAX_SEEN:          # oldest first, by the moment they were for
            seen = dict(sorted(seen.items(), key=lambda kv: kv[1])[-MAX_SEEN:])
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(seen, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.path)

    def mark(self, pairs: list[tuple[str, str]]) -> None:
        if not pairs:
            return
        seen = self.load()
        seen.update(dict(pairs))
        self.save(seen)
