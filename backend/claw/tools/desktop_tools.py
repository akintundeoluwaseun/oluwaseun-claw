"""Desktop tools: windows, controls, typing, keys, screenshots.

Each action takes a before/after snapshot of the screen state where it can, so
results are reported as "checked" only when the change was actually observed.
Accessibility (UI Automation) is used first; clicking at screen coordinates is
a separate, explicitly-approved fallback that requires a screenshot first.
"""

from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path

from pydantic import Field, field_validator

from claw.agent.schemas import Capability
from claw.computer.driver import ControlInfo, DesktopUnavailable, Snapshot, WindowInfo
from claw.computer.launcher import choose_app
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


def _use(ctx: ToolContext, win: WindowInfo) -> None:
    ctx.desktop.last_window = win.handle
    ctx.desktop.last_process = (win.process or "").lower()


def _in_messaging_app(ctx: ToolContext) -> bool:
    return ctx is not None and ctx.desktop is not None and ctx.desktop.last_process in MESSAGING_APPS


def keys_risk(args, ctx: ToolContext) -> RiskLevel:
    return RiskLevel.DESTRUCTIVE if "enter" in args.keys and _in_messaging_app(ctx) else RiskLevel.LOCAL_WRITE


def typing_risk(args, ctx: ToolContext) -> RiskLevel:
    return RiskLevel.DESTRUCTIVE if ("\n" in args.text or "\r" in args.text) and _in_messaging_app(ctx) else RiskLevel.LOCAL_WRITE


def _control(ctx: ToolContext, number: int) -> ControlInfo:
    controls = ctx.desktop.last_controls if ctx.desktop else []
    if not controls:
        raise ToolError("Look at the window first (look_at_window), then refer to controls by number.")
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
    choose_app(args.name, ctx.start_menu_dirs)


async def launch_app(args: LaunchArgs, ctx: ToolContext) -> ToolResult:
    app = choose_app(args.name, ctx.start_menu_dirs)
    before = {w.handle for w in await _d(ctx, "list_windows")}
    await _d(ctx, "launch", app.target)
    deadline = time.monotonic() + 15
    new: list[WindowInfo] = []
    while time.monotonic() < deadline:
        await asyncio.sleep(0.5)
        new = [w for w in await _d(ctx, "list_windows") if w.handle not in before]
        if new:
            break
    if not new:
        return ToolResult(False, f"Started {app.name}, but no new window appeared within 15 seconds.", {"app": app.name}, False)
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
    number: int = Field(ge=0, le=500, description="Control number from the last look_at_window")


def check_control(args: ControlArgs, ctx: ToolContext) -> None:
    c = _control(ctx, args.number)
    if not c.enabled:
        raise ToolError(f"Control {args.number} ('{c.name}') is disabled right now.")


def click_risk(args: ControlArgs, ctx: ToolContext) -> RiskLevel:
    try:
        return escalate_by_label(_control(ctx, args.number).name, RiskLevel.LOCAL_WRITE)
    except ToolError:
        return RiskLevel.LOCAL_WRITE


async def click_control(args: ControlArgs, ctx: ToolContext) -> ToolResult:
    c = _control(ctx, args.number)
    handle = ctx.desktop.last_window
    before = await _d(ctx, "snapshot", handle)
    await _d(ctx, "invoke", args.number)
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
    number: int = Field(ge=0, le=500)
    text: str = Field(max_length=20000)


async def type_into(args: TypeIntoArgs, ctx: ToolContext) -> ToolResult:
    c = _control(ctx, args.number)
    await _d(ctx, "set_text", args.number, args.text)
    await asyncio.sleep(0.2)
    value = await _d(ctx, "read", args.number)
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
    c = _control(ctx, args.number)
    value = await _d(ctx, "read", args.number)
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
    reg.register(ToolSpec("click_control", "Click a control by its number from look_at_window.", D, W, ControlArgs, click_control,
                          precheck=check_control, risk_for=click_risk))
    reg.register(ToolSpec("type_into", "Put text into a field by its number from look_at_window.", D, W, TypeIntoArgs, type_into,
                          precheck=lambda a, c: _control(c, a.number), risk_for=typing_risk))
    reg.register(ToolSpec("type_text", "Type text into whatever has keyboard focus.", D, W, TypeArgs, type_text, risk_for=typing_risk))
    reg.register(ToolSpec("press_keys", 'Press a key or shortcut, e.g. ["ctrl", "s"].', D, W, KeysArgs, press_keys, risk_for=keys_risk))
    reg.register(ToolSpec("read_control", "Read the text in a control by its number.", D, R, ControlArgs, read_control,
                          precheck=lambda a, c: _control(c, a.number)))
    reg.register(ToolSpec("scroll", "Scroll a window up or down.", D, R, ScrollArgs, scroll))
    reg.register(ToolSpec("choose_menu", 'Choose a menu item by its path, e.g. ["File", "Save As..."].', D, W, MenuArgs, choose_menu,
                          risk_for=menu_risk))
    reg.register(ToolSpec("wait_for_window", "Wait until a window or dialog with this title appears.", D, R, WaitArgs, wait_for_window))
    reg.register(ToolSpec("take_screenshot", "Save a screenshot of the screen or one window.", D, R, ShotArgs, take_screenshot))
    reg.register(ToolSpec("describe_screen", "Look at the screen and answer a question about it.", D, R, DescribeArgs, describe_screen))
    reg.register(ToolSpec("click_at", "Click at screen coordinates (only when look_at_window can't find the control).",
                          D, W, ClickAtArgs, click_at, precheck=check_click_at))
