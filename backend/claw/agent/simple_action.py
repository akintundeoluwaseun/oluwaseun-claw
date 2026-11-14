"""One obvious action: skip the planning call and just do it.

Measured on a real 2B (research/performance-audit/): "Open Notepad" spent
**19.6 seconds planning a one-step plan**, then 10.4 more choosing the action.
Two model calls, at ~10 tokens a second, to decide something the request
already said. A plan is worth that when a task has shape to discover; for a
single obvious action it is a toll.

So this recognises the narrow case and synthesises the one-step plan locally,
with no model call at all. The executor still chooses the tool and its
arguments, still asks the permission policy, and still asks the person - the
plan was only ever advice, and `decide()` has never trusted it. Nothing about
approval changes, which is why this is safe to skip.

THE BIAS IS ONE-SIDED, deliberately. Treating a multi-step job as one action
produces a one-step plan for work that needs five, which is a bad answer
delivered confidently - the failure this project keeps measuring. Treating a
simple action as complex merely costs the planning call it costs today. So
everything here is a reason to say no, and anything unclear goes the long way.

It is not a keyword list. The decision rests on Claw's own curated matcher,
`fitting_tools`, which already maps a request to the tools that plainly fit
it; this adds only the checks that matcher cannot make - that the request
names ONE job rather than several.
"""

from __future__ import annotations

import re

#: Words that join a second operation to the first. Measured against the
#: curated matcher: "Join the three invoices into one PDF and email it" and
#: "Research five companies and put them in a spreadsheet" both match exactly
#: one tool, and both need a plan. The conjunction is what tells them apart.
_ANOTHER_JOB = re.compile(
    r"\b(?:and|then|after\s+that|afterwards|also|plus|followed\s+by|next)\b|[;]|,\s*(?:then|and)\b",
    re.I)

#: A request long enough to be describing more than one thing. "Open Notepad"
#: is two words; "find every invoice from March, total them and tell me which
#: customer owes most" is not a single action however few tools match it.
MAX_WORDS = 8

#: Several tools may fit one action. "Open Notepad" matches launch_app,
#: type_text and press_keys - all three are `desktop` and all three are
#: `local_write`, so the step is not ambiguous even though the match is not
#: unique: the executor picks which to call, as it always does. What would be
#: ambiguous is tools that DISAGREE about what kind of work this is or how
#: risky it is, because then the permission shown to the person would be a
#: guess. So: any number of fitting tools, provided they agree.
MAX_FITTING = 4


def single_action(task: str, registry, fitting_tools) -> str | None:
    """The one tool this request obviously wants, or None to plan as usual.

    `fitting_tools` is passed in rather than imported so this module does not
    depend on the executor, which is a much heavier import and already depends
    on plenty.
    """
    text = (task or "").strip()
    if not text or "\n" in text:
        return None
    if len(text.split()) > MAX_WORDS:
        return None
    if _ANOTHER_JOB.search(text):
        return None
    fits = fitting_tools(text, registry)
    if not fits or len(fits) > MAX_FITTING:
        return None
    specs = [registry.get(name) for name in fits]
    if not all(specs):
        return None
    if len({s.capability for s in specs}) != 1 or len({s.risk for s in specs}) != 1:
        # The matched tools disagree about what kind of work this is, or how
        # risky. Planning properly is cheaper than showing someone the wrong
        # permission.
        return None
    return fits[0]


def one_step_plan(task: str, spec, policy):
    """The plan a planning call would have produced, built without one.

    Deliberately plain: the description is the person's own words, because
    anything else would be Claw inventing detail it has not earned. The
    capability and risk come from the tool Claw itself matched, so the
    permission the person is shown is the real one - not a guess the model
    made about its own work.
    """
    from claw.agent.schemas import ModelPlanStep, Plan, PlanStep
    from claw.agent.titles import fallback_title

    step = ModelPlanStep(
        description=task.strip(),
        capability=spec.capability,
        risk=spec.risk,
        expected_result=f"{task.strip()} is done.",
    )
    return Plan(
        # The same cleaning every other title gets, so skipping the planning
        # call does not also skip tidying "Please check..." into "Check...".
        title=fallback_title(task),
        goal=task.strip(),
        steps=[PlanStep(index=1, permission=policy.decide(spec.risk), **step.model_dump())],
        questions=[],
        executable=False,
    )


def tools_note(task: str, registry, fitting_tools) -> str:
    """A line naming the tools that already fit, for the planner's request.

    The planner knows capabilities, not tools - grep its prompt for a tool
    name and you find none. So for "Tidy up my Downloads, it is a mess" it
    planned in the abstract and wrote ONE STEP PER YEAR, counting downwards,
    until the token cap stopped it. `fitting_tools` maps that exact request to
    `sort_into_folders`; the planner was simply never told.

    Measured on the held-out 16 (research/performance-audit/):

        no note                 13/16 correct, 1 unusable, 242 tok, 23.8 s
        this note               13/16 correct, 0 unusable, 178 tok, 19.3 s
        this note + "prefer
        one step over many"     12/16 correct, 0 unusable, 151 tok, 16.8 s

    So naming the tools fixes the runaway and costs nothing. Telling the model
    what to conclude from them costs a correct answer - it pushed an analysis
    task onto `create_spreadsheet`. The note states the fact and stops.
    """
    fits = fitting_tools(task, registry)
    if not fits:
        return ""
    return f"\n\nClaw already has these tools for this: {', '.join(fits[:4])}."
