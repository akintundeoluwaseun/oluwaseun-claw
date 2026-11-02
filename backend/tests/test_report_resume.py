"""Milestone 2: every task ends with COMPLETED / UNVERIFIED / INCOMPLETE / BLOCKED, and a stopped task can carry on."""

import json

from claw.agent.report import done_so_far, final_report, resume_text
from tests.conftest import VALID_PLAN
from tests.test_api import settings_for
from tests.test_chats import finish, wait_done


def test_report_groups_what_was_observed():
    steps = [{"tool": "find_files", "outcome": "verified", "detail": "Found 3"},
             {"tool": "write_text_file", "outcome": "verified", "detail": "Created notes.txt (20 characters)."},
             {"tool": "type_text", "outcome": "done_unverified", "detail": "Typed 20 characters into the active window."},
             {"tool": "send_message", "outcome": "denied", "detail": "You said no."}]
    files = [{"path": "C:/x/notes.txt", "verified": True}, {"path": "C:/x/flyer.png", "verified": False, "note": "headline not checked"}]
    r = final_report(steps, files, "completed")
    assert r["completed"] == ["Created notes.txt (20 characters)."]          # looking (find_files) is not work done
    assert r["unverified"][0].startswith("Typed 20") and "flyer.png" in r["unverified"][1]
    assert r["blocked"] == ["send_message: You said no."] and r["incomplete"] == []
    assert final_report([], [], "interrupted")["incomplete"][0].startswith("The task did not finish. S-CLAW stopped")


def test_resume_hands_over_only_checked_work():
    ev = [{"kind": "verified", "data": {"tool": "create_folder", "detail": "Created Backup"}},
          {"kind": "verified", "data": {"tool": "list_folder", "detail": "3 items"}},
          {"kind": "failed", "data": {"tool": "copy_files", "detail": "locked"}},
          {"kind": "verified", "data": {"tool": "create_folder", "detail": "Created Backup"}}]
    done = done_so_far(ev)
    assert done == ["create_folder: Created Backup"]
    t = resume_text("Copy sales.csv into Backup.", done)
    assert t.startswith("Copy sales.csv into Backup.") and "do NOT repeat" in t and "create_folder" in t


def test_results_carry_the_report_and_an_interrupted_task_resumes(make_client, fake_server, data_dir):
    import sqlite3
    fake_server.replies += [json.dumps(VALID_PLAN), finish("Done."), json.dumps(VALID_PLAN), finish("Carried on.")]
    c = make_client(settings_for(fake_server)).__enter__()
    first = c.post("/tasks/run", json={"task": "Find the latest PDF in my Downloads and summarize it."}).json()["id"]
    assert wait_done(c, first) == "completed"
    assert set(c.get(f"/tasks/{first}").json()["result"]["report"]) == {"completed", "unverified", "incomplete", "blocked"}
    assert c.post(f"/tasks/{first}/resume").status_code == 409            # a finished task is not resumed
    # As if S-CLAW had been closed part-way, after making the folder.
    con = sqlite3.connect(data_dir / "claw.db")
    con.execute("UPDATE tasks SET status='interrupted' WHERE id=?", (first,))
    con.execute("INSERT INTO task_events(task_id, ts, kind, data_json) VALUES (?, '2026-11-02T00:00:00', 'verified', ?)",
                (first, json.dumps({"tool": "create_folder", "detail": "Created the folder 'Backup'"})))
    con.commit()
    con.close()
    r = c.post(f"/tasks/{first}/resume")
    assert r.status_code == 202
    new = r.json()["id"]
    assert wait_done(c, new) == "completed"
    t = c.get(f"/tasks/{new}").json()
    assert t["thread_id"] == first and "do NOT repeat" in t["task_text"] and "Created the folder 'Backup'" in t["task_text"]
    assert t["task_text"].startswith("Find the latest PDF")
