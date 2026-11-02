"""Every tool is classified once (reuse audit §2.2): looking comes from its risk, making from one list."""

from claw.tools.kinds import CHANGES_FILES, MAKES_FILES, UI_ACTIONS, is_looking, looking_tools
from claw.tools.registry import build_registry


def test_every_listed_tool_exists_and_none_is_both():
    names = set(build_registry().names())
    assert MAKES_FILES <= names and CHANGES_FILES <= MAKES_FILES and UI_ACTIONS <= names
    assert not (looking_tools() & MAKES_FILES)


def test_the_drift_that_was_found_is_gone():
    for t in ("compare_folders", "table_totals", "find_duplicate_files", "check_file", "recall", "look_at_page"):
        assert is_looking(t), t
    for t in ("click", "focus_window", "write_text_file", "combine_tables"):
        assert not is_looking(t), t
