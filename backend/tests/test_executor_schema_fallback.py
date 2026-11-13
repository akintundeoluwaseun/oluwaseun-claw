"""The executor's schema: a retry's safety net, and grammar-safe when used.

Two separate problems, both measured with a real Qwen3.5-2B
(research/performance-audit/):

1. ACTION_SCHEMA was sent on EVERY call. A server turns it into a GBNF
   grammar, and the cheapest reply satisfying that grammar is
   {"action": "finish"} - the model finishing without doing anything, which
   is the false completion executor.py already carries three guards against.

2. maxLength becomes that many grammar repetitions. final_answer's 4000
   produced a 42,081-byte grammar that llama.cpp's own parser refuses:
   "number of rules that are going to be repeated multiplied by the new
   repetition exceeds sane defaults". Sending it segfaulted the process
   (llama-cpp-python, exit 139). Stripped, the grammar is 1,470 bytes and the
   same call returns a valid action.

The length limits are not lost. They stay on ACTION_SCHEMA, which is what
pydantic validates the reply against - a length cap is a check on what came
back, not something a grammar should spend thousands of rules on.
"""

import json

import pytest
from pydantic import ValidationError

from claw.agent.executor import (
    ACTION_SCHEMA,
    ACTION_SCHEMA_FOR_MODEL,
    ModelAction,
    without_length_limits,
)


def _max_lengths(obj):
    found = []
    if isinstance(obj, dict):
        if "maxLength" in obj:
            found.append(obj["maxLength"])
        for v in obj.values():
            found += _max_lengths(v)
    elif isinstance(obj, list):
        for v in obj:
            found += _max_lengths(v)
    return found


def test_what_the_model_is_sent_has_no_length_limits():
    assert _max_lengths(ACTION_SCHEMA_FOR_MODEL) == []


def test_what_the_reply_is_validated_against_keeps_them():
    """Dropping the caps from the grammar must not drop them from validation."""
    assert 4000 in _max_lengths(ACTION_SCHEMA)
    assert 1000 in _max_lengths(ACTION_SCHEMA)


def test_the_limits_are_still_enforced_on_a_real_reply():
    with pytest.raises(ValidationError):
        ModelAction.model_validate({"action": "finish", "final_answer": "x" * 4001})
    ok = ModelAction.model_validate({"action": "finish", "final_answer": "x" * 400})
    assert ok.action == "finish"


def test_nothing_else_about_the_schema_changed():
    """Only maxLength goes. The action enum is the part worth constraining."""
    assert ACTION_SCHEMA_FOR_MODEL["properties"]["action"]["enum"] == ["tool", "finish"]
    assert ACTION_SCHEMA_FOR_MODEL["required"] == ACTION_SCHEMA["required"]
    assert set(ACTION_SCHEMA_FOR_MODEL["properties"]) == set(ACTION_SCHEMA["properties"])


def test_it_strips_at_every_depth():
    nested = {"a": {"b": [{"maxLength": 9, "type": "string"}], "maxLength": 3}}
    assert _max_lengths(without_length_limits(nested)) == []


def test_it_does_not_mutate_what_it_is_given():
    before = json.dumps(ACTION_SCHEMA, sort_keys=True)
    without_length_limits(ACTION_SCHEMA)
    assert json.dumps(ACTION_SCHEMA, sort_keys=True) == before


def test_the_grammar_this_produces_is_far_smaller():
    """The whole point: 42,081 bytes of grammar became 1,470."""
    pytest.importorskip("llama_cpp")
    from llama_cpp.llama_grammar import json_schema_to_gbnf

    big = len(json_schema_to_gbnf(json.dumps(ACTION_SCHEMA)))
    small = len(json_schema_to_gbnf(json.dumps(ACTION_SCHEMA_FOR_MODEL)))
    assert small < big / 10, f"{big} -> {small}"


# ---------- the retry, not the first attempt ----------

@pytest.mark.asyncio
async def test_the_first_action_call_is_unconstrained():
    """Constraining it makes {"action":"finish"} the cheapest valid reply."""
    from claw.agent.executor import _next_action
    from claw.models.base import ChatMessage

    seen = []

    class Adapter:
        provider = model = "t"

        async def chat(self, messages, json_schema=None):
            seen.append(json_schema)
            return '{"action":"tool","tool":"take_screenshot","args":{}}'

    act = await _next_action(Adapter(), [ChatMessage(role="user", content="go")],
                             lambda *a, **k: None, 1)
    assert act is not None and act.tool == "take_screenshot"
    assert seen == [None], "the first call must carry no schema"


@pytest.mark.asyncio
async def test_a_rejected_action_is_retried_with_the_stripped_schema():
    from claw.agent.executor import _next_action
    from claw.models.base import ChatMessage

    seen = []
    replies = ["not json", '{"action":"finish","final_answer":"done"}']

    class Adapter:
        provider = model = "t"

        async def chat(self, messages, json_schema=None):
            seen.append(json_schema)
            return replies.pop(0)

    act = await _next_action(Adapter(), [ChatMessage(role="user", content="go")],
                             lambda *a, **k: None, 1)
    assert act is not None and act.action == "finish"
    assert seen[0] is None
    assert seen[1] == ACTION_SCHEMA_FOR_MODEL, "the retry must send the grammar-safe schema"
    assert _max_lengths(seen[1]) == [], "a retry must never send the 42KB-grammar schema"
