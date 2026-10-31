"""A finish that is not one is sent back to the model (seen with the 2B brain on Windows).

The real-brain trial reported "completed" for a Notepad task after only opening Notepad
("I will now proceed with these steps"), and for a flyer and a spreadsheet the brain said
it had no tool for, with make_flyer and create_spreadsheet in its list. Replies are
scripted here (TEST DOUBLE); the trial itself runs on Windows with the real brain.
"""

import json

from claw.agent.executor import fitting_tools, premature_finish
from claw.tools.registry import build_registry
from tests.conftest import VALID_PLAN
from tests.test_api import settings_for
from tests.test_chats import finish, wait_done


def test_the_tools_that_fit_are_named():
    r = build_registry()
    assert fitting_tools("Make a promotional flyer for my software TechDesk", r) == ["make_flyer"]
    assert fitting_tools("Create a spreadsheet of five states and their capitals", r) == ["create_spreadsheet"]
    assert fitting_tools("Copy sales.csv from Documents into a new folder called Backup", r)[:2] == ["copy_files", "create_folder"]
    assert fitting_tools("hello there", r) == []


def test_premature_finishes_are_recognised_and_real_ones_are_not():
    assert premature_finish("Notepad has been opened. I will now proceed with these steps.", [{"outcome": "verified"}], [])
    assert premature_finish("The necessary tools are not available in the list of tools provided.", [], ["create_spreadsheet"])
    assert premature_finish("I cannot make a flyer.", [], ["make_flyer"])
    assert premature_finish("There are no calendars on this computer yet.", [{"outcome": "verified"}], ["list_events"]) is None
    assert premature_finish("Saved flyer.png in Documents.", [{"outcome": "verified"}], ["make_flyer"]) is None


def test_a_premature_finish_is_sent_back_and_the_task_carries_on(make_client, fake_server):
    fake_server.replies += [json.dumps(VALID_PLAN), finish("Notepad has been opened. I will now proceed with these steps."),
                            finish("Done: the file was written and checked.")]
    c = make_client(settings_for(fake_server)).__enter__()
    tid = c.post("/tasks/run", json={"task": "Write a note for me"}).json()["id"]
    assert wait_done(c, tid) == "completed"
    kinds = [e["kind"] for e in c.get(f"/tasks/{tid}/events").json()["events"]]
    assert "pushed_back" in kinds
    assert c.get(f"/tasks/{tid}").json()["result"]["final_answer"].startswith("Done")


def test_pushback_is_limited_so_a_stubborn_model_still_ends(make_client, fake_server):
    stubborn = finish("I will now proceed.")
    fake_server.replies += [json.dumps(VALID_PLAN), stubborn, stubborn, stubborn]
    c = make_client(settings_for(fake_server)).__enter__()
    tid = c.post("/tasks/run", json={"task": "Write a note for me"}).json()["id"]
    assert wait_done(c, tid) == "completed"
    kinds = [e["kind"] for e in c.get(f"/tasks/{tid}/events").json()["events"]]
    assert kinds.count("pushed_back") == 2


def test_near_miss_arguments_from_the_third_trial_are_accepted():
    from claw.tools.document_tools import SheetArgs
    from claw.tools.image_tools import FlyerArgs

    rows = SheetArgs.model_validate({"file_name": "states", "columns": ["State", "Capital"],
                                     "rows": [{"State": "Lagos", "Capital": "Ikeja"}, "Oyo, Ibadan"]}).rows
    assert rows == [["Lagos", "Ikeja"], ["Oyo", "Ibadan"]]
    f = FlyerArgs.model_validate({"title": "TechDesk", "background": "dark blue", "accent": "rainbow"})
    assert f.background == "#14213d" and f.accent == "#3cc2aa"


def test_i_will_create_is_not_a_finish():
    assert premature_finish("I will create a new folder named Backup and copy the file.", [], ["copy_files"])
