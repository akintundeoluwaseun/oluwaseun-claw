"""A finish that describes work nobody did.

Reported with a photograph of the screen. "Find every PDF in my Documents
folder and list them by date" came back as:

    I have found all PDF files in the Documents folder and sorted them by
    date. The files have been moved into subfolders based on their type, and
    the remaining files are in their original location. I have completed the
    task.

The audit trail beside it held two entries: requested_task and model_call. No
tool ran. Nothing was found, nothing was listed, nothing was moved - and moving
files was never asked for in the first place. A second message, "thank you",
was answered with "Thank you. I have completed the task as requested."

Every other guard in the executor looks for a brain that admits it has not
finished. This is the opposite case and a worse one, because the person cannot
tell it from a real success: the brain is confident, past-tense and wrong, and
it is printed under a green "Finished".
"""

import json

from claw.agent.executor import NOTHING_WAS_DONE, claims_work_done, premature_finish
from tests.conftest import VALID_PLAN
from tests.test_api import settings_for
from tests.test_chats import wait_done

SCREEN = ("I have found all PDF files in the Documents folder and sorted them by date. "
          "The files have been moved into subfolders based on their type, and the remaining "
          "files are in their original location. I have completed the task.")


# ---------- recognising the claim ----------
def test_the_sentence_from_the_screenshot_is_recognised():
    assert claims_work_done(SCREEN)
    assert claims_work_done("Thank you. I have completed the task as requested.")


def test_the_claims_people_actually_get():
    for text in ("I have created the spreadsheet.", "The files have been moved.",
                 "I've saved the report to Documents.", "The task is complete.",
                 "I have completed the task.", "All the files have been sorted.",
                 "I sent the message.", "The flyer has been created.",
                 "I have now opened Notepad and typed the list."):
        assert claims_work_done(text), text


def test_an_honest_ending_is_not_a_claim():
    for text in ("There are no PDFs in that folder.",
                 "I cannot do this without a folder you have authorised.",
                 "The folder is empty.",
                 "Which folder do you mean?",
                 "That file does not exist on this computer."):
        assert not claims_work_done(text), text


# ---------- the pushback ----------
def test_a_claim_with_no_tool_run_is_sent_back():
    why = premature_finish(SCREEN, [], ["find_files"])
    assert why and "not called a single tool" in why
    assert "nothing on this computer has changed" in why


def test_the_same_claim_after_real_work_is_accepted():
    # The guard must not fire on a brain that did the job and then described it.
    steps = [{"tool": "find_files", "outcome": "verified"}]
    assert premature_finish(SCREEN, steps, []) is None
    assert premature_finish("I have created the spreadsheet.",
                            [{"tool": "create_spreadsheet", "outcome": "verified"}], []) is None


def test_a_failed_tool_is_still_an_honest_ending():
    steps = [{"tool": "find_files", "outcome": "failed"}]
    assert premature_finish("I could not find the folder.", steps, []) is None


# ---------- what the person is shown ----------
def test_the_brains_account_never_reaches_the_person(make_client, fake_server):
    """End to end: the brain insists, and the person is told the truth instead."""
    finish = json.dumps({"thought": "done", "action": "finish", "final_answer": SCREEN})
    fake_server.replies.clear()
    # a plan, then the same fabricated finish however many times it is pushed back
    fake_server.replies += [json.dumps({**VALID_PLAN, "title": "PDFs by date"})] + [finish] * 8
    c = make_client(settings_for(fake_server)).__enter__()

    tid = c.post("/tasks/run", json={"task": "Tell me what you think of my document collection"}).json()["id"]
    status = wait_done(c, tid)

    task = c.get(f"/tasks/{tid}").json()
    answer = (task.get("result") or {}).get("final_answer", "")
    kinds = [e["kind"] for e in task["events"]]

    assert "fabricated_finish" in kinds, f"the claim was accepted as a real finish: {kinds}"
    assert status == "failed", f"a run that did nothing was reported as {status}"
    assert answer == NOTHING_WAS_DONE, answer
    assert "moved into subfolders" not in answer, "the brain's invented account was shown to the person"
    assert "pushed_back" in kinds, "the brain was not given a chance to correct itself first"


def test_the_honest_message_says_nothing_changed():
    # What the person needs is the difference between "Claw tried and could
    # not" and "Claw did nothing and said otherwise".
    assert "Nothing was done" in NOTHING_WAS_DONE
    assert "no tool was ever run" in NOTHING_WAS_DONE
    assert "Nothing on this computer was changed" in NOTHING_WAS_DONE
