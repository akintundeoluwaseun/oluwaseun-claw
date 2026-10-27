"""Reading and writing the part of the iCalendar format a calendar actually needs.

Deliberately a subset of RFC 5545 — VEVENT with the fields people use — written
here rather than pulled in, because the alternatives are either a dependency in
a signed Windows installer or a licence question, and this part of the format is
small and well specified.

What it handles: line folding and unfolding, the escaping rules, all-day events
(VALUE=DATE), timed events stored in UTC, and unknown properties, which are kept
on the way through so a file written by Outlook or Google survives a round trip
through S-CLAW with everything it came in with.

What it does NOT handle, and says so rather than guessing: recurrence (RRULE),
attendees, alarms, and named time zones. A recurring event read from another
program is reported as the single occurrence it describes and is never rewritten.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

#: Properties this module understands. Everything else is carried through untouched.
KNOWN = {"UID", "DTSTAMP", "DTSTART", "DTEND", "SUMMARY", "LOCATION", "DESCRIPTION", "STATUS"}
UNSUPPORTED = {"RRULE", "RDATE", "EXDATE"}

#: A reminder, in RFC 5545, is a VALARM block inside the event. Only the plain
#: "tell me N before it starts" kind is understood; anything else (an alarm that
#: sends mail, runs a program, or fires at a fixed moment unrelated to the start)
#: is carried through untouched and flagged, because a reminder that is quietly
#: turned into a different reminder is worse than one that is left alone.
ALARM_OK = {"ACTION", "TRIGGER", "DESCRIPTION", "SUMMARY", "UID", "X-WR-ALARMUID", "ATTACH"}
ALARM_ACTIONS = {"DISPLAY", "AUDIO"}
_DURATION = re.compile(
    r"^(?P<sign>[+-])?P(?:(?P<w>\d+)W)?(?:(?P<d>\d+)D)?"
    r"(?:T(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?(?:(?P<s>\d+)S)?)?$", re.I)
#: 09:00 on the day, for an all-day event. Midnight minus ten minutes would ring
#: at ten to midnight the night before, which nobody means by "remind me".
ALL_DAY_HOUR = 9


def parse_trigger(value: str, params: dict[str, str]) -> int | None:
    """A TRIGGER as minutes before the event starts, or None if it is not that.

    Returns a negative number for an alarm set to fire *after* the start, so the
    sign always means the same thing.
    """
    if params.get("VALUE", "DURATION").upper() != "DURATION":
        return None                     # an absolute DATE-TIME trigger
    if params.get("RELATED", "START").upper() != "START":
        return None                     # relative to the end, which this does not model
    m = _DURATION.match(value.strip())
    if not m or not any(m.group(k) for k in ("w", "d", "h", "m", "s")):
        return None
    minutes = (int(m.group("w") or 0) * 7 * 24 * 60 + int(m.group("d") or 0) * 24 * 60
               + int(m.group("h") or 0) * 60 + int(m.group("m") or 0)
               + round(int(m.group("s") or 0) / 60))
    return minutes if m.group("sign") == "-" else -minutes


def fmt_trigger(minutes: int) -> str:
    """Minutes before the start, as a TRIGGER duration."""
    sign = "-" if minutes >= 0 else ""
    left = abs(minutes)
    days, rest = divmod(left, 24 * 60)
    hours, mins = divmod(rest, 60)
    body = (f"{days}D" if days else "") + "T" + (f"{hours}H" if hours else "") + f"{mins}M"
    return f"{sign}P{body}"

_ESCAPES = ((",", "\\,"), (";", "\\;"), ("\n", "\\n"))


def escape(text: str) -> str:
    out = text.replace("\\", "\\\\")
    for raw, esc in _ESCAPES:
        out = out.replace(raw, esc)
    return out


def unescape(text: str) -> str:
    out, i = [], 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            nxt = text[i + 1]
            out.append({"n": "\n", "N": "\n", ",": ",", ";": ";", "\\": "\\"}.get(nxt, nxt))
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def fold(line: str) -> list[str]:
    """RFC 5545 content lines are folded at 75 octets, continuing with a space."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return [line]
    out, chunk = [], bytearray()
    for ch in line:
        encoded = ch.encode("utf-8")
        limit = 75 if not out else 74          # continuation lines carry a leading space
        if len(chunk) + len(encoded) > limit:
            out.append(chunk.decode("utf-8"))
            chunk = bytearray()
        chunk += encoded
    if chunk:
        out.append(chunk.decode("utf-8"))
    return [out[0]] + [" " + part for part in out[1:]]


def unfold(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return [ln for ln in lines if ln.strip()]


def as_utc(when: datetime) -> datetime:
    """Any datetime, as UTC. A naive one is taken to be this computer's local time."""
    if when.tzinfo is None:
        return when.astimezone().astimezone(timezone.utc)
    return when.astimezone(timezone.utc)


def fmt_datetime(when: datetime) -> str:
    return as_utc(when).strftime("%Y%m%dT%H%M%SZ")


def fmt_date(day: date) -> str:
    return day.strftime("%Y%m%d")


def parse_value(value: str, params: dict[str, str]) -> datetime | date:
    if params.get("VALUE") == "DATE" or (len(value) == 8 and "T" not in value):
        return datetime.strptime(value, "%Y%m%d").date()
    if value.endswith("Z"):
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    # A local time with no zone: read as this computer's, which is what the
    # program that wrote it almost certainly meant.
    return datetime.strptime(value, "%Y%m%dT%H%M%S").astimezone()


@dataclass
class VEvent:
    uid: str = ""
    summary: str = ""
    start: datetime | date | None = None
    end: datetime | date | None = None
    location: str = ""
    description: str = ""
    status: str = ""
    #: properties this module does not understand, kept so a round trip loses nothing
    extra: list[str] = field(default_factory=list)
    #: names of properties that make this event more than it appears (RRULE and friends)
    unsupported: list[str] = field(default_factory=list)
    #: minutes before the start to be reminded; None means no reminder
    remind_minutes: int | None = None

    @property
    def all_day(self) -> bool:
        return isinstance(self.start, date) and not isinstance(self.start, datetime)

    def new_uid(self) -> str:
        self.uid = self.uid or f"{uuid.uuid4()}@s-claw"
        return self.uid

    def to_lines(self) -> list[str]:
        self.new_uid()
        out = ["BEGIN:VEVENT", f"UID:{self.uid}", f"DTSTAMP:{fmt_datetime(datetime.now(timezone.utc))}"]
        if self.all_day:
            out.append(f"DTSTART;VALUE=DATE:{fmt_date(self.start)}")
            if self.end:
                out.append(f"DTEND;VALUE=DATE:{fmt_date(self.end)}")
        else:
            out.append(f"DTSTART:{fmt_datetime(self.start)}")
            if self.end:
                out.append(f"DTEND:{fmt_datetime(self.end)}")
        out.append(f"SUMMARY:{escape(self.summary)}")
        if self.location:
            out.append(f"LOCATION:{escape(self.location)}")
        if self.description:
            out.append(f"DESCRIPTION:{escape(self.description)}")
        if self.status:
            out.append(f"STATUS:{self.status}")
        if self.remind_minutes is not None:
            # Written as a real VALARM, so Outlook, Google and a CalDAV server all
            # ring it too - the reminder belongs to the event, not to S-CLAW.
            out += ["BEGIN:VALARM", "ACTION:DISPLAY",
                    f"TRIGGER:{fmt_trigger(self.remind_minutes)}",
                    f"DESCRIPTION:{escape(self.summary or 'Reminder')}", "END:VALARM"]
        out += self.extra
        out.append("END:VEVENT")
        folded: list[str] = []
        for line in out:
            folded += fold(line)
        return folded


def _split(line: str) -> tuple[str, dict[str, str], str]:
    head, _, value = line.partition(":")
    name, *param_parts = head.split(";")
    params = {}
    for part in param_parts:
        k, _, v = part.partition("=")
        params[k.upper()] = v
    return name.upper(), params, value


def _read_alarm(block: list[str]) -> int | None:
    """Minutes before the start, if this VALARM is the plain kind. Otherwise None."""
    minutes = None
    for line in block:
        name, params, value = _split(line)
        if name == "TRIGGER":
            minutes = parse_trigger(value, params)
            if minutes is None:
                return None
        elif name == "ACTION":
            if value.strip().upper() not in ALARM_ACTIONS:
                return None             # e-mail or a program: not ours to reinterpret
        elif name not in ALARM_OK:
            return None
    return minutes


def parse(text: str) -> list[VEvent]:
    events: list[VEvent] = []
    current: VEvent | None = None
    alarm: list[str] | None = None
    for line in unfold(text):
        upper = line.upper()
        if upper.startswith("BEGIN:VEVENT"):
            current = VEvent()
            alarm = None
            continue
        # A VALARM is a block of its own inside the event. Without this, its
        # DESCRIPTION ("Reminder") overwrote the event's own description, and
        # every alarm from Outlook or Google quietly rewrote the event.
        if upper.startswith("BEGIN:VALARM"):
            alarm = []
            continue
        if upper.startswith("END:VALARM"):
            if current is not None and alarm is not None:
                minutes = _read_alarm(alarm)
                if minutes is not None and current.remind_minutes is None:
                    current.remind_minutes = minutes
                else:
                    # Kept exactly as it came, and flagged, rather than turned into
                    # something S-CLAW happens to understand.
                    current.extra += ["BEGIN:VALARM", *alarm, "END:VALARM"]
                    current.unsupported.append("VALARM")
            alarm = None
            continue
        if alarm is not None:
            alarm.append(line)
            continue
        if upper.startswith("END:VEVENT"):
            if current is not None and current.start is not None:
                events.append(current)
            current = None
            continue
        if current is None:
            continue
        name, params, value = _split(line)
        if name in UNSUPPORTED:
            # Kept, so writing the file back does not quietly drop it, but flagged
            # so nothing claims to understand a repeating event that it does not.
            current.unsupported.append(name)
            current.extra.append(line)
        elif name == "UID":
            current.uid = value
        elif name == "SUMMARY":
            current.summary = unescape(value)
        elif name == "LOCATION":
            current.location = unescape(value)
        elif name == "DESCRIPTION":
            current.description = unescape(value)
        elif name == "STATUS":
            current.status = value.upper()
        elif name == "DTSTART":
            current.start = parse_value(value, params)
        elif name == "DTEND":
            current.end = parse_value(value, params)
        elif name == "DTSTAMP":
            pass                                   # rewritten on every save
        else:
            current.extra.append(line)
    return events


def write(events: list[VEvent], name: str = "S-CLAW") -> str:
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//S-CLAW//EN", "CALSCALE:GREGORIAN"]
    lines += fold(f"X-WR-CALNAME:{escape(name)}")
    for event in sorted(events, key=lambda e: _sort_key(e.start)):
        lines += event.to_lines()
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def _sort_key(value: datetime | date | None) -> datetime:
    if isinstance(value, datetime):
        return as_utc(value)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    return datetime.max.replace(tzinfo=timezone.utc)
