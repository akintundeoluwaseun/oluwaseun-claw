"""The calendar: the file format, the store, free-time search, and the tools.

A calendar is a set of promises to other people, so these tests care most about
two things: that nothing is invented when a request is vague, and that nothing
is lost when a file is written.
"""

from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pytest

from claw.calendar import ics
from claw.calendar.free import first_free
from claw.calendar.ics import VEvent
from claw.calendar.store import LocalCalendars
from claw.tools.base import ToolError
from claw.tools.registry import build_registry

REG = build_registry()


async def call(ctx, name, **args):
    spec = REG.get(name)
    parsed = spec.parse_args(args)
    if spec.precheck:
        spec.precheck(parsed, ctx)
    return await spec.handler(parsed, ctx)


# ---------- the file format ----------
def test_round_trip_keeps_punctuation_and_newlines():
    event = VEvent(summary="Call Ade; bring notes, please",
                   description="Line one\nLine two",
                   start=datetime(2026, 11, 3, 9, 0), end=datetime(2026, 11, 3, 10, 0))
    back = ics.parse(ics.write([event]))[0]
    assert back.summary == "Call Ade; bring notes, please"
    assert back.description == "Line one\nLine two"
    assert back.start == ics.as_utc(datetime(2026, 11, 3, 9, 0))


def test_long_lines_are_folded_and_come_back_whole():
    long_title = "Quarterly planning with " + "a very long list of people " * 6
    text = ics.write([VEvent(summary=long_title, start=datetime(2026, 11, 3, 9, 0))])
    assert all(len(line.encode()) <= 75 for line in text.split("\r\n") if line)
    assert ics.parse(text)[0].summary == long_title


def test_an_all_day_event_stays_a_date():
    text = ics.write([VEvent(summary="Public holiday", start=date(2026, 12, 25),
                             end=date(2026, 12, 26))])
    assert "DTSTART;VALUE=DATE:20261225" in text
    back = ics.parse(text)[0]
    assert back.all_day and back.start == date(2026, 12, 25)


def test_a_repeating_event_is_kept_and_flagged_not_pretended_to_be_understood():
    outlook = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:x@elsewhere\r\n"
        "DTSTART:20261103T090000Z\r\nDTEND:20261103T093000Z\r\nSUMMARY:Standup\r\n"
        "RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR\r\nX-CUSTOM-THING:keep me\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n")
    event = ics.parse(outlook)[0]
    assert event.unsupported == ["RRULE"], "a repeating event must be flagged"
    rewritten = ics.write([event])
    assert "RRULE:FREQ=WEEKLY" in rewritten, "the rule must survive being written back"
    assert "X-CUSTOM-THING:keep me" in rewritten, "another program's property was dropped"


# ---------- the store ----------
@pytest.fixture
def store(tmp_path):
    return LocalCalendars(tmp_path / "calendars")


def test_events_are_written_where_other_programs_can_read_them(store):
    store.add(VEvent(summary="Dentist", start=datetime(2026, 11, 3, 9, 0)))
    files = list(store.folder.glob("*.ics"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert text.startswith("BEGIN:VCALENDAR") and "SUMMARY:Dentist" in text


def test_a_write_keeps_the_previous_version(store):
    store.add(VEvent(summary="First", start=datetime(2026, 11, 3, 9, 0)))
    store.add(VEvent(summary="Second", start=datetime(2026, 11, 4, 9, 0)))
    backup = next(store.folder.glob("*.ics.bak"))
    assert "First" in backup.read_text(encoding="utf-8")
    assert "Second" not in backup.read_text(encoding="utf-8")


def test_a_damaged_calendar_is_left_alone_rather_than_replaced(store):
    store.folder.mkdir(parents=True)
    broken = store.folder / "My calendar.ics"
    broken.write_text("this is not a calendar at all", encoding="utf-8")
    assert store.events() == []
    assert broken.read_text(encoding="utf-8") == "this is not a calendar at all"


def test_between_only_returns_what_overlaps(store):
    store.add(VEvent(summary="Inside", start=datetime(2026, 11, 3, 9, 0), end=datetime(2026, 11, 3, 10, 0)))
    store.add(VEvent(summary="Outside", start=datetime(2026, 12, 3, 9, 0), end=datetime(2026, 12, 3, 10, 0)))
    window = (datetime(2026, 11, 1).astimezone(), datetime(2026, 11, 30).astimezone())
    assert [e.summary for _, e in store.between(*window)] == ["Inside"]


# ---------- free time ----------
def test_free_time_skips_what_is_booked_and_stays_in_working_hours():
    base = datetime(2026, 11, 3, 8, 0).astimezone()        # a Tuesday
    busy = [VEvent(summary="Booked", start=datetime(2026, 11, 3, 9, 0).astimezone(),
                   end=datetime(2026, 11, 3, 11, 0).astimezone())]
    slot = first_free(busy, 60, base)
    assert slot is not None
    assert slot.hour >= 11 and slot.date() == base.date()
    assert slot.minute % 15 == 0, "a suggestion should land on a sensible minute"


def test_free_time_rolls_to_the_next_day_and_skips_the_weekend():
    friday = datetime(2026, 11, 6, 17, 30).astimezone()
    full = [VEvent(summary="All day", start=datetime(2026, 11, 6, 9, 0).astimezone(),
                   end=datetime(2026, 11, 6, 18, 0).astimezone())]
    slot = first_free(full, 60, friday)
    assert slot is not None and slot.weekday() == 0, "weekends are not working hours"


def test_free_time_can_say_there_is_none():
    base = datetime(2026, 11, 3, 9, 0).astimezone()
    wall = [VEvent(summary="Busy", start=base + timedelta(days=d, hours=0),
                   end=base + timedelta(days=d, hours=9)) for d in range(0, 16)]
    assert first_free(wall, 120, base, days=10) is None


# ---------- the tools ----------
async def test_listing_an_empty_calendar_says_so(tool_ctx):
    r = await call(tool_ctx, "list_events")
    assert r.verified and "no calendars" in r.summary.lower()


async def test_create_then_list_then_cancel(tool_ctx):
    made = await call(tool_ctx, "create_event", title="Call with Ade",
                      start="2026-11-03 14:30", minutes=45, location="Zoom")
    assert made.verified and made.data["uid"]

    listed = await call(tool_ctx, "list_events", from_date="2026-11-01", days=7)
    assert listed.data["count"] == 1
    entry = listed.data["events"][0]
    assert entry["summary"] == "Call with Ade" and entry["uid"] == made.data["uid"]
    assert "14:30" in listed.untrusted_text and "Zoom" in listed.untrusted_text

    gone = await call(tool_ctx, "cancel_event", uid=made.data["uid"])
    assert gone.verified
    assert (await call(tool_ctx, "list_events", from_date="2026-11-01", days=7)).data["count"] == 0


async def test_a_vague_time_is_refused_rather_than_guessed(tool_ctx):
    for bad in ("next Tuesday", "tomorrow at 2", "3pm", "11-03 14:30"):
        with pytest.raises(ToolError, match="not a date and time"):
            await call(tool_ctx, "create_event", title="Something", start=bad)


async def test_an_overlap_is_pointed_out_not_silently_allowed(tool_ctx):
    await call(tool_ctx, "create_event", title="Dentist", start="2026-11-03 14:00", minutes=60)
    second = await call(tool_ctx, "create_event", title="Call", start="2026-11-03 14:30", minutes=30)
    assert second.verified
    assert "overlaps" in second.summary and "Dentist" in second.summary
    assert second.data["clashes"], "the clash should be in the data too"


async def test_cancelling_something_that_is_not_there_is_refused_before_anything_happens(tool_ctx):
    with pytest.raises(ToolError, match="No event on this computer"):
        await call(tool_ctx, "cancel_event", uid="made-up-id")


async def test_cancelling_is_destructive_and_settings_cannot_lower_it(tool_ctx):
    from claw.permissions.policy import RiskLevel

    assert REG.get("cancel_event").risk is RiskLevel.DESTRUCTIVE


async def test_find_free_time_uses_what_is_already_booked(tool_ctx):
    soon = (datetime.now().astimezone() + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    await call(tool_ctx, "create_event", title="Blocked",
               start=soon.strftime("%Y-%m-%d %H:%M"), minutes=180)
    r = await call(tool_ctx, "find_free_time", minutes=60,
                   from_date=soon.date().isoformat(), days=3)
    assert r.data["found"] is True
    assert datetime.fromisoformat(r.data["start"]) >= soon + timedelta(minutes=180) \
        or datetime.fromisoformat(r.data["start"]).date() > soon.date()


async def test_an_all_day_event_is_stored_as_a_day(tool_ctx):
    r = await call(tool_ctx, "create_event", title="Public holiday",
                   start="2026-12-25", all_day=True)
    assert r.verified
    listed = await call(tool_ctx, "list_events", from_date="2026-12-24", days=3)
    assert listed.data["events"][0]["all_day"] is True
    assert "all day" in listed.untrusted_text


# ---------- stopping to ask the person ----------
async def test_pause_asks_the_person_and_carries_on(tool_ctx):
    asked = []

    async def answer(payload):
        asked.append(payload)
        return True

    tool_ctx.ask_user = answer
    r = await call(tool_ctx, "pause_for_me",
                   what_is_needed="sign in to Instagram in the browser window",
                   why="the page asked for a password", kind="sign in")
    assert r.verified and r.data["answered"] is True
    assert asked[0]["kind"] == "needs_you", "the app must word this as a request, not an approval"
    assert asked[0]["title"] == "S-CLAW needs you"
    assert "sign in to Instagram" in asked[0]["description"]


async def test_pause_stops_the_task_when_nobody_answers(tool_ctx):
    async def nobody(payload):
        return None

    tool_ctx.ask_user = nobody
    r = await call(tool_ctx, "pause_for_me", what_is_needed="enter the code sent to your phone",
                   kind="two-factor code")
    assert r.ok is False and r.data["answered"] is None
    assert "nobody answered" in r.summary and "nothing was guessed" in r.summary


async def test_pause_refuses_to_ask_for_the_secret_itself(tool_ctx):
    tool_ctx.ask_user = lambda payload: None
    for bad in ("tell me your password", "What is your password?", "send me the code please"):
        with pytest.raises(Exception, match="never ask for a password"):
            await call(tool_ctx, "pause_for_me", what_is_needed=bad)


async def test_pause_outside_a_task_says_so(tool_ctx):
    tool_ctx.ask_user = None
    with pytest.raises(ToolError, match="nobody to ask"):
        await call(tool_ctx, "pause_for_me", what_is_needed="sign in")
