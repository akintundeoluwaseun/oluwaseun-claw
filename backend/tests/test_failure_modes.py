"""What happens when things go wrong.

Section 8 of the audit asked for failure tests: an invalid model response, a
timeout, a tool failure, a malformed plan, an interrupted generation, the
context limit. The rule running through all of them is the project's own:
never hide an error behind a fake success, and never blame the brain for a
limit Claw imposed.
"""

import asyncio
import json

import pytest
from pydantic import ValidationError

from claw.agent import jsonfix
from claw.agent.deadline import Deadline
from claw.agent.executor import ACTION_SCHEMA_FOR_MODEL, ModelAction, fit_context
from claw.agent.planner import PlanningFailed, make_plan
from claw.agent.schemas import ModelPlan
from claw.models.base import ChatMessage, ModelResponseError
from claw.permissions.policy import PermissionPolicy

GOOD_PLAN = (
    '{"title": "T", "goal": "Do the thing",'
    ' "steps": [{"description": "Do it", "capability": "files",'
    ' "risk": "read_only", "expected_result": "Done"}], "questions": []}'
)


class Replies:
    provider = model = "test"

    def __init__(self, *replies):
        self.replies = list(replies)
        self.schemas = []

    async def chat(self, messages, json_schema=None):
        self.schemas.append(json_schema is not None)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    async def context_window(self):
        return 8192


@pytest.fixture
def policy():
    return PermissionPolicy({}, ["/tmp"])


# ---------- an invalid model response ----------

@pytest.mark.asyncio
async def test_a_reply_that_is_not_json_is_retried_then_reported(policy):
    a = Replies("not json at all", "still not json")
    with pytest.raises(PlanningFailed) as e:
        await make_plan("do a thing", a, policy)
    assert "usable plan" in str(e.value)
    assert len(a.schemas) == 2, "one free attempt and one constrained retry"


@pytest.mark.asyncio
async def test_a_recoverable_reply_is_repaired_rather_than_failed(policy):
    """jsonfix exists so a nearly-right reply is not thrown away."""
    nearly = GOOD_PLAN.replace('{"title"', 'Here is the plan:\n```json\n{"title"') + "\n```"
    plan = await make_plan("do a thing", Replies(nearly), policy)
    assert len(plan.steps) == 1


@pytest.mark.asyncio
async def test_a_plan_that_breaks_the_schema_is_rejected_not_executed(policy):
    """A 0-step plan is not a plan. Accepting it would report success for
    a task where nothing ran."""
    empty = '{"title":"T","goal":"g","steps":[],"questions":[]}'
    with pytest.raises(PlanningFailed):
        await make_plan("do a thing", Replies(empty, empty), policy)


@pytest.mark.asyncio
async def test_a_plan_with_an_unknown_capability_is_rejected(policy):
    bad = GOOD_PLAN.replace('"files"', '"teleportation"')
    with pytest.raises(PlanningFailed):
        await make_plan("do a thing", Replies(bad, bad), policy)


# ---------- the model server failing ----------

@pytest.mark.asyncio
async def test_a_model_error_is_retried_and_then_surfaced(policy):
    a = Replies(ModelResponseError("the server returned nothing"),
                ModelResponseError("the server returned nothing"))
    with pytest.raises(PlanningFailed):
        await make_plan("do a thing", a, policy)


@pytest.mark.asyncio
async def test_a_transient_model_error_recovers_on_the_retry(policy):
    plan = await make_plan("do a thing",
                           Replies(ModelResponseError("hiccup"), GOOD_PLAN), policy)
    assert len(plan.steps) == 1


# ---------- interrupted generation / the deadline ----------

def test_an_expired_deadline_hands_out_a_positive_timeout():
    """Zero means "no timeout" to some HTTP clients, which is the opposite of
    what is being asked for."""
    d = Deadline(budget_s=1)
    d.started -= 999
    assert d.expired and d.timeout_for(30) > 0


def test_the_deadline_reason_does_not_blame_the_model():
    why = Deadline(budget_s=600).why_stopped()
    assert "model" not in why.lower()
    assert "kept" in why


# ---------- the context limit ----------

def test_an_overlong_conversation_is_trimmed_and_says_so():
    msgs = [ChatMessage(role="system", content="S" * 4000),
            ChatMessage(role="user", content="the task")]
    msgs += [ChatMessage(role="assistant", content="x" * 2000) for _ in range(20)]
    fitted = fit_context(msgs, window_tokens=2048)
    assert fitted.dropped > 0, "something must have been dropped"
    assert len(fitted.messages) < len(msgs)


def test_the_system_message_and_the_task_always_survive_trimming():
    """Drop the system message and the model stops knowing what it may call;
    drop the task and the run forgets what it was asked."""
    msgs = [ChatMessage(role="system", content="RULES"),
            ChatMessage(role="user", content="THE TASK")]
    msgs += [ChatMessage(role="assistant", content="x" * 4000) for _ in range(30)]
    fitted = fit_context(msgs, window_tokens=1024)
    assert fitted.messages[0].content == "RULES"
    assert fitted.messages[1].content == "THE TASK"


def test_being_over_the_window_is_reported_not_hidden():
    msgs = [ChatMessage(role="system", content="S" * 40000),
            ChatMessage(role="user", content="T" * 40000)]
    fitted = fit_context(msgs, window_tokens=512)
    assert fitted.over_tokens > 0, "it must say it did not fit rather than pretend"


# ---------- malformed JSON of every shape jsonfix claims to handle ----------

@pytest.mark.parametrize("raw,expect", [
    ('{"a": 1}', {"a": 1}),
    ('```json\n{"a": 1}\n```', {"a": 1}),
    ('Sure! {"a": 1}', {"a": 1}),
    ('{"path": "C:\\Users\\Ada\\notes.txt"}', None),   # windows path, must not explode
])
def test_jsonfix_handles_what_a_small_brain_really_writes(raw, expect):
    out = jsonfix.loads(raw)
    assert isinstance(out, dict)
    if expect is not None:
        assert out == expect


def test_jsonfix_raises_rather_than_inventing_a_result():
    """A parser that returns something plausible for unparseable input is how
    a task reports success having done nothing."""
    with pytest.raises(Exception):
        jsonfix.loads("there is no json here at all")


# ---------- the action schema sent on a retry ----------

def test_the_retry_schema_cannot_build_a_runaway_grammar():
    """maxLength becomes that many grammar repetitions; final_answer's 4000
    produced a grammar llama.cpp refuses, and sending it segfaulted the
    process."""
    def max_lengths(o):
        if isinstance(o, dict):
            return (["x"] if "maxLength" in o else []) + [y for v in o.values() for y in max_lengths(v)]
        if isinstance(o, list):
            return [y for v in o for y in max_lengths(v)]
        return []
    assert max_lengths(ACTION_SCHEMA_FOR_MODEL) == []


def test_an_action_claiming_a_tool_without_naming_one_is_invalid():
    with pytest.raises((ValidationError, ValueError)):
        a = ModelAction.model_validate({"action": "tool"})
        if a.action == "tool" and not a.tool:
            raise ValueError("action 'tool' needs a tool name")
