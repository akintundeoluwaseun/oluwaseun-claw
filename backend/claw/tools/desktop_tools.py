"""Desktop tools: windows, controls, typing, keys, screenshots.

Each action takes a before/after snapshot of the screen state where it can, so
results are reported as "checked" only when the change was actually observed.
Accessibility (UI Automation) is used first; clicking at screen coordinates is
a separate, explicitly-approved fallback that requires a screenshot first.
"""

from __future__ import annotations

import asyncio
import re
from difflib import SequenceMatcher
import time
from pathlib import Path

from pydantic import Field, field_validator

from claw.agent.schemas import Capability
from claw.computer.driver import ControlInfo, DesktopUnavailable, Snapshot, WindowInfo
from claw.computer.launcher import choose_app, is_system_tool
from claw.permissions.policy import RiskLevel
from claw.tools.base import ToolArgs, ToolContext, ToolError, ToolRegistry, ToolResult, ToolSpec, escalate_by_label

SETTLE_S = 0.6  # give the app a moment to react before checking

ALLOWED_KEYS = {
    "enter", "tab", "escape", "backspace", "delete", "up", "down", "left", "right", "home", "end",
    "pageup", "pagedown", "space", *(f"f{i}" for i in range(1, 13)),
    *"abcdefghijklmnopqrstuvwxyz0123456789",
}
MODIFIERS = {"ctrl", "alt", "shift"}
# Combinations that could leave Claw's control or change Windows itself.
# How long an app is given to put a window on screen. A named constant so a test can
# shorten it instead of waiting the full fifteen seconds for the failure path.
LAUNCH_TIMEOUT_S = 15.0

BLOCKED_COMBOS = [{"ctrl", "alt", "delete"}, {"alt", "tab"}, {"ctrl", "escape"}, {"ctrl", "shift", "escape"}]


async def _d(ctx: ToolContext, fn_name: str, *args):
    if ctx.desktop is None:
        raise ToolError("Desktop control is not available in this session.")
    ok, reason = await ctx.desktop.call(ctx.desktop.driver.available)
    if not ok:
        raise ToolError(reason)
    try:
        return await ctx.desktop.call(getattr(ctx.desktop.driver, fn_name), *args)
    except DesktopUnavailable as exc:
        raise ToolError(str(exc)) from exc
    except ToolError:
        raise
    except Exception as exc:  # noqa: BLE001 — UI Automation raises many COM errors
        text = str(exc).splitlines()[0][:200] if str(exc) else type(exc).__name__
        if "access is denied" in text.lower() or "elevat" in text.lower():
            raise ToolError("That window belongs to an app running as administrator; Claw can't control it.") from exc
        raise ToolError(f"The desktop action did not work: {text}") from exc


# Titles of dialogs that usually mean something went wrong.
_TROUBLE = re.compile(r"error|warning|problem|not responding|failed|cannot|can't|couldn't|denied|alert|crash|stopped working", re.I)


def _trouble(before: Snapshot, after: Snapshot) -> list[str]:
    """New dialogs whose titles suggest an error: reported, and the step is not counted as checked."""
    return [t for t in sorted(set(after.dialog_titles) - set(before.dialog_titles)) if _TROUBLE.search(t)]


def _changed(before: Snapshot, after: Snapshot) -> list[str]:
    notes = []
    new_dialogs = sorted(set(after.dialog_titles) - set(before.dialog_titles))
    if new_dialogs:
        notes.append("A dialog opened: " + ", ".join(f"'{t}'" for t in new_dialogs[:3]) + " (look at it before going on)")
    new_windows = sorted(set(after.window_titles) - set(before.window_titles))
    gone = sorted(set(before.window_titles) - set(after.window_titles))
    new_windows = [t for t in new_windows if t not in new_dialogs]
    if new_windows:
        notes.append("New window: " + ", ".join(f"'{t}'" for t in new_windows[:3]))
    if gone:
        notes.append("Closed: " + ", ".join(f"'{t}'" for t in gone[:3]))
    if after.active_title != before.active_title:
        notes.append(f"Now active: '{after.active_title}'")
    if not notes and after.control_names != before.control_names:
        notes.append("The window's contents changed")
    return notes


def _match_window(windows: list[WindowInfo], title: str | None) -> WindowInfo:
    if not title:
        active = [w for w in windows if w.active]
        if active:
            return active[0]
        raise ToolError("No window is active. Say which window to use.")
    needle = title.lower()
    exact = [w for w in windows if w.title.lower() == needle]
    hits = exact or [w for w in windows if needle in w.title.lower()]
    if not hits:
        raise ToolError(f"No open window matches '{title}'.")
    if len(hits) > 1 and not exact:
        names = "; ".join(w.title for w in hits[:5])
        raise ToolError(f"Several windows match '{title}': {names}. Use more of the title.")
    return hits[0]


# In these apps, Enter (or a typed new line) sends a message: that always needs the user's OK.
MESSAGING_APPS = {"whatsapp.exe", "whatsapp.root.exe", "telegram.exe", "teams.exe", "ms-teams.exe", "outlook.exe", "olk.exe",
                  "slack.exe", "discord.exe", "signal.exe", "skype.exe", "zoom.exe", "messenger.exe"}

# The same is true inside a browser, and there the program is only ever the browser.
# "Open Instagram in Chrome and message John" would otherwise press Enter under the
# ordinary writing rules, and send on a key press nobody approved.
BROWSERS = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "vivaldi.exe",
            "chromium.exe", "iexplore.exe"}
SENDING_SITES = re.compile(
    r"\b(whatsapp|telegram|instagram|messenger|facebook|discord|slack|teams|signal|"
    r"gmail|inbox|outlook|mail|linkedin|twitter|x\.com|reddit chat|skype|viber|wechat)\b",
    re.I)


def _use(ctx: ToolContext, win: WindowInfo) -> None:
    ctx.desktop.last_window = win.handle
    ctx.desktop.last_process = (win.process or "").lower()
    ctx.desktop.last_title = win.title or ""


def _in_messaging_app(ctx: ToolContext) -> bool:
    """Would Enter send something to another person from where Claw is working?

    A false yes costs one extra approval. A false no sends a message nobody
    approved, so the browser case is decided from the window title, which is
    where the site's name is.
    """
    if ctx is None or ctx.desktop is None:
        return False
    process = ctx.desktop.last_process
    if process in MESSAGING_APPS:
        return True
    if process in BROWSERS:
        return bool(SENDING_SITES.search(ctx.desktop.last_title or ""))
    return False


def _where(ctx: ToolContext) -> str:
    """Who is on the other side, as far as the window title says.

    Titles read "John Doe - Telegram" or "(2) WhatsApp", so the leading part is
    the chat and the rest is the app. It is a guess from a title, so the wording
    stays a guess: the person approving can see the screen, Claw cannot.
    """
    title = (ctx.desktop.last_title or "").strip()
    if not title:
        return "the window Claw is working in"
    head = re.split(r"\s+[-\u2013\u2014|]\s+", title)[0].strip()
    head = re.sub(r"^\(\d+\)\s*", "", head)      # "(2) John Doe" - the unread count
    return f"'{head or title}'"


def sending_context(args, ctx: ToolContext) -> str:
    """The sentence shown on the approval card for a key press that sends.

    'press_keys: ["enter"]' is true and useless. What the person needs to know
    before they allow it is who receives the message and what it says - neither
    of which is in the arguments.
    """
    if not _in_messaging_app(ctx):
        return ""
    # When the tool carries the text itself, that text is what gets sent. Only a
    # bare key press has to fall back to what was typed in an earlier step - and
    # reading last_typed for type_text would quote the *previous* message, because
    # the handler that records it has not run yet when this card is shown.
    typed = getattr(args, "text", None) or ctx.desktop.last_typed or ""
    quoted = " ".join(typed.split())
    if len(quoted) > 240:
        quoted = quoted[:240] + "..."
    where = _where(ctx)
    app = ctx.desktop.last_process or "that app"
    lead = f"This sends the message to {where} in {app}."
    return f"{lead} The message reads: \u201c{quoted}\u201d" if quoted else \
        f"{lead} Claw did not type the message itself, so check on screen what is in the box."


def keys_risk(args, ctx: ToolContext) -> RiskLevel:
    return RiskLevel.DESTRUCTIVE if "enter" in args.keys and _in_messaging_app(ctx) else RiskLevel.LOCAL_WRITE


def typing_risk(args, ctx: ToolContext) -> RiskLevel:
    return RiskLevel.DESTRUCTIVE if ("\n" in args.text or "\r" in args.text) and _in_messaging_app(ctx) else RiskLevel.LOCAL_WRITE


#: How close a name has to be before it counts as the control the model meant.
#: The approach — difflib's ratio against each candidate, with a floor — is the
#: one pywinauto uses in `pywinauto/findbestmatch.py` (BSD-3-Clause,
#: github.com/pywinauto/pywinauto). It is adapted rather than imported: that
#: module is Windows-only in practice, while this logic has to run on the build
#: machine's test desktop too, and the behaviour must not differ between them.
MATCH_FLOOR = 0.5
#: Two candidates this close together is not a choice Claw should make silently.
#: Measured on a real-looking chat window: a genuine match beats its nearest
#: rival by 0.55-0.74, while "Send" against "Send now" and "Send later" differ
#: by 0.10 — near-identical labels with different consequences, which is exactly
#: the case worth stopping for.
MATCH_MARGIN = 0.15


def _clean(text: str) -> str:
    """Compare what a person would read: first line, before any tab."""
    return text.split("\t")[0].split("\n")[0].strip().lower()


def match_control(name: str, controls: list[ControlInfo]) -> ControlInfo:
    """The control whose name best matches, or a ToolError explaining why not.

    An exact name wins outright. Otherwise the closest is taken, but only if it
    is clearly closest: when two controls are near-equally good — "Send" and
    "Send later" — picking one silently is how an agent clicks the wrong thing
    on someone's computer, so it asks instead.
    """
    wanted = _clean(name)
    exact = [c for c in controls if _clean(c.name) == wanted]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise ToolError(f"Several controls are called '{name}': "
                        + ", ".join(f"[{c.index}] {c.role}" for c in exact[:6])
                        + ". Use the number instead.")
    scored = sorted(((SequenceMatcher(None, wanted, _clean(c.name)).ratio(), c)
                     for c in controls if c.name), key=lambda pair: -pair[0])
    if not scored or scored[0][0] < MATCH_FLOOR:
        near = ", ".join(f'"{c.name}"' for _, c in scored[:5]) or "nothing with a name"
        raise ToolError(f"No control here is called '{name}'. The closest are: {near}. "
                        "Look at the window again, or use the number.")
    if len(scored) > 1 and scored[0][0] - scored[1][0] < MATCH_MARGIN:
        raise ToolError(
            f"'{name}' could mean "
            + " or ".join(f'[{c.index}] "{c.name}"' for _, c in scored[:2])
            + ". Say which number.")
    return scored[0][1]


def _control(ctx: ToolContext, number: int | None = None, name: str | None = None) -> ControlInfo:
    controls = ctx.desktop.last_controls if ctx.desktop else []
    if not controls:
        raise ToolError("Look at the window first (look_at_window), then refer to controls by number or name.")
    if name:
        return match_control(name, controls)
    if number is None:
        raise ToolError("Say which control: a number from the last look, or its name.")
    if not 0 <= number < len(controls):
        raise ToolError(f"There is no control number {number}; the last look found {len(controls)}.")
    return controls[number]


# ---------- list_windows ----------
class NoArgs(ToolArgs):
    pass


async def list_windows(args: NoArgs, ctx: ToolContext) -> ToolResult:
    windows = await _d(ctx, "list_windows")
    text = "\n".join(f"- {'* ' if w.active else ''}{w.title} ({w.process or 'unknown app'})" for w in windows)
    return ToolResult(True, f"{len(windows)} window(s) open.", {"windows": [w.as_dict() for w in windows]}, True, text)


# ---------- focus_window ----------
class WindowArgs(ToolArgs):
    title: str = Field(min_length=1, max_length=200, description="Part of the window title")


async def focus_window(args: WindowArgs, ctx: ToolContext) -> ToolResult:
    target = _match_window(await _d(ctx, "list_windows"), args.title)
    await _d(ctx, "focus_window", target.handle)
    await asyncio.sleep(SETTLE_S)
    active = await _d(ctx, "active_window")
    ok = active is not None and active.handle == target.handle
    _use(ctx, target)
    return ToolResult(ok, f"Switched to '{target.title}'." if ok else f"Tried to switch to '{target.title}' but another window stayed in front.",
                      {"title": target.title}, verified=ok)


# ---------- launch_app ----------
class LaunchArgs(ToolArgs):
    name: str = Field(min_length=2, max_length=80, description="App name as in the Start menu, e.g. Notepad")


def check_launch(args: LaunchArgs, ctx: ToolContext) -> None:
    # Only refuse here for the reasons that are true before looking at the screen:
    # a system tool, or a name that matches nothing anywhere. An app with no
    # Start-menu shortcut may still be running, and launch_app handles that.
    if is_system_tool(args.name):
        choose_app(args.name, ctx.start_menu_dirs)      # raises, with the right words
    try:
        choose_app(args.name, ctx.start_menu_dirs)
    except ToolError:
        if _running_window(ctx, args.name) is None:
            raise


def _running_window(ctx: ToolContext, name: str) -> WindowInfo | None:
    """An open window of that app, for the many apps with no Start-menu shortcut.

    Store apps, anything pinned to the taskbar only, and anything already open
    all land here. Switching to a window that exists beats reporting that an app
    the person is looking at cannot be found.
    """
    if ctx.desktop is None:
        return None
    try:
        windows = ctx.desktop.driver.list_windows()
    except Exception:  # noqa: BLE001 - the desktop may be unavailable; that is not this function's error
        return None
    needle = name.strip().lower()
    for window in windows:
        title = (window.title or "").lower()
        process = (window.process or "").lower()
        if needle in title or needle == process or needle + ".exe" == process:
            return window
    return None


async def launch_app(args: LaunchArgs, ctx: ToolContext) -> ToolResult:
    try:
        app = choose_app(args.name, ctx.start_menu_dirs)
    except ToolError:
        # Switching to a window is a way to reach an app without a shortcut. It is
        # not a way to reach one S-CLAW refuses to open.
        already = None if is_system_tool(args.name) else _running_window(ctx, args.name)
        if already is None:
            raise
        await _d(ctx, "focus_window", already.handle)
        await asyncio.sleep(SETTLE_S)
        active = await _d(ctx, "active_window")
        ok = active is not None and active.handle == already.handle
        _use(ctx, already)
        return ToolResult(
            ok,
            f"{args.name} has no Start-menu shortcut, but it was already open: switched to "
            f"'{already.title}'." if ok
            else f"{args.name} is open as '{already.title}', but another window stayed in front.",
            {"app": args.name, "title": already.title, "was_running": True}, verified=ok)
    before = {w.handle for w in await _d(ctx, "list_windows")}
    await _d(ctx, "launch", app.target)
    deadline = time.monotonic() + LAUNCH_TIMEOUT_S
    new: list[WindowInfo] = []
    while time.monotonic() < deadline:
        await asyncio.sleep(0.5)
        new = [w for w in await _d(ctx, "list_windows") if w.handle not in before]
        if new:
            break
    if not new:
        return ToolResult(False, f"Started {app.name}, but no new window appeared within {LAUNCH_TIMEOUT_S:.0f} seconds.",
                          {"app": app.name}, False)
    win = new[0]
    _use(ctx, win)
    return ToolResult(True, f"Opened {app.name}: window '{win.title}'.", {"app": app.name, "title": win.title}, True)


# ---------- look_at_window ----------
class LookArgs(ToolArgs):
    title: str | None = Field(default=None, max_length=200, description="Part of the window title; default is the active window")


async def look_at_window(args: LookArgs, ctx: ToolContext) -> ToolResult:
    target = _match_window(await _d(ctx, "list_windows"), args.title)
    controls: list[ControlInfo] = await _d(ctx, "controls", target.handle, 120)
    _use(ctx, target)
    ctx.desktop.last_controls = controls
    text = f"Window: {target.title}\n" + "\n".join(c.line() for c in controls)
    return ToolResult(True, f"Found {len(controls)} controls in '{target.title}'.",
                      {"title": target.title, "count": len(controls)}, True, untrusted_text=text)


# ---------- click_control ----------
class ControlArgs(ToolArgs):
    number: int | None = Field(default=None, ge=0, le=500, description="Control number from the last look_at_window")
    name: str | None = Field(default=None, max_length=120, description='Or its name, e.g. "Send"')


def check_control(args: ControlArgs, ctx: ToolContext) -> None:
    c = _control(ctx, args.number, args.name)
    if not c.enabled:
        raise ToolError(f"Control [{c.index}] ('{c.name}') is disabled right now.")


def click_risk(args: ControlArgs, ctx: ToolContext) -> RiskLevel:
    try:
        return escalate_by_label(_control(ctx, args.number, args.name).name, RiskLevel.LOCAL_WRITE)
    except ToolError:
        return RiskLevel.LOCAL_WRITE


async def click_control(args: ControlArgs, ctx: ToolContext) -> ToolResult:
    c = _control(ctx, args.number, args.name)
    handle = ctx.desktop.last_window
    before = await _d(ctx, "snapshot", handle)
    await _d(ctx, "invoke", c.index)
    await asyncio.sleep(SETTLE_S)
    after = await _d(ctx, "snapshot", handle)
    notes = _changed(before, after)
    trouble = _trouble(before, after)
    if trouble:
        ctx.desktop.last_controls = []
        return ToolResult(False, f"Clicked '{c.name or c.role}', and an error-like dialog appeared: "
                          + ", ".join(f"'{t}'" for t in trouble) + ". Look at it before doing anything else.",
                          {"changes": notes, "dialogs": trouble}, verified=False)
    if notes:
        ctx.desktop.last_controls = []  # the screen changed: numbers must be looked up again
        return ToolResult(True, f"Clicked '{c.name or c.role}'. " + ". ".join(notes) + ".", {"changes": notes}, verified=True)
    return ToolResult(True, f"Clicked '{c.name or c.role}', but nothing visible changed.", {"changes": []}, verified=False)


# ---------- type_into ----------
class TypeIntoArgs(ToolArgs):
    text: str = Field(max_length=20000)
    number: int | None = Field(default=None, ge=0, le=500)
    name: str | None = Field(default=None, max_length=120, description='Or the box\'s name, e.g. "Message"')


async def type_into(args: TypeIntoArgs, ctx: ToolContext) -> ToolResult:
    c = _control(ctx, args.number, args.name)
    await _d(ctx, "set_text", c.index, args.text)
    ctx.desktop.last_typed = args.text
    await asyncio.sleep(0.2)
    value = await _d(ctx, "read", c.index)
    expected = " ".join(args.text.split())
    ok = expected[:200] in " ".join(value.split())
    return ToolResult(
        True,
        f"Typed {len(args.text)} characters into '{c.name or c.role}'" + (" and checked it is there." if ok else ", but could not read it back to check."),
        {"chars": len(args.text)},
        verified=ok,
    )


# ---------- type_text ----------
class TypeArgs(ToolArgs):
    text: str = Field(min_length=1, max_length=20000)


TYPE_CHUNK = 40  # characters per keyboard burst (~0.4 s): Stop / Ctrl+Alt+X takes effect between bursts


async def type_text(args: TypeArgs, ctx: ToolContext) -> ToolResult:
    ctx.desktop.last_typed = args.text
    for i in range(0, len(args.text), TYPE_CHUNK):
        await _d(ctx, "type_keys", args.text[i:i + TYPE_CHUNK])
    return ToolResult(True, f"Typed {len(args.text)} characters into the active window.", {"chars": len(args.text)}, verified=False)


# ---------- press_keys ----------
class KeysArgs(ToolArgs):
    keys: list[str] = Field(min_length=1, max_length=4, description='e.g. ["ctrl", "s"] or ["enter"]')

    @field_validator("keys")
    @classmethod
    def _valid(cls, keys: list[str]) -> list[str]:
        keys = [k.strip().lower() for k in keys]
        main = [k for k in keys if k not in MODIFIERS]
        if len(main) != 1:
            raise ValueError("press exactly one main key, optionally with ctrl/alt/shift")
        if main[0] not in ALLOWED_KEYS:
            raise ValueError(f"the key '{main[0]}' is not allowed")
        if "win" in keys or "windows" in keys:
            raise ValueError("the Windows key is not allowed")
        if any(combo <= set(keys) for combo in BLOCKED_COMBOS):
            raise ValueError("that key combination is not allowed")
        return keys


async def press_keys(args: KeysArgs, ctx: ToolContext) -> ToolResult:
    handle = ctx.desktop.last_window
    before = await _d(ctx, "snapshot", handle)
    await _d(ctx, "send_keys", args.keys)
    await asyncio.sleep(SETTLE_S)
    after = await _d(ctx, "snapshot", handle)
    notes = _changed(before, after)
    trouble = _trouble(before, after)
    label = "+".join(args.keys)
    if notes:
        ctx.desktop.last_controls = []
    if trouble:
        return ToolResult(False, f"Pressed {label}, and an error-like dialog appeared: " + ", ".join(f"'{t}'" for t in trouble) + ".",
                          {"changes": notes, "dialogs": trouble}, verified=False)
    return ToolResult(True, f"Pressed {label}." + (" " + ". ".join(notes) + "." if notes else ""), {"changes": notes}, verified=bool(notes))


# ---------- read_control ----------
async def read_control(args: ControlArgs, ctx: ToolContext) -> ToolResult:
    c = _control(ctx, args.number, args.name)
    value = await _d(ctx, "read", c.index)
    return ToolResult(True, f"Read '{c.name or c.role}' ({len(value)} characters).", {"chars": len(value)}, True, untrusted_text=value[:8000])


# ---------- screenshots ----------
class ShotArgs(ToolArgs):
    title: str | None = Field(default=None, max_length=200, description="Part of a window title; default is the whole screen")


async def _shot(ctx: ToolContext, title: str | None) -> tuple[bytes, Path]:
    handle = None
    if title:
        handle = _match_window(await _d(ctx, "list_windows"), title).handle
    png = await _d(ctx, "screenshot", handle)
    folder = ctx.data_dir / "screenshots" / ctx.task_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{len(list(folder.glob('*.png'))) + 1:02d}.png"
    path.write_bytes(png)
    ctx.desktop.screenshot_taken = True
    return png, path


async def take_screenshot(args: ShotArgs, ctx: ToolContext) -> ToolResult:
    png, path = await _shot(ctx, args.title)
    return ToolResult(True, f"Saved a screenshot ({len(png) // 1024} KB).", {"path": str(path)}, verified=len(png) > 100)


class DescribeArgs(ToolArgs):
    question: str = Field(default="Describe what is on the screen, including any dialogs, errors and the main buttons.", max_length=500)
    title: str | None = Field(default=None, max_length=200)


async def describe_screen(args: DescribeArgs, ctx: ToolContext) -> ToolResult:
    if ctx.vision is None:
        raise ToolError("Reading the screen needs the Online brain or the offline seeing model.")
    png, path = await _shot(ctx, args.title)
    answer = await ctx.vision(png, args.question)
    return ToolResult(True, "Looked at the screen.", {"path": str(path)}, verified=True, untrusted_text=answer[:6000])


# ---------- click_at (visual fallback) ----------
class ClickAtArgs(ToolArgs):
    x: int = Field(ge=0, le=20000)
    y: int = Field(ge=0, le=20000)
    reason: str = Field(min_length=3, max_length=200, description="What is at this point")


def check_click_at(args: ClickAtArgs, ctx: ToolContext) -> None:
    if ctx.desktop is None or not ctx.desktop.screenshot_taken:
        raise ToolError("Take a screenshot or describe the screen before clicking at a position.")


async def click_at(args: ClickAtArgs, ctx: ToolContext) -> ToolResult:
    w, h = await _d(ctx, "screen_size")
    if args.x >= w or args.y >= h:
        raise ToolError(f"({args.x}, {args.y}) is outside the screen ({w}×{h}).")
    handle = ctx.desktop.last_window
    before = await _d(ctx, "snapshot", handle)
    await _d(ctx, "click_at", args.x, args.y)
    await asyncio.sleep(SETTLE_S)
    after = await _d(ctx, "snapshot", handle)
    notes = _changed(before, after)
    if notes:
        ctx.desktop.last_controls = []
    return ToolResult(True, f"Clicked at ({args.x}, {args.y}) — {args.reason}." + (" " + ". ".join(notes) + "." if notes else " Nothing visible changed."),
                      {"changes": notes}, verified=bool(notes))


# ---------- scroll ----------
class ScrollArgs(ToolArgs):
    title: str | None = Field(default=None, max_length=200, description="Part of the window title; default the active window")
    direction: str = Field(default="down", pattern="^(up|down)$")
    clicks: int = Field(default=5, ge=1, le=30, description="Mouse-wheel notches")


async def scroll(args: ScrollArgs, ctx: ToolContext) -> ToolResult:
    target = _match_window(await _d(ctx, "list_windows"), args.title)
    before = await _d(ctx, "snapshot", target.handle)
    await _d(ctx, "scroll", target.handle, args.direction == "down", args.clicks)
    await asyncio.sleep(0.4)
    after = await _d(ctx, "snapshot", target.handle)
    moved = after.control_names != before.control_names
    if moved:
        ctx.desktop.last_controls = []
    _use(ctx, target)
    return ToolResult(True, f"Scrolled {args.direction} in '{target.title}'." + ("" if moved else " Nothing changed (maybe already at the end)."),
                      {"moved": moved}, verified=moved)


# ---------- choose_menu ----------
class MenuArgs(ToolArgs):
    path: list[str] = Field(min_length=1, max_length=5, description='Menu path, e.g. ["File", "Save As..."]')
    title: str | None = Field(default=None, max_length=200)


def menu_risk(args: MenuArgs, ctx: ToolContext) -> RiskLevel:
    return escalate_by_label(args.path[-1], RiskLevel.LOCAL_WRITE)


async def choose_menu(args: MenuArgs, ctx: ToolContext) -> ToolResult:
    target = _match_window(await _d(ctx, "list_windows"), args.title)
    before = await _d(ctx, "snapshot", target.handle)
    await _d(ctx, "menu_select", target.handle, args.path)
    await asyncio.sleep(SETTLE_S)
    after = await _d(ctx, "snapshot", target.handle)
    notes, trouble = _changed(before, after), _trouble(before, after)
    ctx.desktop.last_controls = []
    _use(ctx, target)
    label = " > ".join(args.path)
    if trouble:
        return ToolResult(False, f"Chose {label}; an error-like dialog appeared: " + ", ".join(trouble) + ".",
                          {"changes": notes, "dialogs": trouble}, verified=False)
    return ToolResult(True, f"Chose {label}." + (" " + ". ".join(notes) + "." if notes else " Nothing visible changed."),
                      {"changes": notes}, verified=bool(notes))


# ---------- wait_for_window ----------
class WaitArgs(ToolArgs):
    title: str = Field(min_length=1, max_length=200, description="Part of the expected window or dialog title")
    seconds: int = Field(default=15, ge=1, le=120)


async def wait_for_window(args: WaitArgs, ctx: ToolContext) -> ToolResult:
    deadline = time.monotonic() + args.seconds
    needle = args.title.lower()
    while True:
        hits = [w for w in await _d(ctx, "list_windows") if needle in w.title.lower()]
        if hits:
            _use(ctx, hits[0])
            kind = "dialog" if hits[0].dialog else "window"
            return ToolResult(True, f"The {kind} '{hits[0].title}' is open.", {"title": hits[0].title, "dialog": hits[0].dialog}, verified=True)
        if time.monotonic() >= deadline:
            return ToolResult(False, f"No window titled like '{args.title}' appeared within {args.seconds} seconds.", {}, verified=True)
        await asyncio.sleep(0.5)


def register_desktop_tools(reg: ToolRegistry) -> None:
    D, R, W = Capability.DESKTOP, RiskLevel.READ_ONLY, RiskLevel.LOCAL_WRITE
    reg.register(ToolSpec("list_windows", "List open windows on the desktop.", D, R, NoArgs, list_windows))
    reg.register(ToolSpec("focus_window", "Bring a window to the front by part of its title.", D, R, WindowArgs, focus_window))
    reg.register(ToolSpec("launch_app", "Open an installed app by name (e.g. Notepad, Excel). System tools are not allowed.",
                          D, W, LaunchArgs, launch_app, precheck=check_launch))
    reg.register(ToolSpec("look_at_window", "List a window's buttons, fields and menus with numbers.", D, R, LookArgs, look_at_window))
    reg.register(ToolSpec("click_control", "Click a control, by its number from look_at_window or by its name.", D, W, ControlArgs, click_control,
                          precheck=check_control, risk_for=click_risk))
    reg.register(ToolSpec("type_into", "Put text into a field, by its number from look_at_window or by its name.", D, W, TypeIntoArgs, type_into,
                          precheck=lambda a, c: _control(c, a.number, a.name), risk_for=typing_risk,
                          context_for=sending_context))
    reg.register(ToolSpec("type_text", "Type text into whatever has keyboard focus.", D, W, TypeArgs, type_text, risk_for=typing_risk,
                          context_for=sending_context))
    reg.register(ToolSpec("press_keys", 'Press a key or shortcut, e.g. ["ctrl", "s"].', D, W, KeysArgs, press_keys, risk_for=keys_risk,
                          context_for=sending_context))
    reg.register(ToolSpec("read_control", "Read the text in a control, by number or by name.", D, R, ControlArgs, read_control,
                          precheck=lambda a, c: _control(c, a.number, a.name)))
    reg.register(ToolSpec("scroll", "Scroll a window up or down.", D, R, ScrollArgs, scroll))
    reg.register(ToolSpec("choose_menu", 'Choose a menu item by its path, e.g. ["File", "Save As..."].', D, W, MenuArgs, choose_menu,
                          risk_for=menu_risk))
    reg.register(ToolSpec("wait_for_window", "Wait until a window or dialog with this title appears.", D, R, WaitArgs, wait_for_window))
    reg.register(ToolSpec("take_screenshot", "Save a screenshot of the screen or one window.", D, R, ShotArgs, take_screenshot))
    reg.register(ToolSpec("describe_screen", "Look at the screen and answer a question about it.", D, R, DescribeArgs, describe_screen))
    reg.register(ToolSpec("click_at", "Click at screen coordinates (only when look_at_window can't find the control).",
                          D, W, ClickAtArgs, click_at, precheck=check_click_at))
