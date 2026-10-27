"""Being told before it happens.

A calendar that cannot remind you is a list of dates. These tests pin the two
rules that are easy to get quietly wrong: a reminder fires once, and a laptop
that was switched off for a week does not produce a pile of reminders for
things that already happened.

Everything here is decided from arguments, never from the real clock, so the
rules can be tested at any date.
"""

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from claw.api.app import create_app
from claw.calendar import ics
from claw.calendar.ics import VEvent, fmt_trigger, parse_trigger
from claw.calendar.reminders import GRACE, anchor, find_due, phrase
from claw.calendar.store import LocalCalendars

TOKEN = "t" * 40
NOW = datetime(2026, 11, 3, 13, 0, tzinfo=timezone.utc)


def ev(minutes_from_now, remind=10, **kw):
    return VEvent(uid=kw.pop("uid", "e1@x"), summary=kw.pop("summary", "Site visit"),
                  start=NOW + timedelta(minutes=minutes_from_now), remind_minutes=remind, **kw)


# ---------- the TRIGGER line ----------
@pytest.mark.parametrize("text,minutes", [
    ("-PT15M", 15), ("-PT1H", 60), ("-P1D", 1440), ("-P1DT2H30M", 1590),
    ("-PT0S", 0), ("PT10M", -10),       # a positive trigger fires after the start
])
def test_a_trigger_reads_as_minutes_before_the_start(text, minutes):
    assert parse_trigger(text, {}) == minutes


@pytest.mark.parametrize("text,params", [
    ("20261103T140000Z", {"VALUE": "DATE-TIME"}),   # an absolute moment
    ("-PT15M", {"RELATED": "END"}),                 # counted from the end
    ("tomorrow", {}),                               # not a duration at all
])
def test_a_trigger_this_does_not_model_is_refused_rather_than_guessed(text, params):
    assert parse_trigger(text, params) is None


@pytest.mark.parametrize("minutes", [0, 5, 10, 60, 90, 1440, 2910])
def test_a_reminder_survives_being_written_and_read_back(minutes):
    event = VEvent(summary="Payroll", start=NOW, remind_minutes=minutes)
    back = ics.parse(ics.write([event]))[0]
    assert back.remind_minutes == minutes, f"{fmt_trigger(minutes)} did not come back the same"


def test_an_alarm_of_a_kind_claw_does_not_understand_is_kept_untouched():
    """An e-mail alarm is not turned into a pop-up on this computer."""
    raw = ("BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:a@x\nDTSTART:20261103T140000Z\n"
           "SUMMARY:Payroll\nDESCRIPTION:the real description\n"
           "BEGIN:VALARM\nACTION:EMAIL\nTRIGGER:-PT15M\nATTENDEE:mailto:a@b.c\n"
           "DESCRIPTION:mail body\nEND:VALARM\nEND:VEVENT\nEND:VCALENDAR")
    event = ics.parse(raw)[0]
    assert event.remind_minutes is None
    assert "VALARM" in event.unsupported
    # The bug this pins: the alarm's own DESCRIPTION used to overwrite the event's.
    assert event.description == "the real description"
    assert "ACTION:EMAIL" in "\n".join(event.extra), "the alarm was dropped instead of kept"


# ---------- which reminders are due ----------
def test_a_reminder_is_due_inside_its_window_and_not_before():
    assert find_due([("My calendar", ev(8))], NOW, {})[0], "8 minutes out, 10-minute reminder"
    assert not find_due([("My calendar", ev(11))], NOW, {})[0], "11 minutes out is not yet"


def test_a_reminder_is_shown_once():
    item = ev(8)
    due, _ = find_due([("My calendar", item)], NOW, {})
    key = anchor(item).isoformat()
    again, _ = find_due([("My calendar", item)], NOW, {item.uid: key})
    assert due and not again


def test_a_laptop_that_was_off_does_not_produce_a_pile_of_old_reminders():
    old = [("My calendar", ev(-60 * 24 * d, uid=f"old{d}@x")) for d in range(1, 6)]
    due, retire = find_due(old, NOW, {})
    assert due == [], "reminders for things that already happened were shown"
    assert len(retire) == 5, "they must be retired, or they wait to ambush the next poll"


def test_something_that_has_just_started_is_still_worth_saying():
    due, _ = find_due([("My calendar", ev(-1))], NOW, {})
    assert due and due[0].minutes_until <= 0
    assert not find_due([("My calendar", ev(-(GRACE.total_seconds() // 60) - 1))], NOW, {})[0]


def test_a_cancelled_event_never_reminds():
    item = ev(5)
    item.status = "CANCELLED"
    assert find_due([("My calendar", item)], NOW, {})[0] == []


def test_a_repeating_event_is_skipped_rather_than_reminded_on_the_wrong_day():
    """RRULE is understood by nothing here, so its occurrences are not guessed."""
    item = ev(5)
    item.unsupported.append("RRULE")
    assert find_due([("My calendar", item)], NOW, {})[0] == []


def test_an_event_with_no_reminder_stays_silent():
    assert find_due([("My calendar", ev(5, remind=None))], NOW, {})[0] == []


def test_an_all_day_event_rings_in_the_morning_not_at_midnight():
    """Ten minutes before midnight is not what anyone means by 'remind me'."""
    item = VEvent(uid="d@x", summary="Public holiday", start=date(2026, 11, 3), remind_minutes=10)
    moment = anchor(item)
    assert moment.astimezone().hour == 9
    assert moment.astimezone().minute == 0


@pytest.mark.parametrize("minutes,expected", [
    (0, "now"), (-3, "now"), (1, "in a minute"), (15, "in 15 minutes"),
    (60, "in 1h"), (95, "in 1h 35m"),
])
def test_how_a_reminder_reads(minutes, expected):
    from claw.calendar.reminders import Due
    item = Due(uid="x", calendar="c", summary="s", location="", starts_at=NOW,
               all_day=False, minutes_until=minutes)
    assert phrase(item) == expected


# ---------- through the store and the API ----------
def test_the_store_fires_once_and_the_file_records_it(tmp_path):
    store = LocalCalendars(tmp_path)
    now = datetime.now(timezone.utc)
    store.add(VEvent(summary="Site visit", start=now + timedelta(minutes=5), remind_minutes=10))
    first = store.due(now)
    assert len(first) == 1
    store.mark_shown([first[0].uid])
    assert store.due(now) == []
    assert (tmp_path / "reminders.json").is_file()


def test_the_app_can_ask_what_is_due_and_say_what_it_showed(tmp_path):
    client = TestClient(create_app(tmp_path, TOKEN), base_url="http://127.0.0.1")
    head = {"X-Claw-Token": TOKEN}
    store = LocalCalendars(tmp_path / "calendars")
    now = datetime.now(timezone.utc)
    store.add(VEvent(summary="Site visit", start=now + timedelta(minutes=5), remind_minutes=10))

    body = client.get("/calendar/due", headers=head).json()
    assert len(body["due"]) == 1
    item = body["due"][0]
    assert item["summary"] == "Site visit" and item["when"].startswith("in ")

    client.post("/calendar/due/seen", headers=head, json={"uids": [item["uid"]]})
    assert client.get("/calendar/due", headers=head).json()["due"] == []


def test_the_seen_endpoint_refuses_anything_that_is_not_a_list_of_ids(tmp_path):
    client = TestClient(create_app(tmp_path, TOKEN), base_url="http://127.0.0.1")
    head = {"X-Claw-Token": TOKEN}
    assert client.post("/calendar/due/seen", headers=head, json={"uids": "oops"}).status_code == 400
    assert client.post("/calendar/due/seen", headers=head, json={"uids": [1, 2]}).status_code == 400
