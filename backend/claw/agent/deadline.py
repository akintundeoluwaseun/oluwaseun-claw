"""One clock for a whole task.

Every individual limit in Claw is sensible on its own: a model call is cut off
at 120 seconds, a tool at 60, a run at 20 steps, three failures in a row stop
it. Their PRODUCT is not sensible. Twenty steps of (120 s thinking + 60 s
doing) is an hour, with every one of those limits respected and nothing
reporting a problem. The person sees a spinner.

So one clock covers the task: planning, every model call, every tool, every
retry, and every replan. It starts once and it is never reset - a new step or
a new attempt does not buy more time, because the whole point is to bound what
the person is waiting for, not what any one operation takes.

What it does NOT do is kill work in flight. A model call is an HTTP request
and can be cut off safely, so the remaining time is handed to it as its
timeout. A tool may be halfway through writing a file, so a running tool is
left to finish or to hit its own `step_timeout_s`; the deadline stops the NEXT
one from starting. "Stop launching new operations" is a promise that can be
kept without risking a half-written file; "cancel everything now" is not.

When it expires the run ends as `incomplete` - the status Claw already uses
for a run that stopped with work left - carrying the steps that finished, the
step it was on, and the reason. Work that completed stays completed and is
reported as such. Nothing is rolled back and nothing pretends it was.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Deadline:
    """A budget for one task, measured from when the task started.

    `budget_s` is how long the whole task may take. `started` is a monotonic
    reading, so the clock is unaffected by the system clock changing under it.
    """

    budget_s: float
    started: float = field(default_factory=time.monotonic)
    #: What the budget was called when it was chosen, for the message a person
    #: reads: "conversation", "simple", "moderate", "complex", "extended".
    band: str = "complex"

    @property
    def elapsed_s(self) -> float:
        return time.monotonic() - self.started

    @property
    def remaining_s(self) -> float:
        """Seconds left, never negative."""
        return max(0.0, self.budget_s - self.elapsed_s)

    @property
    def expired(self) -> bool:
        return self.remaining_s <= 0

    def tighten_to(self, budget_s: float, band: str) -> None:
        """Lower the budget once the task's size is known.

        Only ever lowers. A plan that turns out to be one step should not get
        the ten minutes a complex task gets, but nothing may hand a task MORE
        time than it started with - that would be the reset this class exists
        to prevent. Called after planning, when the step count is known; the
        start time is untouched, so the time planning took still counts.
        """
        if budget_s < self.budget_s:
            self.budget_s = budget_s
            self.band = band

    def timeout_for(self, wanted_s: float) -> float:
        """How long a single operation may take, given what is left.

        Never more than the operation's own limit and never more than the time
        left in the task. Floored just above zero: handing 0 to an HTTP client
        means "no timeout" in some of them, which is the opposite of what is
        being asked for here.
        """
        return max(0.01, min(wanted_s, self.remaining_s))

    def why_stopped(self) -> str:
        """What the person is told. Plain, and it does not blame them."""
        return (f"The task reached its time limit of {int(self.budget_s)} seconds "
                f"and stopped before it finished. What had already been done is kept.")


def band_for(step_count: int, limits) -> tuple[float, str]:
    """The budget a plan of this size gets.

    Separate budgets, because the shapes are genuinely different: answering a
    question is one model call, opening an app is one call and one action, and
    researching five companies is neither. A single number would be far too
    short for the last or absurd for the first.
    """
    if step_count <= 1:
        return limits.simple_deadline_s, "simple"
    if step_count <= 4:
        return limits.moderate_deadline_s, "moderate"
    return limits.complex_deadline_s, "complex"
