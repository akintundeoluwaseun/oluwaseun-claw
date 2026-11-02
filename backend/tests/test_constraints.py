"""Limits in the request are read before planning (challenge 17.06, reuse audit §2.1)."""

import json

from claw.agent.constraints import breaks, conflict_question, read_limits
from tests.conftest import VALID_PLAN
from tests.test_api import settings_for
from tests.test_chats import finish, wait_done


def test_limits_are_read_from_plain_words():
    lim = read_limits("Tidy my Downloads folder but don't delete anything and don't change the PDFs.")
    assert lim.no_delete and lim.no_changes and not lim.no_new_files
    assert breaks(lim, "move_file") and breaks(lim, "delete_file") and breaks(lim, "list_folder") is None
    lim = read_limits("Write the message to Tunde but do not send it.")
    assert lim.no_send and breaks(lim, "send_whatsapp_message") and not lim.conflicts
    assert "Do NOT send" in lim.for_prompt()
    assert not read_limits("Read invoice.pdf and tell me the total.").any()


def test_a_request_that_contradicts_itself_is_a_question():
    for t in ("Make a spreadsheet of 3 fruits and their colours, but do not create any new files.",
              "Create a report of my sales without creating any files."):
        q = conflict_question(read_limits(t))
        assert q and "Nothing has been created or changed" in q, t
    for t in ("Do not create any new files; just tell me which file is biggest in Downloads.",
              "Make a spreadsheet of 3 fruits.", "Combine the CSVs but don't change the originals."):
        assert conflict_question(read_limits(t)) is None, t


def test_conflict_is_asked_before_anything_runs(make_client, fake_server, tmp_path):
    c = make_client(settings_for(fake_server)).__enter__()
    tid = c.post("/tasks/run", json={"task": "Make a spreadsheet of 3 fruits and their colours, but do not create any new files."}).json()["id"]
    assert wait_done(c, tid) == "completed"
    res = c.get(f"/tasks/{tid}").json()["result"]
    assert "can't do both" in res["final_answer"] and res["report"]["blocked"] and not res["steps"]
    assert not fake_server.requests                      # the brain was never asked, nothing ran


def test_the_brain_is_told_the_limits(make_client, fake_server):
    fake_server.replies += [json.dumps(VALID_PLAN), finish("Done.")]
    c = make_client(settings_for(fake_server)).__enter__()
    tid = c.post("/tasks/run", json={"task": "Find the latest PDF in my Downloads and summarize it, but do not delete anything."}).json()["id"]
    assert wait_done(c, tid) == "completed"
    assert any("Do NOT delete anything" in json.dumps(r) for r in fake_server.requests)
