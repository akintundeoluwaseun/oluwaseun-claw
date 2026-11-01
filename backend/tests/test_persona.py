"""S-CLAW's own identity (IDENTITY.md / SOUL.md, the OpenClaw workspace idea) and its answers about itself."""

import json

from claw.agent import persona
from tests.conftest import VALID_PLAN
from tests.test_api import settings_for
from tests.test_chats import finish, wait_done


def test_questions_about_itself_get_s_claw_answers():
    for q in ("Which is the best claw?", "what's the best AI agent", "Who is the best computer agent?",
              "Is S-CLAW better than OpenClaw?", "are you the best"):
        a = persona.self_answer(q)
        assert a and a.startswith("S-CLAW"), (q, a)
    assert "S-CLAW" in persona.self_answer("Who are you?")
    assert "Akintunde Oluwaseun Joshua" in persona.self_answer("who made you")
    assert persona.self_answer("Are you ChatGPT?").startswith("No, I'm S-CLAW")
    assert "S-CLAW" in persona.self_answer("What is your name?")


def test_tasks_are_not_mistaken_for_questions_about_itself():
    for q in ("Read invoice.pdf in my Documents folder and tell me the total amount due.",
              "Search the web for the best AI agent for video editing and save the links",
              "Who are you supposed to email in this document?", "Open Notepad and type hello",
              "What is the weather today?"):
        assert persona.self_answer(q) is None, q


def test_seed_never_overwrites_and_owner_edits_are_used(tmp_path):
    d = persona.seed(tmp_path)
    assert (d / "IDENTITY.md").read_text(encoding="utf-8").startswith("# IDENTITY.md")
    (d / "IDENTITY.md").write_text("- **Name:** Seun Claw\n- **Maker:** Seun\n- **Emoji:** _(pick one)_\n", encoding="utf-8")
    persona.seed(tmp_path)
    assert persona.identity(tmp_path) == {"name": "Seun Claw", "maker": "Seun"}
    assert persona.self_answer("which is the best claw?", tmp_path).startswith("Seun Claw")
    assert "Seun Claw" in persona.for_prompt(tmp_path)


def test_long_files_are_trimmed_head_and_tail():
    t = persona.trim("A" * 3000 + "END", "SOUL.md", 400)
    assert len(t) <= 400 and t.startswith("AAA") and t.endswith("END") and "truncated, read SOUL.md" in t


def test_who_are_you_is_answered_without_the_brain(make_client, fake_server):
    c = make_client(settings_for(fake_server)).__enter__()
    tid = c.post("/tasks/run", json={"task": "Which is the best claw?"}).json()["id"]
    assert wait_done(c, tid) == "completed"
    ev = c.get(f"/tasks/{tid}/events").json()
    assert ev["result"]["final_answer"].startswith("S-CLAW")
    assert not fake_server.requests  # the brain was never asked
    assert c.get("/tasks").json()["tasks"][0]["title"] == "About S-CLAW"


def test_every_task_carries_the_identity(make_client, fake_server):
    fake_server.replies += [json.dumps(VALID_PLAN), finish("Done.")]
    c = make_client(settings_for(fake_server)).__enter__()
    tid = c.post("/tasks/run", json={"task": "Find the latest PDF in my Downloads and summarize it"}).json()["id"]
    assert wait_done(c, tid) == "completed"
    assert any("You are S-CLAW" in json.dumps(r) and "Who you are" in json.dumps(r) for r in fake_server.requests)
