"""The clipboard.

Claw could press Ctrl+C and had no idea what landed. That is a hole, not a
convenience: the clipboard is the way out of every app with no
accessibility tree - a PDF viewer, a Java program, anything drawn rather
than built from controls. Select, copy, read works everywhere.

Honest note on coverage. The real backends are win32clipboard on Windows
and xclip/xsel/wl-copy on Linux. This container has neither a clipboard
program nor a display, so the end-to-end tests here are skipped and the
Windows ones run on the build runner, which executes this suite on a real
Windows machine. What IS tested everywhere is the part that decides what to
say about what it found, which is where the misleading answers would come
from.
"""

from __future__ import annotations

import shutil
import sys

import pytest

from claw.agent.schemas import Capability
from claw.permissions.policy import RiskLevel
from claw.tools.base import ToolError
from claw.tools.clipboard_tools import (
    ClipboardUnavailable, describe, read_text, unavailable_message, write_text,
)
from claw.tools.registry import build_registry
from tests.test_phase_a import call


def has_clipboard() -> bool:
    if sys.platform == "win32":
        return True
    return any(shutil.which(p) for p in ("xclip", "xsel", "wl-copy"))


# ---------- what it says about what it found ----------
def test_a_picture_on_the_clipboard_is_not_an_empty_clipboard():
    """The distinction that matters.

    Saying "nothing was copied" when a screenshot is sitting there sends the
    brain down a completely wrong path - it will copy again, and again.
    """
    summary, data = describe(None)
    assert "no text on the clipboard" in summary
    assert "not text" in summary or data["kind"] == "not text"
    assert data["kind"] == "not text"

    summary, data = describe("")
    assert data["kind"] == "empty" and "empty" in summary


def test_text_is_reported_with_its_size():
    summary, data = describe("INV-2201")
    assert data["kind"] == "text" and data["text"] == "INV-2201"
    assert data["characters"] == 8 and data["lines"] == 1

    summary, data = describe("one\ntwo\nthree")
    assert data["lines"] == 3


def test_a_whole_document_is_cut_down_but_counted_honestly():
    big = "x" * 10_000
    summary, data = describe(big)
    assert len(data["text"]) == 4000, "the brain was handed the whole document"
    assert data["characters"] == 10_000, "the real size was not reported"
    assert "first 4,000 characters of 10,000" in summary


def test_whitespace_only_counts_as_empty():
    _, data = describe("   \n\t  ")
    assert data["kind"] == "empty"


# ---------- shape ----------
def test_reading_is_read_only_and_writing_is_not():
    reg = build_registry()
    assert reg.get("read_clipboard").risk is RiskLevel.READ_ONLY
    assert reg.get("put_on_clipboard").risk is RiskLevel.LOCAL_WRITE
    assert reg.get("read_clipboard").capability is Capability.DESKTOP


def test_a_machine_with_no_clipboard_says_so_clearly():
    """Not an empty string, which reads like an empty clipboard."""
    said = unavailable_message()
    assert said
    if sys.platform != "win32":
        assert "xclip" in said and "installed" in said


@pytest.mark.skipif(has_clipboard(), reason="this machine has a clipboard")
def test_without_a_clipboard_program_it_raises_rather_than_lying():
    with pytest.raises(ClipboardUnavailable):
        read_text()
    with pytest.raises(ClipboardUnavailable):
        write_text("anything")


# ---------- the real thing, where there is one ----------
@pytest.mark.skipif(not has_clipboard(), reason="no clipboard on this machine")
async def test_text_goes_on_and_comes_back(tool_ctx):
    r = await call(tool_ctx, "put_on_clipboard", text="INV-2201 total N9,997.50")
    assert r.ok and r.verified, r.summary

    back = await call(tool_ctx, "read_clipboard")
    assert back.ok
    assert back.data["text"] == "INV-2201 total N9,997.50"
    # It is text from another program, so it is handed over as untrusted
    # content rather than folded into Claw's own words.
    assert back.untrusted_text == "INV-2201 total N9,997.50"


@pytest.mark.skipif(not has_clipboard(), reason="no clipboard on this machine")
async def test_several_lines_survive_the_round_trip(tool_ctx):
    body = "Ade Stores\tN15,000\nBola Ventures\tN7,500\n"
    await call(tool_ctx, "put_on_clipboard", text=body)
    back = await call(tool_ctx, "read_clipboard")
    assert "Bola Ventures" in back.data["text"]
    assert back.data["lines"] >= 2
