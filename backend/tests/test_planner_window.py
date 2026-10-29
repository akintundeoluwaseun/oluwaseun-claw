"""Planning against a model whose context is too small.

The planning prompt is about 2,058 tokens with room for a reply. A model
trained at 2,048 cannot hold it, and llama.cpp clamps -c DOWN to the model's
trained context, so this happens to anyone who imports a small model however
large the engine's flag was.

Before this, the server answered 400 and the person saw
"The model server returned an error (400)" as a 502 - nothing they could act
on. Found by the first real Windows build, where a tiny imported model met a
2,158-token prompt.
"""

import json

import pytest

from claw.agent.planner import PlanningFailed, make_plan
from claw.config import DEFAULT_MODES
from claw.models.base import ModelError
from claw.models.openai_compat import OpenAICompatAdapter
from claw.permissions.policy import PermissionPolicy
from tests.fake_model_server import FakeModelServer

GOOD_PLAN = json.dumps({
    "goal": "Write a short note",
    "steps": [{
        "description": "Write the note to a file",
        "capability": "files",
        "risk": "local_write",
        "expected_result": "A file containing the note",
    }],
    "questions": [],
})


def adapter_for(base_url: str) -> OpenAICompatAdapter:
    a = OpenAICompatAdapter(base_url=base_url, model="tiny", timeout_s=10, temperature=0.2)
    a.api_key = "test-key"
    return a


def policy() -> PermissionPolicy:
    return PermissionPolicy(dict(DEFAULT_MODES), [])


async def test_a_context_too_small_is_explained_not_crashed():
    with FakeModelServer(models=["tiny"]) as srv:
        srv.n_ctx = 2048
        with pytest.raises(PlanningFailed) as got:
            await make_plan("Plan something useful", adapter_for(srv.base_url), policy())
        assert "too small" in got.value.message.lower()
        # The numbers a person needs in order to act are in the details.
        joined = " ".join(got.value.details)
        assert "2048" in joined and "larger context" in joined


async def test_it_is_not_reported_as_a_model_failure():
    # PlanningFailed becomes a 422 ("couldn't make a usable plan"); ModelError
    # becomes a 502. A model that is simply too small is the former - and it
    # must be refused BEFORE the request is sent, not after the server rejects
    # it, or the person gets the raw 400 again.
    assert not issubclass(PlanningFailed, ModelError)
    with FakeModelServer(models=["tiny"]) as srv:
        srv.n_ctx = 2048
        srv.replies.append(GOOD_PLAN)  # would succeed if it were ever sent
        with pytest.raises(PlanningFailed) as got:
            await make_plan("Plan something useful", adapter_for(srv.base_url), policy())
        assert "too small" in got.value.message.lower()
        assert srv.requests == [], "the oversized prompt was sent anyway"


async def test_a_big_enough_model_plans_normally():
    with FakeModelServer(models=["tiny"]) as srv:
        srv.n_ctx = 8192
        srv.replies.append(GOOD_PLAN)
        plan = await make_plan("Write a short note", adapter_for(srv.base_url), policy())
        assert plan.steps and plan.steps[0].description


async def test_a_server_that_will_not_say_is_still_tried():
    # A hosted provider has no /props. Refusing to plan because the window is
    # unknown would break every cloud model, so the attempt still goes ahead.
    with FakeModelServer(models=["tiny"]) as srv:
        srv.n_ctx = None
        srv.replies.append(GOOD_PLAN)
        plan = await make_plan("Write a short note", adapter_for(srv.base_url), policy())
        assert plan.steps
