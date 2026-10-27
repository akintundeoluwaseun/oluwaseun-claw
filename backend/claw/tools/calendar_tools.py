"""Calendar tools: see what is on, put something on, take something off.

Two rules shape all of this:

- **A calendar is a set of promises to other people.** Putting something on it,
  or taking something off, is never done quietly: creating asks, cancelling is
  DESTRUCTIVE and asks whatever the settings say.
- **Never invent a time.** If a request does not say which day, or which year,
  the tool refuses and asks rather than picking the next plausible Tuesday.

Times are typed the way people write them — "2026-11-03 14:30" — and are read in
this computer's own time zone, then stored as UTC so the file is unambiguous.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from pydantic import Field, field_validator

from claw.agent.schemas import Capability
from claw.brief import assemble, window
from claw.calendar import ics
from claw.calendar.free import first_free
from claw.calendar.ics import VEvent
from claw.calendar.store import DEFAULT_CALENDAR, LocalCalendars, _moment
from claw.permissions.policy import RiskLevel
from claw.tools.base import ToolArgs, ToolContext, ToolError, ToolRegistry, ToolResult, ToolSpec

MAX_LIST = 100
MAX_DAYS = 400


def calendars(ctx: ToolContext) -> LocalCalendars:
    return LocalCalendars(ctx.data_dir / "calendars")


def _parse_when(text: str, what: str) -> datetime:
    """A date and time, written the way a person writes it, in local time."""
    raw = text.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M", "%d-%m-%Y %H:%M"):
        try:
            return datetime.strptime(raw, fmt).astimezone()
        except ValueError:
            continue
    raise ToolError(
        f"'{text}' is not a date and time S-CLAW can be sure about for the {what}. "
        'Write it as "2026-11-03 14:30", with the year.')


def _parse_day(text: str, what: str) -> date:
    raw = text.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ToolError(f"'{text}' is not a date S-CLAW can be sure about for the {what}. "
                    'Write it as "2026-11-03", with the year.')


def _describe(name: str, event: VEvent) -> str:
    when = event.start
    if event.all_day:
        line = f"{when:%a %d %b %Y} (all day)"
    else:
        local = _moment(when).astimezone()
        end = f"–{_moment(event.end).astimezone():%H:%M}" if event.end else ""
        line = f"{local:%a %d %b %Y %H:%M}{end}"
    bits = [f"{line}  {event.summary or '(no title)'}"]
    if event.location:
        bits.append(f"at {event.location}")
    if name != DEFAULT_CALENDAR:
        bits.append(f"[{name}]")
    if event.unsupported:
        # Saying so matters: the file says this repeats, and S-CLAW is showing one of them.
        bits.append("(repeats — S-CLAW shows this occurrence only)")
    return "  ".join(bits)


# ---------- list_events ----------
class ListArgs(ToolArgs):
    from_date: str | None = Field(default=None, description='First day, e.g. "2026-11-03". Today if left out.')
    days: int = Field(default=7, ge=1, le=MAX_DAYS, description="How many days to cover")
    calendar: str | None = Field(default=None, max_length=80, description="One calendar, or all of them")


async def list_events(args: ListArgs, ctx: ToolContext) -> ToolResult:
    start_day = _parse_day(args.from_date, "start") if args.from_date else datetime.now().date()
    start = datetime.combine(start_day, time.min).astimezone()
    end = start + timedelta(days=args.days)
    store = calendars(ctx)
    found = await asyncio.to_thread(store.between, start, end, args.calendar)
    lines = [_describe(name, e) for name, e in found[:MAX_LIST]]
    data = {
        "from": start_day.isoformat(), "days": args.days,
        "calendars": store.names(), "count": len(found),
        "events": [{"uid": e.uid, "summary": e.summary, "calendar": name,
                    "start": e.start.isoformat() if e.start else None,
                    "end": e.end.isoformat() if e.end else None,
                    "all_day": e.all_day, "location": e.location,
                    "repeats": bool(e.unsupported)}
                   for name, e in found[:MAX_LIST]],
    }
    if not store.names():
        return ToolResult(True, "There are no calendars on this computer yet.", data, verified=True)
    word = "event" if len(found) == 1 else "events"
    return ToolResult(True, f"{len(found)} {word} between {start_day:%d %b} and {(end - timedelta(days=1)).date():%d %b %Y}.",
                      data, verified=True, untrusted_text="\n".join(lines))


# ---------- create_event ----------
class CreateArgs(ToolArgs):
    title: str = Field(min_length=1, max_length=200)
    start: str = Field(description='When it starts, e.g. "2026-11-03 14:30"')
    minutes: int = Field(default=60, ge=5, le=60 * 24, description="How long it lasts")
    location: str = Field(default="", max_length=200)
    notes: str = Field(default="", max_length=2000)
    calendar: str | None = Field(default=None, max_length=80)
    all_day: bool = Field(default=False, description='If true, "start" is a date and the time is ignored')
    remind_minutes: int | None = Field(
        default=10, ge=0, le=60 * 24 * 28,
        description="Minutes before it starts to be reminded; null for no reminder. "
                    "An all-day event is counted from 09:00 on the day.")


def check_create(args: CreateArgs, ctx: ToolContext) -> None:
    if args.all_day:
        _parse_day(args.start, "start")
    else:
        _parse_when(args.start, "start")


async def create_event(args: CreateArgs, ctx: ToolContext) -> ToolResult:
    store = calendars(ctx)
    if args.all_day:
        day = _parse_day(args.start, "start")
        event = VEvent(summary=args.title, start=day, end=day + timedelta(days=1),
                       location=args.location, description=args.notes,
                       remind_minutes=args.remind_minutes)
        window = (datetime.combine(day, time.min).astimezone(),
                  datetime.combine(day + timedelta(days=1), time.min).astimezone())
    else:
        start = _parse_when(args.start, "start")
        end = start + timedelta(minutes=args.minutes)
        event = VEvent(summary=args.title, start=start, end=end,
                       location=args.location, description=args.notes,
                       remind_minutes=args.remind_minutes)
        window = (start, end)

    clashes = await asyncio.to_thread(store.between, window[0], window[1], None)
    saved = await asyncio.to_thread(store.add, event, args.calendar)

    # Verified by reading it back out of the file, not by the write returning.
    back = await asyncio.to_thread(store.find, saved.uid)
    ok = back is not None and back[1].summary == args.title
    remind_note = ""
    if args.remind_minutes is not None and ok:
        remind_note = (" You will be reminded when it starts."
                       if args.remind_minutes == 0 else
                       f" You will be reminded {args.remind_minutes} minutes before.")
    clash_note = ""
    if clashes:
        names = ", ".join(f"'{e.summary or 'untitled'}'" for _, e in clashes[:3])
        clash_note = f" This overlaps {len(clashes)} thing(s) already there: {names}."
    return ToolResult(
        ok,
        f"Put '{args.title}' on {back[0] if back else args.calendar or DEFAULT_CALENDAR} "
        f"for {_describe(back[0], back[1]).split('  ')[0] if back else args.start}.{remind_note}{clash_note}"
        if ok else "The event was written but could not be read back.",
        {"uid": saved.uid, "calendar": back[0] if back else None,
         "remind_minutes": args.remind_minutes,
         "file": str((ctx.data_dir / "calendars").resolve()),
         "clashes": [{"summary": e.summary, "uid": e.uid} for _, e in clashes]},
        verified=ok,
    )


# ---------- daily_brief ----------
class BriefArgs(ToolArgs):
    pass


async def daily_brief(args: BriefArgs, ctx: ToolContext) -> ToolResult:
    """What today looks like: the calendar, and work that did not finish."""
    now = datetime.now(timezone.utc)
    store = calendars(ctx)
    start, end = window(now)
    events = await asyncio.to_thread(store.between, start, end, None)
    tasks = ctx.recent_tasks(50) if ctx.recent_tasks else []
    brief = assemble(events, tasks, now)
    return ToolResult(
        True, brief.headline(), brief.as_dict(), verified=True,
        # The agenda is the person's own calendar, but a summary or a location can
        # hold anything a meeting invitation put there.
        untrusted_text=brief.as_text(),
    )


# ---------- cancel_event ----------
class CancelArgs(ToolArgs):
    uid: str = Field(min_length=1, max_length=300, description="The event's id, from list_events")


def check_cancel(args: CancelArgs, ctx: ToolContext) -> None:
    if calendars(ctx).find(args.uid) is None:
        raise ToolError(f"No event on this computer has the id '{args.uid}'. "
                        "Use list_events first and take the id from there.")


async def cancel_event(args: CancelArgs, ctx: ToolContext) -> ToolResult:
    store = calendars(ctx)
    found = await asyncio.to_thread(store.find, args.uid)
    if found is None:
        raise ToolError(f"No event on this computer has the id '{args.uid}'.")
    name, event = found
    removed = await asyncio.to_thread(store.remove, args.uid, name)
    still_there = await asyncio.to_thread(store.find, args.uid)
    ok = removed is not None and still_there is None
    return ToolResult(
        ok,
        f"Took '{event.summary or 'untitled'}' off {name}. The previous version of the "
        f"calendar is kept beside it as {name}.ics.bak." if ok
        else f"'{event.summary}' could not be removed.",
        {"uid": args.uid, "calendar": name, "summary": event.summary}, verified=ok,
    )


# ---------- find_free_time ----------
class FreeArgs(ToolArgs):
    minutes: int = Field(default=60, ge=5, le=60 * 12, description="How long you need")
    from_date: str | None = Field(default=None, description="First day to consider; today if left out")
    days: int = Field(default=14, ge=1, le=90)
    earliest: int = Field(default=9, ge=0, le=23, description="Earliest hour of the day to suggest")
    latest: int = Field(default=18, ge=1, le=24, description="Latest hour it may end")
    include_weekends: bool = False


async def find_free_time(args: FreeArgs, ctx: ToolContext) -> ToolResult:
    if args.latest <= args.earliest:
        raise ToolError("The latest hour has to be after the earliest one.")
    start_day = _parse_day(args.from_date, "start") if args.from_date else datetime.now().date()
    search_from = max(datetime.now().astimezone(),
                      datetime.combine(start_day, time.min).astimezone())
    store = calendars(ctx)
    pairs = await asyncio.to_thread(store.between, search_from,
                                    search_from + timedelta(days=args.days + 1), None)
    slot = first_free([e for _, e in pairs], args.minutes, search_from, days=args.days,
                      day_start=time(args.earliest), day_end=time(args.latest),
                      weekends=args.include_weekends)
    if slot is None:
        return ToolResult(True,
                          f"No free {args.minutes}-minute slot between {args.earliest}:00 and "
                          f"{args.latest}:00 in the next {args.days} days.",
                          {"found": False, "busy_events": len(pairs)}, verified=True)
    return ToolResult(True, f"Free: {slot:%A %d %B %Y at %H:%M} for {args.minutes} minutes.",
                      {"found": True, "start": slot.isoformat(), "minutes": args.minutes,
                       "busy_events": len(pairs)}, verified=True)


def register_calendar_tools(reg: ToolRegistry) -> None:
    reg.register(ToolSpec(
        "daily_brief",
        "What today looks like: everything in the calendar for today, and any task "
        "from the last few days that did not finish. Says what it cannot see.",
        Capability.FILES, RiskLevel.READ_ONLY, BriefArgs, daily_brief))
    F, R, W = Capability.FILES, RiskLevel.READ_ONLY, RiskLevel.LOCAL_WRITE
    reg.register(ToolSpec("list_events", "See what is on the calendar over a range of days.",
                          F, R, ListArgs, list_events))
    reg.register(ToolSpec("create_event", "Put something on the calendar.",
                          F, W, CreateArgs, create_event, precheck=check_create))
    # Taking something off a calendar is a promise withdrawn; it sits at the
    # approval floor that settings cannot lower.
    reg.register(ToolSpec("cancel_event", "Take an event off the calendar.",
                          F, RiskLevel.DESTRUCTIVE, CancelArgs, cancel_event, precheck=check_cancel))
    reg.register(ToolSpec("find_free_time", "Find the next free slot of a given length.",
                          F, R, FreeArgs, find_free_time))
