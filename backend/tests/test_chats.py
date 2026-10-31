"""Chats: retries and follow-ups stay in one conversation, which has one title written from the request.

Reported on a real install: retrying after an error added a new history entry each time, all with the same
name, and every name was the request pasted back. Model replies are scripted (TEST DOUBLE).
"""

import json
import time

from claw.agent.titles import clean_model_title, fallback_title
from tests.conftest import VALID_PLAN
from tests.test_api import settings_for


def finish(text):
    return json.dumps({"thought": "done", "action": "finish", "final_answer": text})


def wait_done(c, task_id, seconds=20):
    end = time.time() + seconds
    while time.time() < end:
        st = c.get(f"/tasks/{task_id}/events").json()["status"]
        if st not in ("created", "planning", "running", "awaiting_approval"):
            return st
        time.sleep(0.1)
    raise AssertionError("task did not finish")


def test_fallback_titles_are_short_and_not_the_request_pasted():
    assert fallback_title("Can you please open Notepad and type my shopping list") == "Open Notepad"
    assert fallback_title("Read invoice.pdf in my Documents folder and tell me the total.") == "Read invoice.pdf in my Documents folder"
    assert fallback_title("hi, could you search the web for free video editors") == "Search free video editors"
    assert fallback_title("please") == "New chat"
    assert len(fallback_title("word " * 40).split()) <= 7


def test_model_titles_are_checked():
    assert clean_model_title('"invoice total from pdf."') == "Invoice total from pdf"
    assert clean_model_title("") is None
    assert clean_model_title("This is a very long sentence that is not really a title at all for sure") is None


def test_retry_and_follow_up_stay_in_one_chat_with_the_models_title(make_client, fake_server):
    plan = {**VALID_PLAN, "title": "Newest PDF summary"}
    fake_server.replies += [json.dumps(plan), finish("Summarised report.pdf."),
                            json.dumps(plan), finish("Saved it as summary.txt.")]
    c = make_client(settings_for(fake_server)).__enter__()
    first = c.post("/tasks/run", json={"task": "Can you find the latest PDF in my Downloads and summarize it"}).json()["id"]
    assert wait_done(c, first) == "completed"
    follow = c.post("/tasks/run", json={"task": "Now save that summary as a text file", "thread_id": first}).json()["id"]
    assert wait_done(c, follow) == "completed"
    chats = c.get("/tasks").json()["tasks"]
    assert len(chats) == 1, chats
    assert chats[0]["id"] == follow and chats[0]["title"] == "Newest PDF summary" and chats[0]["messages"] == 2
    thread = c.get("/tasks", params={"thread": first}).json()
    assert [t["task_text"] for t in thread["tasks"]][0].startswith("Can you find") and thread["title"] == "Newest PDF summary"
    # the follow-up was planned knowing what came before
    planning_requests = [r for r in fake_server.requests if "User request" in json.dumps(r)]
    assert "Earlier in this conversation" in json.dumps(planning_requests[-1]) and "Summarised report.pdf" in json.dumps(planning_requests[-1])


def test_failed_attempts_and_retries_do_not_duplicate_the_chat(make_client, fake_server):
    fake_server.status_override = 500  # the brain fails: every attempt errors
    c = make_client(settings_for(fake_server)).__enter__()
    first = c.post("/tasks/run", json={"task": "Please check what windows are open right now"}).json()["id"]
    assert wait_done(c, first) == "failed"
    for _ in range(3):
        again = c.post("/tasks/run", json={"task": "Please check what windows are open right now", "thread_id": first}).json()["id"]
        assert wait_done(c, again) == "failed"
    chats = c.get("/tasks").json()["tasks"]
    assert len(chats) == 1 and chats[0]["messages"] == 4
    assert chats[0]["title"] == "Check what windows are open right now"  # no brain answered: a cleaned-up title, not the request


def test_new_chat_when_no_thread_and_bad_thread_ids(make_client, fake_server):
    c = make_client(settings_for(fake_server)).__enter__()
    assert c.post("/tasks/run", json={"task": "Open Notepad", "thread_id": "not-a-thread"}).status_code == 422
    assert c.get("/tasks", params={"thread": "../x"}).status_code == 422
    fake_server.status_override = 500
    gone = "0" * 32
    tid = c.post("/tasks/run", json={"task": "Open Notepad", "thread_id": gone}).json()["id"]
    wait_done(c, tid)
    assert c.get("/tasks").json()["tasks"][0]["thread_id"] == tid  # an unknown chat starts a new one


def test_starter_folders_are_the_everyday_ones_that_exist(tmp_path):
    from claw.config import starter_folders

    (tmp_path / "Documents").mkdir()
    (tmp_path / "OneDrive" / "Desktop").mkdir(parents=True)
    got = starter_folders(tmp_path)
    assert got == [str(tmp_path / "Documents"), str(tmp_path / "OneDrive" / "Desktop")]  # no Downloads here: not invented


def test_a_fresh_install_gets_its_folders_once(tmp_path, monkeypatch):
    import json as _json

    from claw.api.app import create_app

    home = tmp_path / "home"
    (home / "Documents").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("CLAW_NO_STARTER_FOLDERS")
    data = tmp_path / "data"
    create_app(data, "t" * 40)
    saved = _json.loads((data / "settings.json").read_text())["permissions"]
    assert saved["authorized_folders"] == [str(home / "Documents")] and saved["starter_folders_added"]
    # someone removes them: a restart must not put them back
    saved["authorized_folders"] = []
    full = _json.loads((data / "settings.json").read_text()); full["permissions"] = saved
    (data / "settings.json").write_text(_json.dumps(full))
    create_app(data, "t" * 40)
    assert _json.loads((data / "settings.json").read_text())["permissions"]["authorized_folders"] == []


def test_a_search_in_the_middle_keeps_its_case():
    assert fallback_title("Open my browser and search for motion graphics templates") == "Open my browser and search motion graphics"
