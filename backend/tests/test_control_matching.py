"""Finding a control by name instead of by position.

Before this, a control could only be named by its number from the last
look_at_window, which is brittle: the numbers move whenever the window does.

The matching approach — difflib's ratio against each candidate name, with a
floor below which nothing matches — is the one pywinauto uses in
`pywinauto/findbestmatch.py` (BSD-3-Clause). It is adapted rather than
imported, because that module is Windows-only in practice and this has to
behave identically on the Linux test desktop.

The interesting cases are the refusals.
"""

import pytest

from claw.computer.driver import ControlInfo
from claw.tools.base import ToolError
from claw.tools.desktop_tools import match_control

def c(i, name, role="Button"):
    return ControlInfo(index=i, role=role, name=name)


SCREEN = [c(0, "Message"), c(1, "Send"), c(2, "Attach file"), c(3, "Search or start new chat")]


def test_an_exact_name_wins():
    assert match_control("Send", SCREEN).index == 1


def test_case_and_surrounding_space_do_not_matter():
    assert match_control("  send  ", SCREEN).index == 1


def test_a_close_name_is_accepted():
    assert match_control("Attach", SCREEN).index == 2


def test_a_name_that_matches_nothing_is_refused_with_the_near_misses():
    with pytest.raises(ToolError) as caught:
        match_control("Print invoice", SCREEN)
    assert "No control here is called" in caught.value.message
    assert '"' in caught.value.message, "the message should show what is actually there"


def test_two_similar_names_are_a_question_not_a_guess():
    """'Send' and 'Send later' is exactly how an agent clicks the wrong thing."""
    screen = [c(0, "Send later"), c(1, "Send now")]
    with pytest.raises(ToolError, match="could mean"):
        match_control("Send", screen)


def test_an_exact_match_still_wins_against_a_similar_neighbour():
    screen = [c(0, "Send"), c(1, "Send later")]
    assert match_control("Send", screen).index == 0


def test_duplicate_names_ask_for_a_number():
    screen = [c(0, "Open"), c(1, "Open")]
    with pytest.raises(ToolError, match="Several controls are called"):
        match_control("Open", screen)


def test_only_the_first_line_of_a_long_label_is_compared():
    screen = [c(0, "Send\tCtrl+Enter"), c(1, "Cancel")]
    assert match_control("Send", screen).index == 0


def test_unnamed_controls_are_not_candidates():
    screen = [c(0, ""), c(1, "Send")]
    assert match_control("Send", screen).index == 1
