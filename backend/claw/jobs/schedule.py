"""When a job should next run.

Pure arithmetic over a schedule and a moment, so every awkward case — the
computer was asleep, the clocks changed, the job has never run — can be tested
without waiting for a Tuesday.

Two shapes only, because they cover what people actually ask for and neither
can be got subtly wrong:

    every     "every 30 minutes", counted from the last run
    daily     "at 08:00", in the computer's own time zone

Cron is not here on purpose. A cron line nobody can read is a schedule nobody
can check, and the moment it is wrong the job runs at 3am for a month.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone

EVERY = "every"
DAILY = "daily"
KINDS = (EVERY, DAILY)

#: Below this, a job is a busy loop wearing a schedule.
MIN_MINUTES = 5
MAX_MINUTES = 60 * 24 * 7
TIME_OF_DAY = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")

#: A daily job whose time passed while the computer was off is run late, but
#: only this late. Yesterday's 08:00 report arriving at 23:00 is noise.
CATCH_UP = timedelta(hours=4)


class BadSchedule(ValueError):
    """The schedule cannot be understood, and is not guessed at."""


@dataclass(frozen=True)
class Schedule:
    kind: str
    minutes: int = 0          # for EVERY
    at: str = ""              # for DAILY, "HH:MM"

    @classmethod
    def parse(cls, kind: str, minutes: int | None = None, at: str = "") -> Schedule:
        kind = (kind or "").strip().lower()
        if kind not in KINDS:
            raise BadSchedule(f"a schedule is '{EVERY}' or '{DAILY}', not '{kind}'")
        if kind == EVERY:
            if minutes is None:
                raise BadSchedule("say how many minutes")
            if not MIN_MINUTES <= int(minutes) <= MAX_MINUTES:
                raise BadSchedule(f"between {MIN_MINUTES} minutes and a week, not {minutes} minutes")
            return cls(EVERY, minutes=int(minutes))
        if not TIME_OF_DAY.match((at or "").strip()):
            raise BadSchedule(f"'{at}' is not a time of day like 08:00")
        return cls(DAILY, at=at.strip())

    def describe(self) -> str:
        if self.kind == EVERY:
            if self.minutes % 60 == 0 and self.minutes >= 60:
                hours = self.minutes // 60
                return "every hour" if hours == 1 else f"every {hours} hours"
            return f"every {self.minutes} minutes"
        return f"every day at {self.at}"

    def as_dict(self) -> dict:
        return {"kind": self.kind, "minutes": self.minutes, "at": self.at}


def _at_on(day, at: str) -> datetime:
    hour, minute = (int(part) for part in at.split(":"))
    return datetime.combine(day, time(hour, minute)).astimezone()


def next_run(schedule: Schedule, last_run: datetime | None, now: datetime) -> datetime:
    """The next moment this job should run.

    For `every`, counted from the last run — a job that ran late does not then
    run twice in quick succession to catch up.
    """
    if schedule.kind == EVERY:
        if last_run is None:
            return now
        return last_run + timedelta(minutes=schedule.minutes)
    here = now.astimezone()
    today = _at_on(here.date(), schedule.at)
    if last_run is not None and last_run.astimezone().date() >= here.date():
        return _at_on(here.date() + timedelta(days=1), schedule.at)
    return today if today > here else _at_on(here.date() + timedelta(days=1), schedule.at)


def is_due(schedule: Schedule, last_run: datetime | None, now: datetime) -> bool:
    """Should it run right now?

    A daily job that was missed because the computer was off runs late, within
    `CATCH_UP`, and is otherwise skipped until tomorrow — the alternative is a
    pile of yesterdays arriving the moment someone opens their laptop.
    """
    if schedule.kind == EVERY:
        return last_run is None or now >= last_run + timedelta(minutes=schedule.minutes)
    here = now.astimezone()
    today = _at_on(here.date(), schedule.at)
    if here < today:
        return False
    if here > today + CATCH_UP:
        return False
    return last_run is None or last_run.astimezone() < today
