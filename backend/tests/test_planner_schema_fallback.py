"""The schema constrains a RETRY, never the first attempt.

Passing json_schema makes llama-server build a GBNF grammar from it, and a
grammar-constrained 2B writes the cheapest structure that satisfies the
grammar rather than the best plan. Measured on the 16 held-out tasks with a
real Qwen3.5-2B (research/performance-audit/):

    always constrained   9/16 correct, 1.0 steps per plan, 15.3 s/task
    free then constrained 13/16 correct, 2.6 steps per plan, 20.6 s/task

The grammar was collapsing real multi-step work into one step. Free output is
better and jsonfix repairs it; the grammar stays as the net under the retry,
so a second attempt still cannot come back malformed.
"""

import pytest

from claw.agent.planner import make_plan
from claw.agent.schemas import ModelPlan
from claw.permissions.policy import PermissionPolicy

GOOD = (
    '{"title": "Join invoices", "goal": "Join the invoices into one PDF",'
    ' "steps": [{"description": "Join the three invoices into one PDF",'
    ' "capability": "documents", "risk": "local_write",'
    ' "expected_result": "One PDF holding all three"}], "questions": []}'
)


class Recorder:
    """Records whether each call carried a schema, and replies as told."""

    provider = "test"
    model = "test"

    def __init__(self, replies):
        self.replies = list(replies)
        self.schemas = []

    async def chat(self, messages, json_schema=None):
        self.schemas.append(json_schema is not None)
        return self.replies.pop(0)

    async def context_window(self):
        return 8192


@pytest.fixture
def policy():
    return PermissionPolicy({}, ["/tmp"])


@pytest.mark.asyncio
async def test_the_first_attempt_is_not_constrained(policy):
    """The model writes freely, which is where the better plan comes from."""
    a = Recorder([GOOD])
    await make_plan("Join the three invoices into one PDF", a, policy)
    assert a.schemas == [False], "the first call must carry no schema"


@pytest.mark.asyncio
async def test_a_retry_is_constrained(policy):
    """One bad reply, then the grammar makes the second one well-formed."""
    a = Recorder(["not json at all", GOOD])
    plan = await make_plan("Join the three invoices into one PDF", a, policy)
    assert a.schemas == [False, True], "the retry must carry the schema"
    assert len(plan.steps) == 1


@pytest.mark.asyncio
async def test_the_budget_is_one_free_attempt_and_one_constrained_retry(policy):
    """MAX_ATTEMPTS is 2, so there is exactly one retry and it is the
    constrained one. Two bad replies is a PlanningFailed, not a third try."""
    from claw.agent.planner import MAX_ATTEMPTS, PlanningFailed

    assert MAX_ATTEMPTS == 2, "the strategy below assumes one free try and one retry"
    a = Recorder(["nope", "still nope"])
    with pytest.raises(PlanningFailed):
        await make_plan("Join the three invoices into one PDF", a, policy)
    assert a.schemas == [False, True]


@pytest.mark.asyncio
async def test_the_schema_passed_is_the_plan_schema(policy):
    """A retry constrained by the wrong schema would be worse than none."""
    seen = {}

    class Capture(Recorder):
        async def chat(self, messages, json_schema=None):
            if json_schema is not None:
                seen["schema"] = json_schema
            return await super().chat(messages, json_schema=json_schema)

    a = Capture(["bad", GOOD])
    await make_plan("Join the three invoices into one PDF", a, policy)
    assert seen["schema"] == ModelPlan.model_json_schema()


@pytest.mark.asyncio
async def test_a_good_first_reply_costs_exactly_one_call(policy):
    """Making the schema a fallback must not add a round trip."""
    a = Recorder([GOOD])
    await make_plan("Join the three invoices into one PDF", a, policy)
    assert len(a.schemas) == 1
