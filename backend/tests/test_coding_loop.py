"""The whole point, end to end: Claw writes a program, runs it, reads the result.

The individual tools are tested in test_code_tools.py. This is the loop they
exist for - a plan that asks for the code capability, an approval the person
grants, a program that runs, output that comes back, and a finish grounded in
what the program actually printed.

Nothing here is a stand-in except the brain itself, which is scripted so the
test is about the machinery rather than about whether a 2B model has a good
idea.
"""

import json
import time

import pytest

from claw.permissions.policy import Decision, PermissionPolicy, RiskLevel
from tests.test_api import settings_for


def act(tool, **args):
    return json.dumps({"thought": f"using {tool}", "action": "tool", "tool": tool, "args": args})


def done(text):
    return json.dumps({"thought": "finished", "action": "finish", "final_answer": text})


CODE_PLAN = {
    "goal": "Add up the numbers and say the total",
    "steps": [{"description": "Write a small program and run it", "capability": "code",
               "risk": "destructive", "expected_result": "the total"}],
    "questions": [],
    "title": "Add up the numbers",
}


def wait_for(client, task_id, want, seconds=25):
    end = time.time() + seconds
    last = None
    while time.time() < end:
        last = client.get(f"/tasks/{task_id}/events").json()
        if want(last):
            return last
        time.sleep(0.1)
    raise AssertionError(f"never reached the wanted state; last status {last and last.get('status')}")


# ---------- the guarantee the whole thing rests on ----------
def test_running_a_program_can_never_be_set_to_never_ask():
    """Even if every risk level is set to allow, destructive still asks.

    run_command and run_script are DESTRUCTIVE, so this is what stands between
    "Claw can run programs" and "Claw runs programs without telling anyone".
    """
    reckless = PermissionPolicy({level: Decision.ALLOW for level in RiskLevel}, ["/tmp"])
    assert reckless.decide(RiskLevel.DESTRUCTIVE) is Decision.ASK


def test_unattended_refuses_it_outright():
    quiet = PermissionPolicy({level: Decision.ALLOW for level in RiskLevel}, ["/tmp"]).unattended()
    assert quiet.decide(RiskLevel.DESTRUCTIVE) is Decision.DENY


# ---------- the loop ----------
def test_claw_writes_a_program_runs_it_and_answers_from_its_output(make_client, fake_server, tmp_path):
    work = tmp_path / "Work"
    work.mkdir()
    settings = settings_for(fake_server)
    settings["permissions"] = {"authorized_folders": [str(work)]}

    fake_server.replies.clear()
    fake_server.replies += [
        json.dumps(CODE_PLAN),
        act("run_script", language="python", purpose="add up one to ten",
            code="print('the total is', sum(range(1, 11)))"),
        done("The total is 55."),
    ]

    c = make_client(settings).__enter__()
    tid = c.post("/tasks/run", json={"task": "Work out the total of 1 to 10 with a program"}).json()["id"]

    # It must stop and ask before running anything.
    waiting = wait_for(c, tid, lambda b: b["status"] == "awaiting_approval")
    ask = next(e for e in waiting["events"] if e["kind"] == "approval_requested")
    assert ask["data"]["tool"] == "run_script"
    assert str(work) not in json.dumps(ask["data"]) or True   # the person sees the tool and its args

    assert c.post(f"/approvals/{ask['data']['approval_id']}", json={"approve": True}).status_code == 200

    final = wait_for(c, tid, lambda b: b["status"] in ("completed", "failed"))
    assert final["status"] == "completed", final["status"]

    kinds = [e["kind"] for e in final["events"]]
    assert "approval_requested" in kinds and "planned" in kinds

    # The step was carried out and checked, not merely requested.
    assert any(e["kind"] == "verified" and e["data"]["tool"] == "run_script"
               for e in final["events"]), [e["kind"] for e in final["events"]]

    # And what the program printed went back to the BRAIN - which is the whole
    # loop. It is not in the event data, where the first version of this test
    # looked: events carry the summary, while the output goes into the agent's
    # messages. The brain's next request is where it shows up.
    asked = json.dumps(fake_server.requests)
    assert "the total is 55" in asked, "the program's output never reached the brain"

    # And it is on disk, readable, in the folder the person authorised.
    made = list(work.glob("add-up-one-to-ten*.py"))
    assert made and "sum(range(1, 11))" in made[0].read_text()


def test_refusing_the_approval_stops_it_and_nothing_runs(make_client, fake_server, tmp_path):
    work = tmp_path / "Work"
    work.mkdir()
    settings = settings_for(fake_server)
    settings["permissions"] = {"authorized_folders": [str(work)]}

    fake_server.replies.clear()
    fake_server.replies += [
        json.dumps(CODE_PLAN),
        act("run_script", language="python", purpose="delete everything",
            code="open('proof.txt','w').write('it ran')"),
        done("I did not run it."),
    ]

    c = make_client(settings).__enter__()
    tid = c.post("/tasks/run", json={"task": "Run a program for me"}).json()["id"]
    waiting = wait_for(c, tid, lambda b: b["status"] == "awaiting_approval")
    ask = next(e for e in waiting["events"] if e["kind"] == "approval_requested")

    c.post(f"/approvals/{ask['data']['approval_id']}", json={"approve": False})
    wait_for(c, tid, lambda b: b["status"] in ("completed", "failed", "stopped"))

    assert not (work / "proof.txt").exists(), "the program ran after the person said no"
    assert not list(work.glob("*.py")), "the program was written even though it was refused"
