"""A tool refuses a brain for being wrong, not for how it typed the argument.

The Light brain was reported as "not intelligent". Part of that turned out to
be tools, not the brain: a 2B writes `to: "a@b.com, c@d.com"` or
`keys: "ctrl+s"` where a list was asked for, and pydantic refused the whole
call. Nothing about those requests is unclear.

motion_tools had tolerated exactly this for its own points field since the
first benchmark - added where someone watched it fail, rather than everywhere
it could. This audits the rest: every tool argument that is a plain list of
strings or numbers, where a string has one obvious reading.

Deliberately NOT coerced, and asserted below so nobody adds it later: the
arguments whose elements are structured - a slide, a link, a report section.
Turning "a, b" into a list of those means inventing fields, and a tool that
guesses at structure is worse than one that asks.
"""

from __future__ import annotations

import pytest

from claw.tools.base import as_int_list, as_str_list


# ---------- the helpers ----------

@pytest.mark.parametrize(("given", "expected"), [
    ("a@b.com, c@d.com", ["a@b.com", "c@d.com"]),
    ("a@b.com; c@d.com", ["a@b.com", "c@d.com"]),
    ("one\ntwo", ["one", "two"]),
    ("single", ["single"]),
    ("a,, ,b", ["a", "b"]),
])
def test_a_string_becomes_the_list_it_obviously_means(given, expected):
    assert as_str_list(given) == expected


def test_a_correct_call_is_untouched():
    assert as_str_list(["a", "b"]) == ["a", "b"]


def test_something_it_cannot_read_is_passed_on_for_pydantic_to_explain():
    """Better pydantic's own message than a guess of ours."""
    assert as_str_list(None) is None
    assert as_str_list(42) == 42
    assert as_int_list("not numbers") == "not numbers"


def test_limits_are_still_enforced():
    assert len(as_str_list(",".join(str(i) for i in range(50)), 4)) == 4


# ---------- the tools, as a brain would call them ----------

def test_press_keys_takes_a_chord_written_as_one_string():
    from claw.tools.desktop_tools import KeysArgs
    assert KeysArgs(keys="ctrl+s").keys == ["ctrl", "s"]
    assert KeysArgs(keys="enter").keys == ["enter"]
    assert KeysArgs(keys=["ctrl", "s"]).keys == ["ctrl", "s"]


def test_a_menu_path_takes_the_arrow_people_write():
    from claw.tools.desktop_tools import MenuArgs
    assert MenuArgs(path="File > Save As").path == ["File", "Save As"]


def test_e_mail_recipients_take_commas_and_semicolons():
    from claw.tools.mail_tools import MailArgs
    assert MailArgs(to="a@b.com; c@d.com", subject="s", body="b").to == ["a@b.com", "c@d.com"]


def test_columns_and_paths_take_a_plain_string():
    from claw.tools.document_tools import SheetArgs
    from claw.tools.text_tools import CombineArgs, TableArgs
    assert CombineArgs(paths="a.txt, b.txt", file_name="out").paths == ["a.txt", "b.txt"]
    assert TableArgs(text="x", columns="Name, Price", file_name="t").columns == ["Name", "Price"]
    assert SheetArgs(file_name="s", columns="Name, Price", rows=[["a", 1]]).columns == ["Name", "Price"]


def test_a_crop_box_takes_four_numbers_in_a_string():
    from claw.tools.image_tools import EditArgs
    assert EditArgs(path="a.png", crop="0,0,100,100").crop == [0, 0, 100, 100]
    assert EditArgs(path="a.png", crop=[0, 0, 100, 100]).crop == [0, 0, 100, 100]


def test_a_nonsense_crop_is_still_refused():
    """Tolerance is not the same as accepting anything."""
    from pydantic import ValidationError

    from claw.tools.image_tools import EditArgs
    with pytest.raises(ValidationError):
        EditArgs(path="a.png", crop="left to right")


# ---------- what must stay strict ----------

def test_structured_arguments_are_not_guessed_at():
    """A slide, a link and a report section have fields. "a, b" does not say
    what goes in them, and a tool that invents them is worse than one that
    refuses."""
    from pydantic import ValidationError

    from claw.tools.document_tools import ReportArgs
    from claw.tools.file_tools import SaveLinksArgs
    from claw.tools.office_tools import DeckArgs

    with pytest.raises(ValidationError):
        SaveLinksArgs(links="http://a.com, http://b.com", file_name="l")
    with pytest.raises(ValidationError):
        ReportArgs(title="t", sections="one, two", file_name="r")
    with pytest.raises(ValidationError):
        DeckArgs(title="t", slides="one, two", file_name="d")
