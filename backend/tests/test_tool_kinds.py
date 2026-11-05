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


def test_a_tool_that_saves_a_file_is_listed_as_one():
    """The direction the test above never checked, and the drift it let through.

    MAKES_FILES is what the "do not create new files" limit and the
    invented-file guard consult. The old test asserted MAKES_FILES <= names:
    everything listed must exist. It never asserted the converse, so eleven
    tools added after the list - the six design tools, the four analysis tools
    and collect_documents, which downloads up to twenty-five documents into a
    folder - wrote files while the limit believed they could not.

    A handler that records its output in ctx.memory.outputs is, by definition,
    a tool that produced a file. That is the signal checked here. The reverse
    is not required: several listed tools delegate the saving to a helper, and
    being on the list is the safe side of the error.
    """
    import inspect

    saves = set()
    for spec in build_registry().all():
        try:
            source = inspect.getsource(spec.handler)
        except (OSError, TypeError):      # a C-level or dynamically built handler
            continue
        if "outputs.append" in source:
            saves.add(spec.name)

    assert saves, "nothing was detected as saving a file; this check has stopped working"
    unlisted = sorted(saves - MAKES_FILES)
    assert not unlisted, (
        "these tools save a file but are not in MAKES_FILES, so the 'no new files' "
        f"limit does not cover them: {unlisted}"
    )
