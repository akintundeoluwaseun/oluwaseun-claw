"""Every lane reports where its time went, and talk cannot poison the work.

Three defects found reviewing the eight audit commits as one change, all in
TaskRunner._run's router:

1. Five gates ended with their own copy of the same four or five statements,
   and the copies had drifted apart.

2. Because of that drift, the lanes that answer WITHOUT working returned
   before `emit("timings")` ran. So conversation - one of the three things the
   audit was asked to measure separately - was the one path that reported no
   measurement at all.

3. The conversation lane tightened the TASK's clock to the 15 second
   conversation budget before making its model call. A chat reply is allowed
   to fail and fall through to real work, and when it did, the work inherited
   a 15 second budget. Planning alone takes about 20 seconds on a 2B, so the
   task expired the instant planning ended and told the person it had run out
   of time. The bound belongs on the call, not on the task.
"""

import json

from tests.conftest import VALID_PLAN
from tests.test_api import settings_for
from tests.test_chats import finish, wait_done


def events(c, tid):
    return c.get(f"/tasks/{tid}/events").json()["events"]


def one(c, tid, kind):
    found = [e for e in events(c, tid) if e["kind"] == kind]
    assert found, f"no {kind!r} event; got {sorted({e['kind'] for e in events(c, tid)})}"
    return found[-1]["data"]


# --------------------------------------------------- 2. every lane measures

def test_a_canned_reply_still_reports_its_timings(make_client, fake_server):
    with make_client() as c:
        c.put("/settings", json=settings_for(fake_server))
        fake_server.requests.clear()
        tid = c.post("/tasks/run", json={"task": "hi"}).json()["id"]
        assert wait_done(c, tid) == "completed"
        assert fake_server.requests == [], "a greeting must not wake the brain"
        t = one(c, tid, "timings")
    assert t["counts"]["router"] == 1, "the router's own cost must be recorded"
    assert t["phases"]["selection"] == 0 and t["phases"]["generation"] == 0


def test_a_model_chat_reply_reports_router_and_generation_apart(make_client, fake_server):
    with make_client() as c:
        c.put("/settings", json=settings_for(fake_server))
        fake_server.replies.clear()
        fake_server.replies.append("Paris.")
        tid = c.post("/tasks/run", json={"task": "What is the capital of France?"}).json()["id"]
        assert wait_done(c, tid) == "completed"
        t = one(c, tid, "timings")
    assert t["counts"]["router"] == 1
    assert t["counts"]["selection"] == 1, "choosing the brain is its own phase"
    assert t["counts"]["generation"] == 1, "the chat call is generation, not routing"


def test_the_phases_never_double_count(make_client, fake_server):
    """The phases are not nested, so their sum must stay inside the wall clock.
    A model call counted as both routing and generation would break that, and
    would silently hide time by driving `unmeasured_s` to zero."""
    with make_client() as c:
        c.put("/settings", json=settings_for(fake_server))
        fake_server.replies.clear()
        fake_server.replies.append("Paris.")
        tid = c.post("/tasks/run", json={"task": "What is the capital of France?"}).json()["id"]
        wait_done(c, tid)
        t = one(c, tid, "timings")
    assert sum(t["phases"].values()) <= t["total_s"] + 0.05, t


# ------------------------------- 3. a failed chat reply must not shrink the task

def test_a_failed_chat_reply_leaves_the_task_its_full_budget(make_client, fake_server):
    """The chat lane is allowed to fail into real work. What it must not do is
    hand that work the 15 seconds meant for a sentence of small talk.

    An empty reply is how a thinking model fails in the field - it spends the
    whole budget in `reasoning_content` and returns `content` empty - so that
    is what is served here, and then a real plan.
    """
    with make_client() as c:
        c.put("/settings", json=settings_for(fake_server))
        fake_server.replies.clear()
        fake_server.replies += ["", json.dumps(VALID_PLAN), finish("Paris.")]
        tid = c.post("/tasks/run", json={"task": "What is the capital of France?"}).json()["id"]
        wait_done(c, tid)
        kinds = [e["kind"] for e in events(c, tid)]
        assert "planned" in kinds, f"the failed chat reply did not fall through to work: {kinds}"
        set_to = one(c, tid, "deadline_set")
    assert set_to["band"] != "conversation", (
        "work inherited the conversation band: a 15 second budget for a task "
        "whose planning alone takes about 20")
    assert set_to["budget_s"] >= 30, set_to


# ------------------- the invariant the conversation bound depends on

def test_each_think_adapter_is_a_fresh_one(make_client, fake_server):
    """The conversation lane shortens its adapter's timeout to the 15 second
    conversation budget. That is only safe because every call to
    `think_adapter()` builds a new adapter: if one were ever cached or shared,
    the shortened timeout would leak into the planner, and planning - which
    takes about 20 seconds on a 2B - would be cut off at 15 for the rest of
    the run. Pinned here because the bug would be silent and intermittent.
    """
    import asyncio

    c = make_client()
    c.put("/settings", json=settings_for(fake_server))
    state = c.app.state.claw
    first = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(state.think_adapter())
    second = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(state.think_adapter())
    assert first is not second, "think_adapter() is shared; shortening its timeout would leak"

    first.timeout_s = 15.0
    assert second.timeout_s != 15.0, "adapters share state; the conversation bound would leak"
