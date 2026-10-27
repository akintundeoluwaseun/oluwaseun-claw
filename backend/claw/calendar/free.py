"""Finding time that is actually free.

Working hours matter more than they look: "the first free hour" is useless if it
is at four in the morning, so the search is bounded by hours a person would
accept and it says which day it landed on.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from claw.calendar.ics import VEvent, as_utc
from claw.calendar.store import _moment


def busy_blocks(events: list[VEvent]) -> list[tuple[datetime, datetime]]:
    blocks = []
    for e in events:
        if e.start is None:
            continue
        start = _moment(e.start)
        end = _moment(e.end, end=True) if e.end else start + timedelta(hours=1)
        blocks.append((start, end))
    return sorted(blocks)


def first_free(events: list[VEvent], minutes: int, search_from: datetime,
               days: int = 14, day_start: time = time(9), day_end: time = time(18),
               weekends: bool = False) -> datetime | None:
    """The earliest start, inside working hours, with nothing already booked."""
    need = timedelta(minutes=minutes)
    blocks = busy_blocks(events)
    local_from = as_utc(search_from).astimezone()
    for offset in range(days + 1):
        day = (local_from + timedelta(days=offset)).date()
        if not weekends and day.weekday() >= 5:
            continue
        window_start = datetime.combine(day, day_start).astimezone()
        window_end = datetime.combine(day, day_end).astimezone()
        cursor = max(window_start, local_from if offset == 0 else window_start)
        # Round up to the next quarter hour: nobody books a meeting at 09:07.
        extra = (-cursor.minute) % 15
        cursor += timedelta(minutes=extra, seconds=-cursor.second, microseconds=-cursor.microsecond)
        while cursor + need <= window_end:
            clash = next((b for b in blocks
                          if b[0] < as_utc(cursor + need) and b[1] > as_utc(cursor)), None)
            if clash is None:
                return cursor
            cursor = clash[1].astimezone()
            extra = (-cursor.minute) % 15
            cursor += timedelta(minutes=extra, seconds=-cursor.second, microseconds=-cursor.microsecond)
    return None
