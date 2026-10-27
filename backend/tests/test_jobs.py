"""Work that runs on a schedule, with nobody watching.

This is the riskiest feature in the product, so the tests are mostly about
restraint: what an unattended job may not do, what it does instead of asking,
and what happens when the person is using S-CLAW at the time.

The schedule arithmetic is pure, so every awkward case — asleep for a day, the
job has never run, 07:59 versus 08:00 — is tested at a fixed moment.
"""

from datetime import datetime, time, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from claw.api.app import create_app
from claw.jobs.runner import due_jobs
from claw.jobs.schedule import CATCH_UP, BadSchedule, Schedule, is_due, next_run
from claw.permissions.policy import Decision, PermissionPolicy, RiskLevel
from claw.storage.db import Database

TOKEN = "t" * 40


def at(hour, minute=0, day=3):
    return datetime.combine(datetime(2026, 11, day).date(), time(hour, minute)).astimezone()


# ---------- what an unattended job may not do ----------
def test_nothing_can_ask_a_person_who_is_not_there():
    """Every "ask" becomes "no": waiting for an approval nobody will give is how
    an unattended agent ends up doing something nobody agreed to."""
    watched = PermissionPolicy({r: Decision.ASK for r in RiskLevel}, ["/tmp"])
    alone = watched.unattended()
    for risk in RiskLevel:
        assert alone.decide(risk) is Decision.DENY, f"{risk} could still ask"


def test_destructive_work_is_refused_even_if_the_settings_allow_it():
    loose = PermissionPolicy({r: Decision.ALLOW for r in RiskLevel}, ["/tmp"])
    alone = loose.unattended()
    assert alone.decide(RiskLevel.DESTRUCTIVE) is Decision.DENY
    # Reading is still fine: a job that can do nothing at all is not a feature.
    assert alone.decide(RiskLevel.READ_ONLY) is Decision.ALLOW


def test_the_folders_a_person_authorised_are_not_widened():
    policy = PermissionPolicy({r: Decision.ALLOW for r in RiskLevel}, ["/tmp"])
    assert policy.unattended().authorized_roots == policy.authorized_roots


# ---------- when a job is due ----------
@pytest.mark.parametrize("kind,kwargs,words", [
    ("every", {"minutes": 30}, "every 30 minutes"),
    ("every", {"minutes": 60}, "every hour"),
    ("every", {"minutes": 240}, "every 4 hours"),
    ("daily", {"at": "08:00"}, "every day at 08:00"),
])
def test_a_schedule_reads_as_a_sentence(kind, kwargs, words):
    assert Schedule.parse(kind, **kwargs).describe() == words


@pytest.mark.parametrize("kind,kwargs", [
    ("every", {"minutes": 1}),            # a busy loop wearing a schedule
    ("every", {"minutes": 60 * 24 * 8}),  # longer than a week
    ("daily", {"at": "25:00"}),
    ("daily", {"at": "8am"}),
    ("weekly", {"minutes": 60}),
    ("cron", {"minutes": 60}),            # deliberately not supported
])
def test_a_schedule_that_cannot_be_read_is_refused_not_guessed(kind, kwargs):
    with pytest.raises(BadSchedule):
        Schedule.parse(kind, **kwargs)


def test_an_interval_job_counts_from_its_last_run():
    every30 = Schedule.parse("every", minutes=30)
    assert is_due(every30, None, at(9)), "a job that never ran is due"
    assert not is_due(every30, at(9), at(9, 29))
    assert is_due(every30, at(9), at(9, 30))


def test_a_late_interval_job_does_not_then_run_twice_to_catch_up():
    every30 = Schedule.parse("every", minutes=30)
    # It last ran at 09:00 and the computer slept until 15:00.
    assert next_run(every30, at(9), at(15)) == at(9, 30)
    assert is_due(every30, at(9), at(15)), "it is due once"
    # Having run at 15:00, the next one is 15:30, not a backlog of six.
    assert next_run(every30, at(15), at(15)) == at(15, 30)


def test_a_daily_job_waits_for_its_time():
    daily = Schedule.parse("daily", at="08:00")
    assert not is_due(daily, None, at(7, 59))
    assert is_due(daily, None, at(8, 0))


def test_a_daily_job_missed_while_the_computer_was_off_runs_late_but_not_absurdly_late():
    daily = Schedule.parse("daily", at="08:00")
    assert is_due(daily, None, at(8) + CATCH_UP - timedelta(minutes=1)), "late is still useful"
    assert not is_due(daily, None, at(8) + CATCH_UP + timedelta(minutes=1)), \
        "yesterday's morning report arriving at night is noise"


def test_a_daily_job_runs_once_a_day():
    daily = Schedule.parse("daily", at="08:00")
    assert not is_due(daily, at(8, 1), at(9)), "it already ran today"
    assert is_due(daily, at(8, 1, day=2), at(9)), "yesterday's run does not count"
    assert next_run(daily, at(8, 1), at(9)) == at(8, day=4)


# ---------- choosing what to run ----------
def job(**kw):
    base = {"id": "j1", "name": "Site check", "task_text": "check it", "kind": "every",
            "minutes": 30, "at": "", "enabled": 1, "last_run": None}
    return {**base, **kw}


def test_only_enabled_jobs_run():
    assert due_jobs([job(enabled=0)], at(9)) == []
    assert len(due_jobs([job()], at(9))) == 1


def test_a_job_with_an_unreadable_schedule_is_skipped_not_run_at_random():
    assert due_jobs([job(kind="cron", minutes=0, at="*/5 * * * *")], at(9)) == []


def test_a_stored_timestamp_that_makes_no_sense_does_not_crash_the_loop():
    assert len(due_jobs([job(last_run="not a date")], at(9))) == 1


# ---------- history ----------
def test_being_skipped_is_recorded_but_does_not_count_as_having_run(tmp_path):
    """Otherwise a job skipped because you were typing silently loses its turn."""
    db = Database(tmp_path / "claw.db")
    job_id = db.add_job("Site check", "check it", "every", minutes=30)
    db.record_job_run(job_id, "skipped", "S-CLAW was busy with something else.")
    assert db.job(job_id)["last_run"] is None, "a skip consumed the job's turn"
    assert db.job(job_id)["last_status"] == "skipped", "but it is visible"
    db.record_job_run(job_id, "completed", "it is up", "task-1")
    assert db.job(job_id)["last_run"] is not None


def test_a_jobs_history_goes_with_it_when_it_is_deleted(tmp_path):
    db = Database(tmp_path / "claw.db")
    job_id = db.add_job("Site check", "check it", "every", minutes=30)
    db.record_job_run(job_id, "completed", "fine", "task-1")
    db.delete_job(job_id)
    assert db.job_runs(job_id) == []


# ---------- through the API ----------
@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(tmp_path, TOKEN), base_url="http://127.0.0.1")


HEAD = {"X-Claw-Token": TOKEN}


def test_a_job_can_be_made_listed_paused_and_removed(client):
    made = client.post("/jobs", headers=HEAD, json={
        "name": "Site check", "task": "check example.com is up",
        "kind": "every", "minutes": 30}).json()
    assert made["schedule"] == "every 30 minutes" and made["next_run"]

    listed = client.get("/jobs", headers=HEAD).json()
    assert len(listed["jobs"]) == 1
    # The promise this feature cannot keep is denied in the data itself.
    assert "only while S-CLAW is open" in listed["note"]
    assert listed["jobs"][0]["only_while_running"] is True

    paused = client.post(f"/jobs/{made['id']}/enabled", headers=HEAD, json={"enabled": False}).json()
    assert paused["enabled"] is False
    assert paused["next_run"] is None, "a paused job must not advertise a next run"

    assert client.delete(f"/jobs/{made['id']}", headers=HEAD).status_code == 200
    assert client.delete(f"/jobs/{made['id']}", headers=HEAD).status_code == 404


@pytest.mark.parametrize("body,code", [
    ({"name": "", "task": "x", "kind": "every", "minutes": 30}, "bad_request"),
    ({"name": "x", "task": "", "kind": "every", "minutes": 30}, "bad_request"),
    ({"name": "x", "task": "y", "kind": "every", "minutes": 1}, "bad_schedule"),
    ({"name": "x", "task": "y", "kind": "cron", "at": "* * * * *"}, "bad_schedule"),
])
def test_a_job_that_cannot_work_is_refused_at_the_door(client, body, code):
    res = client.post("/jobs", headers=HEAD, json=body)
    assert res.status_code == 400 and res.json()["error"]["code"] == code


def test_history_for_a_job_that_is_not_there(client):
    assert client.get("/jobs/nope/runs", headers=HEAD).status_code == 404
