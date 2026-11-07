"""The clipboard: reading what was copied, and putting something there.

Claw could press Ctrl+C and had no idea what landed on the clipboard. That
is a real hole, not a convenience. The clipboard is the way out of every app
that has no accessibility tree - a PDF viewer, a game launcher, a Java
program, anything drawn rather than built from controls. Select, copy, read:
that works everywhere, and without it those apps are only lookable-at.

It also closes a verification gap. "I copied the invoice number" was a claim
with nothing behind it; now the thing that was copied can be read back and
quoted.

Putting text on the clipboard is the other half: the person pastes it
themselves, wherever they want it, which is often safer and always faster
than Claw typing two hundred characters into a field it had to find first.

Platform honesty: on Windows this is pywin32, which S-CLAW already ships.
On Linux it needs xclip, xsel or wl-copy, and when none is installed the
tool says exactly that rather than returning an empty string that reads
like an empty clipboard.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys

from pydantic import Field

from claw.agent.schemas import Capability
from claw.permissions.policy import RiskLevel
from claw.tools.base import ToolArgs, ToolContext, ToolError, ToolRegistry, ToolResult, ToolSpec

#: Past this the clipboard is holding a document, not a snippet, and the
#: brain does not need all of it to work with it.
MAX_SHOWN = 4000
MAX_SET = 100_000


class ClipboardUnavailable(ToolError):
    """No way to reach the clipboard on this machine."""


def _linux_reader() -> list[str] | None:
    if shutil.which("wl-paste"):
        return ["wl-paste", "--no-newline"]
    if shutil.which("xclip"):
        return ["xclip", "-selection", "clipboard", "-o"]
    if shutil.which("xsel"):
        return ["xsel", "--clipboard", "--output"]
    return None


def _linux_writer() -> list[str] | None:
    if shutil.which("wl-copy"):
        return ["wl-copy"]
    if shutil.which("xclip"):
        return ["xclip", "-selection", "clipboard"]
    if shutil.which("xsel"):
        return ["xsel", "--clipboard", "--input"]
    return None


def unavailable_message() -> str:
    if sys.platform == "win32":
        return ("Claw could not reach the Windows clipboard. This normally means the app is "
                "running without the Windows support files; reinstalling S-CLAW fixes it.")
    return ("This computer has no clipboard program Claw can use. On Linux it needs xclip, "
            "xsel or wl-clipboard installed.")


def read_text() -> str | None:
    """What is on the clipboard as text, or None when it holds no text.

    None and "" are different answers and are kept apart: a picture on the
    clipboard is not an empty clipboard, and saying "nothing was copied"
    when a screenshot is sitting there would send the brain down the wrong
    path entirely.
    """
    if sys.platform == "win32":
        try:
            import win32clipboard  # noqa: PLC0415
            import win32con  # noqa: PLC0415
        except ImportError as exc:                      # pragma: no cover - Windows only
            raise ClipboardUnavailable(unavailable_message()) from exc
        win32clipboard.OpenClipboard()
        try:
            if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                return win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
            return None
        finally:
            win32clipboard.CloseClipboard()

    command = _linux_reader()
    if command is None:
        raise ClipboardUnavailable(unavailable_message())
    done = subprocess.run(command, capture_output=True, timeout=15, check=False)
    if done.returncode != 0:
        return None
    return done.stdout.decode("utf-8", "replace")


def write_text(text: str) -> None:
    if sys.platform == "win32":
        try:
            import win32clipboard  # noqa: PLC0415
            import win32con  # noqa: PLC0415
        except ImportError as exc:                      # pragma: no cover - Windows only
            raise ClipboardUnavailable(unavailable_message()) from exc
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
        finally:
            win32clipboard.CloseClipboard()
        return

    command = _linux_writer()
    if command is None:
        raise ClipboardUnavailable(unavailable_message())
    done = subprocess.run(command, input=text.encode("utf-8"), capture_output=True,
                          timeout=15, check=False)
    if done.returncode != 0:
        raise ClipboardUnavailable(
            f"The clipboard program failed: {done.stderr.decode('utf-8', 'replace')[:160]}")


def describe(text: str | None) -> tuple[str, dict]:
    """The summary and data for whatever was found. Pure, so it is testable."""
    if text is None:
        return ("There is no text on the clipboard. Something may have been copied that is not "
                "text, such as a picture or a file.", {"text": "", "kind": "not text"})
    if not text.strip():
        return ("The clipboard is empty.", {"text": "", "kind": "empty"})
    shown = text[:MAX_SHOWN]
    lines = text.count("\n") + 1
    more = "" if len(text) <= MAX_SHOWN else f" (the first {MAX_SHOWN:,} characters of {len(text):,})"
    return (f"The clipboard holds {len(text):,} character(s) over {lines} line(s){more}.",
            {"text": shown, "kind": "text", "characters": len(text), "lines": lines})


class NoArgs(ToolArgs):
    pass


async def read_clipboard(args: NoArgs, ctx: ToolContext) -> ToolResult:
    text = await asyncio.to_thread(read_text)
    summary, data = describe(text)
    # The clipboard came from somewhere else - another app, a web page, an
    # e-mail - so it is untrusted text, handed over as content rather than
    # folded into Claw's own words.
    return ToolResult(True, summary, data, verified=True,
                      untrusted_text=data["text"])


class PutArgs(ToolArgs):
    text: str = Field(min_length=1, max_length=MAX_SET,
                      description="What to put on the clipboard, ready to paste")


async def put_on_clipboard(args: PutArgs, ctx: ToolContext) -> ToolResult:
    await asyncio.to_thread(write_text, args.text)
    # Read it back: setting the clipboard can fail silently when another
    # program is holding it open, which on Windows is common enough to be
    # worth the extra call.
    back = await asyncio.to_thread(read_text)
    ok = (back or "") == args.text
    shown = args.text if len(args.text) <= 60 else args.text[:57] + "..."
    return ToolResult(
        ok,
        f"Put {len(args.text):,} character(s) on the clipboard, ready to paste: {shown!r}."
        + (" Read it back to check." if ok else
           " WARNING: reading it back gave something else, so another program may have taken it."),
        {"characters": len(args.text), "checked": ok}, verified=ok)


def register_clipboard_tools(reg: ToolRegistry) -> None:
    reg.register(ToolSpec(
        "read_clipboard", "Read what is on the clipboard - the way to get text out of an app "
                          "whose window Claw cannot read.",
        Capability.DESKTOP, RiskLevel.READ_ONLY, NoArgs, read_clipboard))
    reg.register(ToolSpec(
        "put_on_clipboard", "Put text on the clipboard so it can be pasted anywhere.",
        Capability.DESKTOP, RiskLevel.LOCAL_WRITE, PutArgs, put_on_clipboard))
