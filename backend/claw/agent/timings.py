"""Where a task's time actually went.

A task that finishes inside its deadline has proved nothing about whether it
was efficient. Ten minutes of budget hides a great deal, and the only way to
know whether the cost was thinking, doing, or waiting to try again is to
measure each separately and report all of them.

So every phase is timed under its own name and the totals are attached to the
task, next to its steps. The phases are deliberately not nested: a reader can
add them up and compare the sum with the wall clock, and the difference IS the
answer to "where did the rest go?". A phase that is cheap stays in the report
showing that it is cheap, because a number that only appears when it is bad
cannot be used to prove anything is good.

Phases:

    router      deciding which lane a message takes, before any model is woken
    selection   choosing and starting a model, including a cold load
    planning    make_plan, including its retry
    generation  every model call made while executing, added up
    tools       every tool run, added up
    retry       time spent on attempts that were thrown away
    total       the task from arrival to answer
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field

#: The phases, in the order a reader wants them.
PHASES = ("router", "selection", "planning", "generation", "tools", "retry")


@dataclass
class Timings:
    """Seconds per phase for one task, plus how many times each happened.

    Counts matter as much as totals: 40 seconds of generation is one slow call
    or eight quick ones, and those want different fixes.
    """

    seconds: dict[str, float] = field(default_factory=lambda: dict.fromkeys(PHASES, 0.0))
    counts: dict[str, int] = field(default_factory=lambda: dict.fromkeys(PHASES, 0))
    started: float = field(default_factory=time.monotonic)

    def add(self, phase: str, seconds: float) -> None:
        self.seconds[phase] = self.seconds.get(phase, 0.0) + max(0.0, seconds)
        self.counts[phase] = self.counts.get(phase, 0) + 1

    @contextmanager
    def measure(self, phase: str):
        """Time a block, whether it succeeds or raises.

        A call that failed still spent the time, and a report that only counts
        successes would make a task look cheaper the more often it went wrong.
        """
        began = time.monotonic()
        try:
            yield
        finally:
            self.add(phase, time.monotonic() - began)

    @property
    def total_s(self) -> float:
        return time.monotonic() - self.started

    def as_dict(self) -> dict[str, object]:
        """What the task carries, for a person or a benchmark to read."""
        measured = sum(self.seconds.values())
        total = self.total_s
        return {
            "total_s": round(total, 2),
            "phases": {p: round(self.seconds.get(p, 0.0), 2) for p in PHASES},
            "counts": {p: self.counts.get(p, 0) for p in PHASES},
            # Everything the phases did not account for: queueing, the
            # database, waiting for a person to approve something. Named
            # rather than left as a gap, because an unexplained remainder is
            # where the next slow thing hides.
            "unmeasured_s": round(max(0.0, total - measured), 2),
        }

    def summary_line(self) -> str:
        """One line for a log: the phases that actually cost something."""
        parts = [f"{p} {self.seconds[p]:.1f}s" for p in PHASES if self.seconds.get(p, 0) >= 0.05]
        return f"total {self.total_s:.1f}s" + (" | " + ", ".join(parts) if parts else "")
