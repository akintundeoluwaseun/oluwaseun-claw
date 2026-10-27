"""The calendars on this computer.

One `.ics` file per calendar, in the data folder. That format is the reason:
it is the one every calendar program reads, so the file can be opened in
Outlook, imported into Google Calendar, synced by a CalDAV server, backed up,
or read in a text editor. Nothing here is locked inside S-CLAW.

Writes are atomic — a temporary file in the same folder, then a replace — so a
crash or a pulled plug cannot leave a half-written calendar, and every write
keeps the previous version as `.ics.bak`.

This is the local provider. `CalendarSource` is the interface a CalDAV or
hosted-provider implementation would satisfy later; it is deliberately small.
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Protocol

from claw.calendar import ics
from claw.calendar.ics import VEvent
from claw.calendar.reminders import Due, SeenReminders, find_due

SAFE_NAME = re.compile(r"[^A-Za-z0-9 _-]+")
DEFAULT_CALENDAR = "My calendar"
MAX_EVENTS = 20_000


def _moment(value: datetime | date, end: bool = False) -> datetime:
    """A date or datetime as an aware datetime, so two of them can be compared."""
    if isinstance(value, datetime):
        return ics.as_utc(value)
    day = value + timedelta(days=1) if end else value
    return datetime.combine(day, time.min).astimezone().astimezone(timezone.utc)


def overlaps(event: VEvent, start: datetime, end: datetime) -> bool:
    if event.start is None:
        return False
    ev_start = _moment(event.start)
    ev_end = _moment(event.end, end=True) if event.end else ev_start + timedelta(hours=1)
    return ev_start < end and ev_end > start


class CalendarSource(Protocol):
    """What a calendar has to be able to do. A CalDAV server would implement this."""

    def names(self) -> list[str]: ...
    def events(self, calendar: str | None = None) -> list[tuple[str, VEvent]]: ...
    def add(self, event: VEvent, calendar: str | None = None) -> VEvent: ...
    def remove(self, uid: str, calendar: str | None = None) -> VEvent | None: ...


@dataclass
class LocalCalendars:
    """Calendars kept as .ics files in a folder on this computer."""

    folder: Path

    def __post_init__(self) -> None:
        self.folder = Path(self.folder)

    # ---------- files ----------
    def _path(self, calendar: str | None) -> Path:
        name = (calendar or DEFAULT_CALENDAR).strip() or DEFAULT_CALENDAR
        safe = SAFE_NAME.sub("", name).strip() or "calendar"
        return self.folder / f"{safe}.ics"

    def names(self) -> list[str]:
        if not self.folder.is_dir():
            return []
        return sorted(p.stem for p in self.folder.glob("*.ics"))

    def _read(self, path: Path) -> list[VEvent]:
        if not path.is_file():
            return []
        try:
            return ics.parse(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            # A calendar that cannot be read is reported as empty rather than
            # replaced: the file stays exactly as it is, for the person to look at.
            return []

    def _write(self, path: Path, events: list[VEvent]) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        text = ics.write(events, name=path.stem)
        tmp = path.with_suffix(".ics.tmp")
        tmp.write_text(text, encoding="utf-8", newline="")
        if path.exists():
            shutil.copy2(path, path.with_suffix(".ics.bak"))
        os.replace(tmp, path)

    # ---------- the interface ----------
    def events(self, calendar: str | None = None) -> list[tuple[str, VEvent]]:
        paths = [self._path(calendar)] if calendar else sorted(self.folder.glob("*.ics")) \
            if self.folder.is_dir() else []
        out: list[tuple[str, VEvent]] = []
        for path in paths:
            for event in self._read(path):
                out.append((path.stem, event))
                if len(out) >= MAX_EVENTS:
                    return out
        return out

    def between(self, start: datetime, end: datetime,
                calendar: str | None = None) -> list[tuple[str, VEvent]]:
        found = [(name, e) for name, e in self.events(calendar) if overlaps(e, start, end)]
        return sorted(found, key=lambda pair: _moment(pair[1].start))

    def add(self, event: VEvent, calendar: str | None = None) -> VEvent:
        path = self._path(calendar)
        events = self._read(path)
        event.new_uid()
        events.append(event)
        self._write(path, events)
        return event

    def remove(self, uid: str, calendar: str | None = None) -> VEvent | None:
        for path in ([self._path(calendar)] if calendar else sorted(self.folder.glob("*.ics"))):
            events = self._read(path)
            keep = [e for e in events if e.uid != uid]
            if len(keep) != len(events):
                gone = next(e for e in events if e.uid == uid)
                self._write(path, keep)
                return gone
        return None

    # ---------- reminders ----------
    @property
    def seen(self) -> SeenReminders:
        """Which reminders have already been shown. Kept beside the calendars."""
        return SeenReminders(self.folder / "reminders.json")

    def due(self, now: datetime) -> list[Due]:
        """Reminders to show now. Ones whose moment is long past are retired quietly."""
        items, log = self.events(), self.seen
        found, retire = find_due(items, now, log.load())
        log.mark(retire)
        return found

    def mark_shown(self, uids: list[str]) -> int:
        """Record that these were shown, so they are not shown again."""
        pairs = []
        for name, event in self.events():
            if event.uid in uids:
                from claw.calendar.reminders import anchor
                moment = anchor(event)
                if moment is not None:
                    pairs.append((event.uid, moment.isoformat()))
        self.seen.mark(pairs)
        return len(pairs)

    def find(self, uid: str) -> tuple[str, VEvent] | None:
        for name, event in self.events():
            if event.uid == uid:
                return name, event
        return None
