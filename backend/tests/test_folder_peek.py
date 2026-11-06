"""A folder pasted on its own gets an answer at once.

Asked for directly: paste a path and have Claw say what is in it - "these are
the files, what do you want done?" - without planning. A bare path smells like
work, because it IS a path, so it went to the planner carrying the whole tool
catalogue and took the best part of a minute to decide to list a directory.

Reading a directory takes milliseconds, and the person has not said what they
want done yet anyway. This is the question before the job.
"""

import json
import tempfile
from pathlib import Path

import pytest

from claw.agent.conversation import describe_folder, looks_like_bare_path, path_in
from tests.conftest import VALID_PLAN
from tests.test_api import settings_for
from tests.test_chats import finish, wait_done


# ---------- is it just a path? ----------
def test_a_path_on_its_own():
    for text in (r"C:\Users\Me\Pictures", r"C:\Users\Me\Job files", "/home/me/Pictures",
                 "~/Documents", r"\\server\share\jobs", '"C:\\Users\\Me\\Pictures"'):
        # "share" is a task verb and an ordinary Windows path segment, which is
        # why only the LAST segment is checked for one.
        assert looks_like_bare_path(text), text


def test_a_path_with_an_instruction_round_it_is_a_job():
    # A Windows folder name can contain spaces, so the pattern cannot ban them.
    # A task verb is what separates "here is a folder" from "do this to it".
    for text in (r"sort the files in C:\Users\Me\Pictures",
                 r"C:\Users\Me\Pictures and make a flyer",
                 r"open C:\Users\Me\Pictures",
                 "make a flyer", "hello"):
        assert not looks_like_bare_path(text), text


def test_the_quotes_explorer_adds_are_stripped():
    assert path_in('"C:\\Users\\Me\\Job files"') == r"C:\Users\Me\Job files"


# ---------- what it says ----------
@pytest.fixture
def folder():
    with tempfile.TemporaryDirectory() as d:
        here = Path(d)
        for n in ("a.jpg", "b.jpg", "c.png", "notes.txt", "invoice.pdf"):
            (here / n).write_text("x")
        (here / "old").mkdir()
        yield here


def test_it_counts_what_is_there_and_asks_what_to_do(folder):
    said = describe_folder(str(folder), [str(folder)])
    assert "5 files" in said and "2 jpg" in said and "1 folder" in said
    assert "a.jpg" in said and "notes.txt" in said
    assert said.endswith("What would you like done with them?")


def test_a_long_folder_does_not_list_everything(folder):
    for i in range(40):
        (folder / f"pic{i:02d}.jpg").write_text("x")
    said = describe_folder(str(folder), [str(folder)])
    assert "45 files" in said and said.count(".jpg") <= 9 and "…" in said


def test_an_empty_folder_says_so(tmp_path):
    assert "is empty" in describe_folder(str(tmp_path), [str(tmp_path)])


def test_a_file_is_not_a_folder(folder):
    said = describe_folder(str(folder / "a.jpg"), [str(folder)])
    assert "is a file, not a folder" in said


def test_a_path_that_does_not_exist_says_so_plainly(folder):
    said = describe_folder(str(folder / "nope"), [str(folder)])
    assert "There is nothing at" in said and "paste it again" in said


def test_a_folder_claw_may_not_open_is_refused_with_the_remedy(folder):
    said = describe_folder("/etc", [str(folder)])
    assert "not a folder Claw may open" in said and "Settings > Folders" in said


def test_a_subfolder_of_an_allowed_folder_is_allowed(folder):
    assert "is empty" in describe_folder(str(folder / "old"), [str(folder)])


# ---------- end to end: no planning call ----------
def test_pasting_a_folder_never_wakes_the_brain(make_client, fake_server, tmp_path):
    here = tmp_path / "Pictures"
    here.mkdir()
    (here / "one.jpg").write_text("x")
    settings = settings_for(fake_server)
    settings["permissions"] = {"authorized_folders": [str(here)]}
    fake_server.replies.clear()
    fake_server.requests.clear()

    c = make_client(settings).__enter__()
    tid = c.post("/tasks/run", json={"task": str(here)}).json()["id"]
    assert wait_done(c, tid) == "completed"

    task = c.get(f"/tasks/{tid}").json()
    answer = (task.get("result") or {}).get("final_answer", "")
    kinds = [e["kind"] for e in task["events"]]

    assert "1 file" in answer and "one.jpg" in answer, answer
    assert fake_server.requests == [], "the brain was woken to list a directory"
    assert "planned" not in kinds and "model_call" not in kinds, kinds
    assert "chat_reply" in kinds


def test_the_next_message_still_knows_which_folder(make_client, fake_server, tmp_path):
    """The point of the peek: paste a folder, then say what to do with it.

    The planner must see the path in the second message without the person
    typing it again - otherwise the fast answer has cost them the context.
    """
    here = tmp_path / "Pictures"
    here.mkdir()
    (here / "one.jpg").write_text("x")
    (here / "two.jpg").write_text("x")
    settings = settings_for(fake_server)
    settings["permissions"] = {"authorized_folders": [str(here)]}

    c = make_client(settings).__enter__()
    first = c.post("/tasks/run", json={"task": str(here)}).json()["id"]
    assert wait_done(c, first) == "completed"
    thread = c.get(f"/tasks/{first}").json()["thread_id"]

    fake_server.replies.clear()
    fake_server.requests.clear()
    fake_server.replies += [json.dumps({**VALID_PLAN, "title": "Flyer from the pictures"}),
                            finish("Made it.")]
    second = c.post("/tasks/run", json={"task": "make a flyer from the pictures in there",
                                        "thread_id": thread}).json()["id"]
    wait_done(c, second)

    asked = json.dumps(fake_server.requests)
    assert str(here) in asked, "the planner was not told which folder"
    assert "one.jpg" in asked or "2 files" in asked, "what is in the folder was not carried over"
