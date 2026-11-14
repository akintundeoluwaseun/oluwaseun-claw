"""One clock for a whole task.

Each limit Claw already had bounds ONE operation: a model call at 120s, a tool
at 60s, a run at 20 steps. Nothing bounded their product - twenty steps of
(120 + 60) is an hour, with every limit respected and nothing reporting a
problem. The person sees a spinner.

These hold the seven properties the deadline has to have.
"""

import time

import pytest

from claw.agent.deadline import Deadline, band_for
from claw.config import AgentSettings


# ---------- 1. it covers the whole lifecycle, and 2. it never resets ----------

def test_the_clock_does_not_restart():
    d = Deadline(budget_s=10)
    d.started -= 6
    assert pytest.approx(d.remaining_s, abs=0.5) == 4
    # narrowing the band mid-task must not give the 6 seconds back
    d.tighten_to(8, "moderate")
    assert pytest.approx(d.remaining_s, abs=0.5) == 2


def test_tightening_only_ever_lowers():
    """Nothing may hand a running task MORE time - that is the reset."""
    d = Deadline(budget_s=100, band="complex")
    d.tighten_to(600, "extended")
    assert d.budget_s == 100 and d.band == "complex"
    d.tighten_to(30, "simple")
    assert d.budget_s == 30 and d.band == "simple"


def test_time_already_spent_on_planning_still_counts():
    """The clock starts before the router, so planning is inside the budget."""
    d = Deadline(budget_s=60)
    d.started -= 50          # planning took 50s
    d.tighten_to(30, "simple")
    assert d.expired, "a 30s budget cannot survive 50s of planning"


# ---------- 3. expiry stops new work ----------

def test_expired_is_true_only_when_the_budget_is_gone():
    d = Deadline(budget_s=5)
    assert not d.expired
    d.started -= 5.01
    assert d.expired


def test_remaining_never_goes_negative():
    d = Deadline(budget_s=1)
    d.started -= 100
    assert d.remaining_s == 0


def test_an_operation_gets_the_lesser_of_its_own_limit_and_what_is_left():
    d = Deadline(budget_s=100)
    assert d.timeout_for(30) == 30            # plenty of time: its own limit
    d.started -= 90
    assert pytest.approx(d.timeout_for(30), abs=0.5) == 10   # nearly out: what is left


def test_a_spent_budget_still_gives_a_positive_timeout():
    """Handing 0 to an HTTP client means 'no timeout' in some of them, which
    is the opposite of what is being asked for."""
    d = Deadline(budget_s=1)
    d.started -= 100
    assert d.timeout_for(30) > 0


# ---------- 4. the reason is honest and readable ----------

def test_the_reason_says_what_happened_and_keeps_the_work():
    why = Deadline(budget_s=600).why_stopped()
    assert "600" in why
    assert "stopped before it finished" in why
    assert "kept" in why, "it must not imply the finished work was undone"


# ---------- separate budgets per shape ----------

def test_the_four_budgets_are_configurable_and_ordered():
    a = AgentSettings()
    assert a.conversation_deadline_s < a.simple_deadline_s < a.moderate_deadline_s < a.complex_deadline_s
    assert a.complex_deadline_s == 600, "ten minutes for a complex task"
    assert a.extended_deadline_s > a.complex_deadline_s


@pytest.mark.parametrize("steps,band", [(1, "simple"), (2, "moderate"), (4, "moderate"), (5, "complex"), (20, "complex")])
def test_the_band_follows_the_plan_size(steps, band):
    a = AgentSettings()
    assert band_for(steps, a)[1] == band


def test_each_band_is_actually_that_budget():
    a = AgentSettings()
    assert band_for(1, a)[0] == a.simple_deadline_s
    assert band_for(3, a)[0] == a.moderate_deadline_s
    assert band_for(9, a)[0] == a.complex_deadline_s


# ---------- 7. an approved longer deadline ----------

def test_extended_is_asked_for_never_inferred():
    """A longer deadline is a decision about how long someone will wait."""
    from claw.agent.schemas import PlanRequest
    assert PlanRequest(task="x").extended is False
    assert PlanRequest(task="x", extended=True).extended is True


def test_the_runner_takes_the_flag():
    import inspect
    from claw.agent.runner import TaskRunner
    assert "extended" in inspect.signature(TaskRunner.start).parameters


# ---------- it really stops a run, and reports what happened ----------

@pytest.mark.asyncio
async def test_an_expired_deadline_stops_the_run_before_the_next_step(monkeypatch):
    """Stop launching new operations - checked BEFORE a step, not mid-step."""
    from claw.agent import executor as ex

    calls = []

    async def never(*a, **k):
        calls.append(1)
        raise AssertionError("no model call may start after the deadline")

    monkeypatch.setattr(ex, "_next_action", never)
    d = Deadline(budget_s=1, band="simple")
    d.started -= 100

    out = await _run_with(ex, deadline=d)
    assert out.status == "incomplete"
    assert calls == [], "nothing new may be launched"
    assert "time limit" in (out.error or "")


@pytest.mark.asyncio
async def test_the_incomplete_result_names_the_step_and_keeps_the_work():
    from claw.agent import executor as ex

    d = Deadline(budget_s=1, band="simple")
    d.started -= 100
    out = await _run_with(ex, deadline=d)
    assert out.status == "incomplete"
    assert "step 1" in out.final_answer
    assert "rolled back" not in (out.final_answer + (out.error or "")).lower()
    assert "undone" not in (out.final_answer + (out.error or "")).lower()


@pytest.mark.asyncio
async def test_no_deadline_means_no_change_in_behaviour():
    """Everything that does not pass a deadline must behave exactly as before."""
    from claw.agent import executor as ex

    out = await _run_with(ex, deadline=None)
    assert out.status == "completed"


async def _run_with(ex, deadline):
    """Drive run_agent with a model that finishes at once."""
    from claw.agent.executor import ModelAction

    class Adapter:
        provider = model = "t"

        async def chat(self, messages, json_schema=None):
            return ModelAction(action="finish", final_answer="done").model_dump_json()

        async def context_window(self):
            return 8192

    import tempfile
    from pathlib import Path

    from claw.browser.session import BrowserSession
    from claw.config import Settings
    from claw.permissions.policy import PermissionPolicy
    from claw.tools.base import ToolContext, ToolRegistry

    data = Path(tempfile.mkdtemp())
    settings = Settings()
    ctx = ToolContext(
        settings=settings,
        policy=PermissionPolicy(settings.permissions.modes, [str(data)]),
        data_dir=data,
        browser=BrowserSession(data, lambda: settings.browser),
        task_id="t1",
    )
    return await ex.run_agent("do a thing", "1. do it", Adapter(), ToolRegistry(), ctx,
                              lambda *a, **k: None, _approve, None,
                              window_tokens=8192, deadline=deadline)


async def _approve(payload):
    return True
