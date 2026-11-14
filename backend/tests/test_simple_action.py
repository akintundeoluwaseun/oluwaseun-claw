"""Tier B: one obvious action skips the planning call.

Measured on a real 2B (research/performance-audit/): "Open Notepad" spent
19.6 seconds planning a one-step plan, then 10.4 more choosing the action.
A plan earns that when a task has shape to discover. For a single obvious
action it is a toll.

Nothing about approval changes. The executor still chooses the tool and its
arguments and decide() still asks the person: the plan was only ever advice,
and these tests pin that down.

The bias is one-sided on purpose. Treating a multi-step job as one action
gives a confident wrong answer; treating a simple action as complex costs only
the planning call it costs today. So everything here is a reason to say no.
"""

import pytest

from claw.agent.executor import fitting_tools
from claw.agent.simple_action import one_step_plan, single_action
from claw.permissions.policy import Decision, PermissionPolicy, RiskLevel
from claw.tools.registry import build_registry


@pytest.fixture(scope="module")
def registry():
    return build_registry()


SIMPLE = ["Open Notepad", "Take a screenshot", "Create a folder called Reports",
          "Tidy up my Downloads, it is a mess", "Sort my Downloads into folders"]

NOT_SIMPLE = [
    "Open Notepad and type my shopping list",        # two jobs
    "Join the three invoices into one PDF and email it",
    "Research five companies and put them in a spreadsheet",
    "Find the latest PDF in Downloads and summarise it",
    "Make a flyer for a back to school sale",        # no single matching tool
    "Open Calculator",                               # nothing matched: plan as usual
    "find every invoice from March, total them and tell me who owes most",
]


@pytest.mark.parametrize("task", SIMPLE)
def test_one_obvious_action_is_recognised(task, registry):
    assert single_action(task, registry, fitting_tools) is not None


@pytest.mark.parametrize("task", NOT_SIMPLE)
def test_anything_less_than_obvious_is_planned_as_usual(task, registry):
    assert single_action(task, registry, fitting_tools) is None


def test_a_second_job_joined_by_a_conjunction_is_never_simple(registry):
    """'and email it' is the difference between one action and two, and the
    curated matcher cannot see it - both match exactly one tool."""
    for joiner in ("and send it", "then delete them", "; email it", ", then print it"):
        assert single_action(f"Join the invoices {joiner}", registry, fitting_tools) is None


def test_tools_that_disagree_about_risk_are_not_simple(registry):
    """If the matched tools disagree about how risky the work is, the
    permission shown to the person would be a guess."""
    import types

    def two_minds(task, reg):
        return ["take_screenshot", "create_folder"]   # read_only vs local_write

    assert single_action("do a thing", registry, two_minds) is None


def test_several_tools_that_agree_are_fine(registry):
    """'Open Notepad' matches launch_app, type_text and press_keys - all
    desktop, all local_write. The executor picks which to call, as always."""
    assert single_action("Open Notepad", registry, fitting_tools) == "launch_app"


# ---------- the synthesised plan ----------

def test_the_plan_has_one_step_and_the_real_permission(registry):
    policy = PermissionPolicy({RiskLevel.LOCAL_WRITE: Decision.ASK}, ["/tmp"])
    spec = registry.get("create_folder")
    plan = one_step_plan("Create a folder called Reports", spec, policy)
    assert len(plan.steps) == 1
    step = plan.steps[0]
    assert step.capability == spec.capability
    assert step.risk == spec.risk
    assert step.permission == policy.decide(spec.risk), "the permission must be the real one"


def test_the_step_is_the_persons_own_words(registry):
    """Anything else would be Claw inventing detail it has not earned."""
    spec = registry.get("take_screenshot")
    plan = one_step_plan("Take a screenshot", spec, PermissionPolicy({}, ["/tmp"]))
    assert plan.steps[0].description == "Take a screenshot"
    assert plan.goal == "Take a screenshot"


def test_a_destructive_tool_still_has_to_be_asked_about(registry):
    """Skipping the planning call must not skip an approval."""
    policy = PermissionPolicy({RiskLevel.DESTRUCTIVE: Decision.ALLOW}, ["/tmp"])
    assert policy.decide(RiskLevel.DESTRUCTIVE) == Decision.ASK, "the floor still holds"


def test_a_multiline_request_is_never_simple(registry):
    assert single_action("Open Notepad\nthen type the list", registry, fitting_tools) is None


def test_an_empty_request_is_never_simple(registry):
    assert single_action("", registry, fitting_tools) is None
    assert single_action("   ", registry, fitting_tools) is None


# ---------- naming the tools that fit, for the planner ----------

def test_the_note_names_the_tool_that_fits(registry):
    """The planner knows capabilities, not tools: grep its prompt for a tool
    name and you find none. That is why "tidy up" became one step per year."""
    from claw.agent.simple_action import tools_note

    note = tools_note("Organise the Downloads folder into subfolders by type", registry, fitting_tools)
    assert "sort_into_folders" in note


def test_the_note_is_empty_when_nothing_fits(registry):
    from claw.agent.simple_action import tools_note

    assert tools_note("What is the weather", registry, fitting_tools) == ""


def test_the_note_states_a_fact_and_stops(registry):
    """Measured: naming the tools keeps 13/16 and fixes the runaway. Telling
    the model what to conclude ("prefer one step over many") dropped it to
    12/16 by pushing an analysis task onto create_spreadsheet."""
    from claw.agent.simple_action import tools_note

    note = tools_note("Tidy up my Downloads, it is a mess", registry, fitting_tools).lower()
    for pushy in ("prefer", "instead of", "rather than", "should", "must"):
        assert pushy not in note, f"the note must not instruct: found {pushy!r}"


def test_the_note_is_bounded(registry):
    from claw.agent.simple_action import tools_note

    note = tools_note("Open Notepad", registry, fitting_tools)
    assert note.count(",") <= 3, "at most four tools are named"
