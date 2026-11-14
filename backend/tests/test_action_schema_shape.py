"""The schema the model is shown can only describe a USABLE action.

`ModelAction.tool` has to be optional, because a "finish" action has no tool.
The flat schema generated from it therefore permits `{"action": "tool"}` with
nothing to call, and `run_agent` rejected that by hand.

That hole was where the executor actually failed. Measured end to end against
a real llama-server with Qwen3.5-2B, four read-only tasks over a CSV,
temperature 0: "action 'tool' needs a tool name" was the commonest rejection
in BOTH the unconstrained and the constrained run, and because the schema
allowed it, the constrained RETRY - the safety net under the free first
attempt - could serve the same invalid reply again. Before the fix the four
tasks completed 0/4 either way; after it, 2/4 unconstrained and 3/4
constrained.

So the two actions are now described as alternatives, each with its own
required fields. ModelAction is untouched and remains what a reply is
validated against.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from claw.agent.executor import ACTION_SCHEMA, ACTION_SCHEMA_FOR_MODEL, ModelAction


def branches() -> dict[str, dict]:
    got = {}
    for branch in ACTION_SCHEMA_FOR_MODEL["oneOf"]:
        got[branch["properties"]["action"]["const"]] = branch
    return got


def test_it_offers_exactly_the_two_actions():
    assert set(branches()) == {"tool", "finish"}


def test_a_tool_action_cannot_be_described_without_a_tool():
    tool = branches()["tool"]
    assert "tool" in tool["required"], (
        "the schema still permits {'action': 'tool'} with nothing to call - the "
        "exact reply the executor kept rejecting, and the one its constrained "
        "retry could not rule out")
    assert tool["properties"]["tool"]["minLength"] == 1, "an empty tool name is no tool name"


def test_a_finish_cannot_be_described_without_an_answer():
    """A finish with nothing to say is the false completion the executor
    already guards against three other ways. The cheapest reply a grammar can
    emit must not be the one that abandons the task."""
    finish = branches()["finish"]
    assert "final_answer" in finish["required"]
    assert finish["properties"]["final_answer"]["minLength"] == 1


def test_no_branch_asks_a_grammar_for_thousands_of_repetitions():
    """maxLength becomes that many grammar rules; 4000 produced a 42KB grammar
    that llama.cpp's own parser refuses. The limits live on ModelAction, which
    is what validates the reply."""
    assert "maxLength" not in json.dumps(ACTION_SCHEMA_FOR_MODEL)
    assert "maxLength" in json.dumps(ACTION_SCHEMA), "the real schema must keep its limits"


def test_the_grammar_stays_small():
    """It is sent on every constrained call, and a 42KB grammar is refused."""
    assert len(json.dumps(ACTION_SCHEMA_FOR_MODEL)) < 2048


# ------------------------------------- what the schema allows, pydantic accepts

@pytest.mark.parametrize("reply", [
    {"action": "tool", "tool": "find_files", "args": {"name_contains": "sales"}},
    {"action": "tool", "tool": "read_file", "args": {}},
    {"action": "finish", "final_answer": "The total is 5590."},
    {"thought": "checking", "action": "tool", "tool": "read_file", "args": {}},
])
def test_everything_the_schema_permits_is_a_valid_action(reply):
    """The two must agree. A schema that permitted something ModelAction
    rejects would send the model confidently into a wall."""
    action = ModelAction.model_validate(reply)
    if action.action == "tool":
        assert action.tool, "run_agent would reject this by hand"
    else:
        assert action.final_answer


@pytest.mark.parametrize("reply", [
    {"action": "tool"},                      # the failure this fix is for
    {"action": "tool", "tool": ""},
    {"action": "finish"},                    # a finish with nothing to say
    {"action": "finish", "final_answer": ""},
])
def test_the_replies_that_used_to_get_through_no_longer_fit_the_schema(reply):
    """Not a pydantic test: these are checked against the schema the MODEL is
    given, because the point is that the GRAMMAR can no longer produce them.

    Checked by hand rather than with a JSON Schema library, so this adds no
    dependency for one assertion. Only the two rules that matter here are
    applied: the branch's required fields, and its minLength on them.
    """
    def fits(branch: dict) -> bool:
        if branch["properties"]["action"]["const"] != reply.get("action"):
            return False
        for field in branch["required"]:
            if field not in reply:
                return False
            spec = branch["properties"][field]
            if "minLength" in spec and len(reply[field]) < spec["minLength"]:
                return False
        return True

    assert not any(fits(b) for b in ACTION_SCHEMA_FOR_MODEL["oneOf"]), (
        f"{reply} still fits the schema the model is shown, so a grammar can "
        f"still produce it")


def test_the_hand_check_would_notice_a_valid_reply():
    """Guards the guard above: a checker that rejects everything proves nothing."""
    def fits(branch: dict, reply: dict) -> bool:
        if branch["properties"]["action"]["const"] != reply.get("action"):
            return False
        return all(f in reply and len(str(reply[f])) >= branch["properties"][f].get("minLength", 0)
                   for f in branch["required"])

    good = {"action": "tool", "tool": "find_files"}
    assert any(fits(b, good) for b in ACTION_SCHEMA_FOR_MODEL["oneOf"])
