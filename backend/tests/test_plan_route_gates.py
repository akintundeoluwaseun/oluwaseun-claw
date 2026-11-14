"""POST /tasks/plan runs the cheap gates too.

"Plan only" called make_plan directly, so none of the six gates in
TaskRunner._run ran. A greeting typed into that box woke the brain and sent
it the whole tool catalogue so it could work out that hello needs no tools -
the exact cost conversation.py exists to avoid, on the one path that skipped
it.
"""

import time
import json

import pytest


@pytest.fixture
def client(make_client):
    return make_client({})


def test_a_greeting_does_not_wake_the_brain(client):
    """This endpoint only ever produces a plan, so a greeting is refused
    rather than answered - but refused WITHOUT a model call, which is the
    whole point. The refusal carries the answer it would have given."""
    r = client.post("/tasks/plan", json={"task": "Hi"})
    assert r.status_code == 422, r.text
    body = r.json()
    assert "nothing to plan" in json.dumps(body).lower()
    tid = r.headers["x-claw-task-id"]
    kinds = [e["kind"] for e in client.get(f"/tasks/{tid}/events").json().get("events", [])]
    assert "model_call" not in kinds, "a greeting must not wake the brain"
    assert "chat_reply" in kinds


def test_one_obvious_action_is_planned_without_a_model(client):
    r = client.post("/tasks/plan", json={"task": "Take a screenshot"})
    assert r.status_code == 200, r.text
    body = r.json()
    events = client.get(f"/tasks/{body['id']}/events").json().get("events", [])
    kinds = [e["kind"] for e in events]
    assert "simple_action" in kinds
    assert "model_call" not in kinds, "one obvious action does not need a planning call"
    assert body["plan"] and len(body["plan"]["steps"]) == 1


def test_the_synthesised_plan_carries_a_real_permission(client):
    body = client.post("/tasks/plan", json={"task": "Take a screenshot"}).json()
    step = body["plan"]["steps"][0]
    assert step["permission"] in ("allow", "ask", "deny")
    assert step["capability"] and step["risk"]


def test_a_real_task_still_reaches_the_planner(client):
    """The gates must not swallow work. No model is configured in this test,
    so a task that needs planning fails at the model - which proves it got
    there."""
    r = client.post("/tasks/plan", json={"task": "Find the latest PDF in Downloads and summarise it"})
    assert r.status_code in (200, 422, 502)
    if r.status_code != 200:
        assert "model" in json.dumps(r.json()).lower() or "plan" in json.dumps(r.json()).lower()


# ---------------------------------------------------------------------------
# A plan request is bounded
#
# The desktop allows this route fifteen minutes (desktop/src/backend.js marks
# it "slow"), and nothing on the backend bounded the planning call, so a
# wedged brain held the person at a spinner for the full quarter of an hour.

import asyncio

import pytest


def test_a_wedged_plan_request_gives_up_and_says_why(make_client, fake_server, monkeypatch):
    from claw.agent import planner

    async def never_answers(self, messages, json_schema=None, *, thinking=True):
        await asyncio.sleep(600)
        return "{}"

    monkeypatch.setattr("claw.models.openai_compat.OpenAICompatAdapter.chat", never_answers)
    # A budget small enough that the test does not take three minutes.
    monkeypatch.setattr(planner, "_MODEL_CALL_CEILING_S", 600.0)

    c = make_client({"model": {"mode": "custom", "provider": "openai_compatible",
                               "base_url": fake_server.base_url, "model": "qwen2.5:7b"},
                     "agent": {"moderate_deadline_s": 10}})
    began = time.monotonic()
    r = c.post("/tasks/plan", json={"task": "Research five suppliers and compare their prices"})
    took = time.monotonic() - began

    assert took < 60, f"the plan request was not bounded: {took:.1f}s"
    assert r.status_code == 504, r.text
    body = r.json()["error"]
    assert body["code"] == "planning_timed_out"
    assert "time limit" in body["message"]
    assert "usable plan" not in body["message"], "it must not blame the brain for Claw's own limit"


def test_an_ordinary_plan_request_is_untouched(make_client, fake_server):
    """The bound must not change the normal case."""
    import json as _json

    from tests.conftest import VALID_PLAN

    fake_server.replies.clear()
    fake_server.replies.append(_json.dumps(VALID_PLAN))
    c = make_client({"model": {"mode": "custom", "provider": "openai_compatible",
                               "base_url": fake_server.base_url, "model": "qwen2.5:7b"}})
    r = c.post("/tasks/plan", json={"task": "Find the latest PDF in Downloads and summarise it"})
    assert r.status_code == 200, r.text
    assert r.json()["plan"]["steps"]
