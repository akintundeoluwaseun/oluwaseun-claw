"""The tool catalogue's budget comes from the window the server really serves.

CATALOGUE_BUDGET and FULL_CATALOGUE_BUDGET were set against
DEFAULT_CONTEXT_TOKENS. llama.cpp clamps -c DOWN to the model's trained
context, so the window in force can be smaller than the one the engine asked
for - and fit_context keeps the system message whatever the budget, so a flat
catalogue budget out of a smaller window makes every run `forced`.

The first test is the important one: at DEFAULT_CONTEXT_TOKENS nothing may
change, so this is a no-op for anyone whose brain serves the window it was
asked for.
"""

import pytest

from claw.agent import executor as ex
from claw.agent.executor import (
    CATALOGUE_BUDGET,
    DEFAULT_CONTEXT_TOKENS,
    FULL_CATALOGUE_BUDGET,
    MIN_DETAILED,
    MIN_NAMED,
    catalogue_budget,
    estimate_tokens,
    tool_catalogue,
)
from claw.tools.registry import build_registry

A_REAL_REQUEST = "tidy up the downloads folder"


@pytest.fixture(scope="module")
def registry():
    return build_registry()


def _detailed(text: str) -> list[str]:
    return [line.split("(", 1)[0][2:] for line in text.splitlines() if line.startswith("- ")]


def _named(text: str) -> list[str]:
    for line in text.splitlines():
        if line.startswith("Also available"):
            rest = line.split(": ", 1)[1]
            return [n.strip() for n in rest.split(",") if "more (ask for any tool" not in n]
    return []


def test_budget_is_unchanged_at_the_default_window():
    assert catalogue_budget(DEFAULT_CONTEXT_TOKENS, True) == CATALOGUE_BUDGET
    assert catalogue_budget(DEFAULT_CONTEXT_TOKENS, False) == FULL_CATALOGUE_BUDGET


@pytest.mark.parametrize("capabilities", [{"files"}, None])
def test_catalogue_byte_identical_at_the_default_window(registry, capabilities):
    """The whole point of expressing the budget as a share: at 8192, no change."""
    before = tool_catalogue(registry, capabilities, [], task=A_REAL_REQUEST)
    after = tool_catalogue(registry, capabilities, [], task=A_REAL_REQUEST,
                           window_tokens=DEFAULT_CONTEXT_TOKENS)
    assert before == after


def test_default_argument_is_the_default_window():
    """Callers that do not know the window keep the behaviour they had."""
    import inspect
    sig = inspect.signature(tool_catalogue)
    assert sig.parameters["window_tokens"].default == DEFAULT_CONTEXT_TOKENS


@pytest.mark.parametrize("window", [2048, 4096])
def test_smaller_window_shrinks_the_catalogue(registry, window):
    small = tool_catalogue(registry, {"files"}, [], task=A_REAL_REQUEST, window_tokens=window)
    full = tool_catalogue(registry, {"files"}, [], task=A_REAL_REQUEST,
                          window_tokens=DEFAULT_CONTEXT_TOKENS)
    assert estimate_tokens(small) <= estimate_tokens(full)


def test_smaller_window_still_leaves_room_for_the_task(registry):
    """A 2048-token brain: the catalogue must not eat the window on its own.

    1800 of 2048 was the defect. A share of the real window is ~450, and even
    when the floors hold the line above that, it must not be most of 2048.
    """
    window = 2048
    cat = tool_catalogue(registry, {"files"}, [], task=A_REAL_REQUEST, window_tokens=window)
    assert estimate_tokens(cat) < window // 2, estimate_tokens(cat)


@pytest.mark.parametrize("window", [512, 1024, 2048, 4096, 8192, 16384])
def test_floors_hold_at_every_window(registry, window):
    """However tight the budget, the catalogue stays a catalogue."""
    cat = tool_catalogue(registry, {"files"}, [], task=A_REAL_REQUEST, window_tokens=window)
    assert len(_detailed(cat)) >= MIN_DETAILED, (window, len(_detailed(cat)))
    names = _named(cat)
    if names:
        assert len(names) >= MIN_NAMED, (window, len(names))


def test_fitting_tools_survive_a_tiny_window(registry):
    """A tool the request plainly needs is never demoted to a name."""
    task = "tidy up the downloads folder"
    fitting = ex.fitting_tools(task, registry)
    cat = tool_catalogue(registry, {"files"}, [], task=task, window_tokens=1024)
    detailed = _detailed(cat)
    for name in fitting:
        assert name in detailed, name


def test_a_bigger_window_is_allowed_more(registry):
    assert catalogue_budget(16384, True) > CATALOGUE_BUDGET
    assert catalogue_budget(16384, False) > FULL_CATALOGUE_BUDGET
