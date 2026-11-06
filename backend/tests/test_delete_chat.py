"""Deleting a chat, asked for after a real install: there was no way to.

A chat is the unit a person sees in the history, so it is the unit they can
delete - one message of a conversation removed would leave answers with no
questions. What goes is the messages and their steps. What stays is deliberate
and tested here, because it is the part someone would be upset to lose by
tidying their history:

- memories. "My business address is 14 Taiwo Road" is a fact about the person,
  not a line of a transcript.
- the files Claw saved. They are in the person's own folders.

A chat still working is refused rather than quietly stopped: stopping someone's
work as a side effect of tidying is not what they asked for.
"""

import json
import time

from claw.storage.db import Database
from tests.conftest import VALID_PLAN
from tests.test_api import settings_for


def finish(text):
    return json.dumps({"thought": "done", "action": "finish", "final_answer": text})


#: 60, not 20: a deadline that only holds on an idle machine reports the
#: machine rather than the code, and the suite is over a thousand tests. The
#: message names the status it was stuck at, so a timeout can be read instead
#: of guessed at.
#:
#: Honest note, because this was first changed for the wrong reason. It was
#: raised to explain an intermittent failure in
#: test_a_real_job_still_goes_through_the_planner, which was assumed to be a
#: timeout. It is not. When that test fails the events are
#: ['requested_task', 'model_call', 'task_cancelled'] - the task was
#: CANCELLED, so wait_done returned at once and never came near any deadline.
#: The only things that cancel a task are an explicit cancel request and the
#: app's lifespan shutdown (claw/api/app.py cancels a busy runner on the way
#: out). It has not been reproduced outside a full-suite run, and it is NOT
#: fixed by this value. Left raised because it is right on its own merits.
def wait_done(c, task_id, seconds=60):
    end = time.time() + seconds
    st = "never asked"
    while time.time() < end:
        st = c.get(f"/tasks/{task_id}/events").json()["status"]
        if st not in ("created", "planning", "running", "awaiting_approval"):
            return st
        time.sleep(0.1)
    raise AssertionError(f"task {task_id} did not finish in {seconds}s; stuck at {st!r}")


# ---------- the database, on its own ----------
def test_a_chat_takes_its_messages_and_their_steps_with_it(tmp_path):
    db = Database(tmp_path / "claw.db")
    first = db.create_task("Find the PDF", model="m")
    second = db.create_task("And its length", model="m", thread_id=first)
    other = db.create_task("Something else", model="m")
    for t in (first, second, other):
        db.update_task(t, status="completed")
        db.add_event(t, "started", {})
        db.add_event(t, "finished", {})

    assert db.delete_thread(first) == {"deleted": 2, "running": False}
    assert db.get_task(first) is None and db.get_task(second) is None
    assert db.get_events(first) == [] and db.get_events(second) == []
    # the other chat is untouched
    assert db.get_task(other) is not None and len(db.get_events(other)) == 2


def test_a_chat_that_is_still_working_is_refused(tmp_path):
    db = Database(tmp_path / "claw.db")
    task = db.create_task("Open Notepad", model="m")
    db.update_task(task, status="running")
    assert db.delete_thread(task) == {"deleted": 0, "running": True}
    assert db.get_task(task) is not None, "a running task was deleted anyway"


def test_every_unfinished_status_counts_as_working(tmp_path):
    for status in ("created", "planning", "running", "awaiting_approval"):
        db = Database(tmp_path / f"{status}.db")
        task = db.create_task("x", model="m")
        db.update_task(task, status=status)
        assert db.delete_thread(task)["running"] is True, status


def test_one_unfinished_message_protects_the_whole_chat(tmp_path):
    # Deleting the finished half and leaving the running one would be worse than
    # refusing: the run would carry on writing events for a chat half gone.
    db = Database(tmp_path / "claw.db")
    first = db.create_task("Find the PDF", model="m")
    db.update_task(first, status="completed")
    second = db.create_task("Now summarise it", model="m", thread_id=first)
    db.update_task(second, status="running")
    assert db.delete_thread(first)["running"] is True
    assert db.get_task(first) is not None and db.get_task(second) is not None


def test_a_chat_that_does_not_exist_deletes_nothing(tmp_path):
    db = Database(tmp_path / "claw.db")
    assert db.delete_thread("0" * 32) == {"deleted": 0, "running": False}


def test_what_the_person_told_claw_is_not_deleted_with_the_chat(tmp_path):
    db = Database(tmp_path / "claw.db")
    task = db.create_task("Remember my address", model="m")
    db.update_task(task, status="completed")
    db.remember(kind="fact", subject="me", fact="The shop is at 14 Taiwo Road",
               source="said", task_id=task)
    assert db.delete_thread(task)["deleted"] == 1
    kept = db.memories()
    assert [m["fact"] for m in kept] == ["The shop is at 14 Taiwo Road"], kept


# ---------- through the API ----------
def test_deleting_a_chat_removes_it_from_the_history(make_client, fake_server):
    plan = {**VALID_PLAN, "title": "Newest PDF summary"}
    fake_server.replies += [json.dumps(plan), finish("Summarised report.pdf."),
                            json.dumps(plan), finish("It was two pages long."),
                            json.dumps(plan), finish("Kept this one.")]
    c = make_client(settings_for(fake_server)).__enter__()
    first = c.post("/tasks/run", json={"task": "Find the latest PDF in my Downloads"}).json()["id"]
    assert wait_done(c, first) == "completed"
    follow = c.post("/tasks/run", json={"task": "How long was it", "thread_id": first}).json()["id"]
    assert wait_done(c, follow) == "completed"
    keep = c.post("/tasks/run", json={"task": "A different question entirely"}).json()["id"]
    assert wait_done(c, keep) == "completed"
    assert len(c.get("/tasks").json()["tasks"]) == 2

    r = c.delete(f"/chats/{first}")
    assert r.status_code == 200, r.text
    assert r.json() == {"deleted": first, "messages": 2}

    chats = c.get("/tasks").json()["tasks"]
    assert [t["id"] for t in chats] == [keep]
    assert c.get(f"/tasks/{first}").status_code == 404
    assert c.get(f"/tasks/{follow}").status_code == 404
    assert c.get(f"/tasks/{keep}").status_code == 200


def test_deleting_a_chat_twice_says_there_is_no_such_chat(make_client, fake_server):
    # A read-only task on purpose. "Open Notepad please" matches the
    # write-in-notepad skill, whose first step is launch_app - local_write, so it
    # waits for the person's approval and nothing in a test approves it. Correct
    # behaviour, wrong fixture for a test about deleting a finished chat.
    fake_server.replies += [json.dumps({**VALID_PLAN, "title": "Newest PDF summary"}), finish("Done.")]
    c = make_client(settings_for(fake_server)).__enter__()
    task = c.post("/tasks/run", json={"task": "Find the latest PDF in my Downloads"}).json()["id"]
    assert wait_done(c, task) == "completed"
    assert c.delete(f"/chats/{task}").status_code == 200
    again = c.delete(f"/chats/{task}")
    assert again.status_code == 404 and "no such chat" in again.text


def test_a_chat_id_that_is_not_one_is_refused_before_anything_is_deleted(make_client, fake_server):
    c = make_client(settings_for(fake_server)).__enter__()
    for bad in ("../x", "not-a-thread", "0" * 31, "g" * 32, "%2e%2e"):
        assert c.delete(f"/chats/{bad}").status_code in (404, 422), bad
