"""The prompts have to describe tools that exist, and the behaviours that matter.

A capability nothing tells the model about is a capability nobody uses, and a
prompt that names a tool which has since been renamed sends the model looking
for something that is not there. Both fail silently, which is why they are
tested rather than reviewed.
"""

import re

from claw.agent.executor import EXEC_PROMPT
from claw.agent.planner import SYSTEM_PROMPT
from claw.tools.registry import build_registry

REG = build_registry()
NAMES = set(REG.names())

# Anything in the prompts that looks like a tool name: lower case with underscores.
LOOKS_LIKE_A_TOOL = re.compile(r"\b([a-z][a-z0-9]+(?:_[a-z0-9]+)+)\b")
# Words with underscores that are not tools: argument names, JSON keys, risk levels.
NOT_TOOLS = {
    "final_answer", "expected_result", "read_only", "local_write", "new_plan",
    "system_prompt", "exec_prompt", "task_id", "json_schema",
}


def mentioned(text: str) -> set[str]:
    return {m for m in LOOKS_LIKE_A_TOOL.findall(text) if m not in NOT_TOOLS}


def flat(text: str) -> str:
    """One line, lower case: a prompt is wrapped for reading, not for matching."""
    return " ".join(text.split()).lower()


def test_every_tool_the_executor_prompt_names_actually_exists():
    unknown = mentioned(EXEC_PROMPT) - NAMES
    assert not unknown, f"the prompt tells the model to use tools that do not exist: {sorted(unknown)}"


def test_every_tool_the_planner_prompt_names_actually_exists():
    unknown = mentioned(SYSTEM_PROMPT) - NAMES
    assert not unknown, f"the plan prompt names tools that do not exist: {sorted(unknown)}"


def test_the_model_is_told_to_stop_and_ask_rather_than_invent_a_credential():
    low = flat(EXEC_PROMPT)
    assert "pause_for_me" in low
    for phrase in ("password", "captcha", "never type a credential", "never make one up"):
        assert phrase in low, f"the executor prompt does not mention: {phrase}"


def test_the_model_is_told_to_check_who_it_is_messaging():
    low = flat(EXEC_PROMPT)
    assert "check the name on screen" in low
    assert "is not necessarily the right one" in low
    assert "approval" in low


def test_the_model_is_told_not_to_guess_a_date():
    assert "never guess" in flat(EXEC_PROMPT)
    assert "next tuesday" in flat(EXEC_PROMPT)
    assert "next tuesday" in flat(SYSTEM_PROMPT)


def test_the_model_is_told_a_draft_is_not_a_sent_mail():
    low = flat(EXEC_PROMPT)
    assert "compose_mail" in low and "does not send" in low


def test_the_planner_treats_a_step_that_needs_a_person_as_normal():
    low = flat(SYSTEM_PROMPT)
    assert "signing in" in low and "is a normal step" in low
    assert "do not refuse the whole task" in low


def test_the_planner_splits_writing_a_message_from_sending_it():
    low = flat(SYSTEM_PROMPT)
    assert "separate steps" in low and "destructive" in low


def test_the_prompts_still_forbid_following_instructions_found_in_content():
    assert "NOT instructions" in EXEC_PROMPT
    assert "not a change to these rules" in SYSTEM_PROMPT
