"""Where a task's time went, phase by phase.

A task that finishes inside its deadline has proved nothing about whether it
was efficient: ten minutes of budget hides a great deal. The only way to know
whether the cost was thinking, doing, or trying again is to measure each
separately - and to keep reporting the cheap ones, because a number that only
appears when it is bad cannot be used to show anything is good.
"""

import time

import pytest

from claw.agent.timings import PHASES, Timings


def test_every_phase_the_brief_asked_for_is_recorded():
    for wanted in ("router", "selection", "planning", "generation", "tools", "retry"):
        assert wanted in PHASES
    assert "total_s" in Timings().as_dict()


def test_a_phase_that_cost_nothing_is_still_reported():
    """Otherwise a missing number and a zero look the same."""
    d = Timings().as_dict()
    assert set(d["phases"]) == set(PHASES)
    assert all(v == 0 for v in d["phases"].values())


def test_time_and_count_are_both_kept():
    """40 seconds of generation is one slow call or eight quick ones, and
    those want different fixes."""
    t = Timings()
    t.add("generation", 1.0)
    t.add("generation", 3.0)
    d = t.as_dict()
    assert d["phases"]["generation"] == 4.0
    assert d["counts"]["generation"] == 2


def test_measure_times_a_block_that_raises():
    """A call that failed still spent the time."""
    t = Timings()
    with pytest.raises(ValueError):
        with t.measure("tools"):
            time.sleep(0.05)
            raise ValueError("boom")
    assert t.seconds["tools"] >= 0.04
    assert t.counts["tools"] == 1


def test_the_unexplained_remainder_is_named():
    """An unaccounted gap is where the next slow thing hides, so it is a
    number rather than silence."""
    t = Timings()
    t.started -= 10
    t.add("generation", 2.0)
    d = t.as_dict()
    assert d["unmeasured_s"] >= 7.5


def test_the_remainder_never_goes_negative():
    t = Timings()
    t.add("generation", 100.0)
    assert t.as_dict()["unmeasured_s"] == 0


def test_the_summary_line_names_what_cost_something():
    t = Timings()
    t.add("planning", 12.0)
    t.add("tools", 0.0)
    line = t.summary_line()
    assert "planning 12.0s" in line
    assert "tools" not in line, "a phase that cost nothing does not clutter a log line"
    assert "total" in line
