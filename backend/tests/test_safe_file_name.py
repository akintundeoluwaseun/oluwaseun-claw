"""A name keeps its meaning and gains the right extension - once.

From a real run: the flyer was saved as "flyer.docx.png". The brain had asked
for "flyer.docx" and the image tool was writing a PNG. The old rule dropped an
existing suffix only when it already matched the extension being applied, so a
wrong one survived as part of the name and the right one was added after it.

The fix cannot be "always drop whatever follows the last dot", because plenty
of real names have one: v1.2, report.2026, a folder named after a domain. So a
suffix is replaced only when it is recognisably a file extension.
"""

from __future__ import annotations

import pytest

from claw.tools.file_tools import safe_file_name


@pytest.mark.parametrize(("name", "ext", "expected"), [
    ("flyer.docx", ".png", "flyer.png"),        # the reported bug
    ("flyer.png", ".png", "flyer.png"),         # already right: not doubled
    ("flyer", ".png", "flyer.png"),             # no extension at all
    ("My Flyer.DOCX", ".png", "My Flyer.png"),  # case does not matter
    ("notes.txt", ".docx", "notes.docx"),
    ("slides.pptx", ".pdf", "slides.pdf"),
    ("clip.mov", ".mp4", "clip.mp4"),
])
def test_a_wrong_extension_is_replaced_not_stacked(name, ext, expected):
    assert safe_file_name(name, ext) == expected


@pytest.mark.parametrize(("name", "ext", "expected"), [
    ("v1.2", ".png", "v1.2.png"),
    ("report.2026", ".pdf", "report.2026.pdf"),
    ("budget.final", ".xlsx", "budget.final.xlsx"),
    ("a.b.c", ".png", "a.b.c.png"),
])
def test_a_dot_that_is_not_an_extension_is_left_alone(name, ext, expected):
    """Renaming someone's file because it contains a full stop is worse than the bug."""
    assert safe_file_name(name, ext) == expected


def test_no_output_ever_carries_two_extensions():
    """The shape of the bug, stated directly."""
    for name in ["flyer.docx", "flyer.png", "report.pdf", "sheet.xlsx", "clip.mov"]:
        for ext in [".png", ".pdf", ".docx", ".mp4"]:
            out = safe_file_name(name, ext)
            assert out.count(".") == 1, f"{name!r} + {ext} gave {out!r}"
            assert out.endswith(ext)


def test_the_awkward_names_still_behave():
    assert safe_file_name("", ".png") == "links.png"          # falls back rather than ""
    assert safe_file_name("con", ".txt") == "con-file.txt"    # reserved on Windows
    assert safe_file_name("../../etc/passwd", ".txt") == "passwd.txt"
    assert safe_file_name("a" * 200, ".png").endswith(".png")
