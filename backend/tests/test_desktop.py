"""Desktop control logic against the TEST DOUBLE desktop (tests/fake_desktop.py).
The real Windows UI Automation driver is not exercised here (no Windows)."""

import json
import os
import sys

import pytest

from claw.agent.executor import run_agent
from claw.computer.driver import UnsupportedDriver, default_driver
from claw.computer.launcher import choose_app, find_app
from claw.models.base import ChatMessage
from claw.models.ollama import OllamaAdapter
from claw.permissions.policy import Decision, PermissionPolicy, RiskLevel
from claw.tools.base import ToolError
from claw.tools.registry import build_registry

REG = build_registry()


async def call(ctx, tool_name, **args):
    spec = REG.get(tool_name)
    parsed = spec.parse_args(args)
    if spec.precheck:
        spec.precheck(parsed, ctx)
    return await spec.handler(parsed, ctx)


def act(tool, **args):
    return json.dumps({"thought": tool, "action": "tool", "tool": tool, "args": args})


# ---------- launcher ----------
def test_builtin_and_start_menu_apps(tmp_path):
    assert choose_app("notepad").target == "notepad.exe"
    menu = tmp_path / "m"
    menu.mkdir()
    for n in ("Excel.lnk", "Visual Studio Code.lnk", "Visual Studio Installer.lnk"):
        (menu / n).write_text("x")
    assert choose_app("excel", [menu]).name == "Excel"
    assert choose_app("visual studio code", [menu]).name == "Visual Studio Code"
    with pytest.raises(ToolError, match="More than one"):
        choose_app("visual studio", [menu])
    with pytest.raises(ToolError, match="No installed app"):
        choose_app("photoshop", [menu])


@pytest.mark.parametrize("name", ["cmd", "Command Prompt", "PowerShell", "regedit", "Windows Security", "control panel"])
def test_system_tools_refused(name, tmp_path):
    with pytest.raises(ToolError, match="system tools"):
        find_app(name, [tmp_path])


def test_off_windows_the_posix_driver_is_used():
    if sys.platform == "win32":
        pytest.skip("Windows has the real driver")
    from claw.computer.posix_driver import LinuxX11Driver, MacDriver

    d = default_driver()
    assert isinstance(d, (LinuxX11Driver, MacDriver))


# ---------- tools ----------
async def test_open_type_save_in_notepad(desk_ctx):
    fake = desk_ctx.fake
    r = await call(desk_ctx, "launch_app", name="Notepad")
    assert r.verified and "Untitled - Notepad" in r.summary
    look = await call(desk_ctx, "look_at_window")
    assert '[0] Document "Text editor"' in look.untrusted_text
    typed = await call(desk_ctx, "type_into", number=0, text="Shopping: rice, beans")
    assert typed.verified
    saved = await call(desk_ctx, "click_control", number=3)  # Save
    assert saved.verified and "A dialog opened: 'Save As'" in saved.summary
    with pytest.raises(ToolError, match="Look at the window first"):
        await call(desk_ctx, "click_control", number=3)  # numbers are stale after the screen changed
    await call(desk_ctx, "look_at_window", title="Save As")
    await call(desk_ctx, "type_into", number=0, text="notes.txt")
    done = await call(desk_ctx, "click_control", number=1)
    assert done.verified and "Closed: 'Save As'" in done.summary
    assert fake.saved == {"notes.txt": "Shopping: rice, beans"}
    win = await call(desk_ctx, "list_windows")
    assert "* notes.txt - Notepad" in win.untrusted_text


async def test_click_with_no_visible_change_is_not_verified(desk_ctx):
    await call(desk_ctx, "launch_app", name="Notepad")
    await call(desk_ctx, "look_at_window")
    r = await call(desk_ctx, "click_control", number=1)  # File menu: nothing changes in the stand-in
    assert r.ok and not r.verified and "nothing visible changed" in r.summary


async def test_focus_window(desk_ctx):
    await call(desk_ctx, "launch_app", name="Notepad")
    r = await call(desk_ctx, "focus_window", title="file explorer")
    assert r.verified
    with pytest.raises(ToolError, match="No open window"):
        await call(desk_ctx, "focus_window", title="Photoshop")


async def test_locked_screen_explained(desk_ctx):
    desk_ctx.fake.locked = True
    with pytest.raises(ToolError, match="locked"):
        await call(desk_ctx, "list_windows")


def test_key_rules():
    spec = REG.get("press_keys")
    assert spec.parse_args({"keys": ["Ctrl", "S"]}).keys == ["ctrl", "s"]
    for bad in (["win", "r"], ["ctrl", "alt", "delete"], ["alt", "tab"], ["ctrl", "s", "x"], ["ctrl"], ["printscreen"]):
        with pytest.raises(ToolError):
            spec.parse_args({"keys": bad})


async def test_ctrl_s_opens_dialog(desk_ctx):
    await call(desk_ctx, "launch_app", name="Notepad")
    r = await call(desk_ctx, "press_keys", keys=["ctrl", "s"])
    assert r.verified and "Save As" in r.summary


async def test_click_at_needs_screenshot_and_bounds(desk_ctx, tmp_path):
    with pytest.raises(ToolError, match="screenshot"):
        await call(desk_ctx, "click_at", x=10, y=10, reason="the OK button")
    shot = await call(desk_ctx, "take_screenshot")
    assert os.path.exists(shot.data["path"]) and open(shot.data["path"], "rb").read(4) == b"\x89PNG"
    with pytest.raises(ToolError, match="outside the screen"):
        await call(desk_ctx, "click_at", x=5000, y=10, reason="far right")
    await call(desk_ctx, "click_at", x=100, y=200, reason="the OK button")
    assert desk_ctx.fake.clicks_at == [(100, 200)]


async def test_describe_screen_uses_vision_and_marks_untrusted(desk_ctx):
    with pytest.raises(ToolError, match="Online brain"):
        await call(desk_ctx, "describe_screen")
    asked = []

    async def stub_vision(png, q):  # TEST DOUBLE for the seeing model
        asked.append((png[:4], q))
        return "A Notepad window with a Save dialog."

    desk_ctx.vision = stub_vision
    r = await call(desk_ctx, "describe_screen", question="Is a dialog open?")
    assert r.untrusted_text.startswith("A Notepad window") and asked == [(b"\x89PNG", "Is a dialog open?")]


# ---------- the whole loop, with permissions ----------
async def run(ctx, fake_server, replies, approve=True, task="Open Notepad, write a shopping list and save it as notes.txt"):
    fake_server.replies.extend(replies)
    approvals = []

    async def approval(payload):
        approvals.append(payload)
        return approve

    adapter = OllamaAdapter(fake_server.base_url, "qwen2.5:7b", timeout_s=10, temperature=0)
    out = await run_agent(task, "", adapter, REG, ctx, lambda k, d: None, approval)
    return out, approvals


async def test_batch3_acceptance_flow(desk_ctx, fake_server):
    out, approvals = await run(
        desk_ctx, fake_server,
        [
            act("launch_app", name="Notepad"),
            act("look_at_window"),
            act("type_into", number=0, text="rice\nbeans\nplantain"),
            act("press_keys", keys=["ctrl", "s"]),
            act("look_at_window", title="Save As"),
            act("type_into", number=0, text="notes.txt"),
            act("click_control", number=1),
            act("list_windows"),
            json.dumps({"thought": "done", "action": "finish", "final_answer": "Saved notes.txt in Notepad."}),
        ],
    )
    assert out.status == "completed", out.summary()
    assert [s["outcome"] for s in out.steps] == ["verified"] * 8
    assert desk_ctx.fake.saved["notes.txt"] == "rice\nbeans\nplantain"
    assert [a["tool"] for a in approvals] == ["launch_app", "type_into", "press_keys", "type_into", "click_control"]


async def test_send_button_in_app_needs_ok_even_when_writes_allowed(desk_ctx, fake_server):
    desk_ctx.policy = PermissionPolicy({RiskLevel.LOCAL_WRITE: Decision.ALLOW}, [])
    out, approvals = await run(
        desk_ctx, fake_server,
        [act("launch_app", name="Notepad"), act("look_at_window"), act("click_control", number=4)],
        approve=False,
    )
    assert [a["tool"] for a in approvals] == ["click_control"] and approvals[0]["risk"] == "destructive"
    assert out.status == "stopped"


async def test_blocked_app_refused_before_asking(desk_ctx, fake_server):
    out, approvals = await run(
        desk_ctx, fake_server,
        [act("launch_app", name="PowerShell"), json.dumps({"thought": "x", "action": "finish", "final_answer": "Not allowed."})],
    )
    assert approvals == [] and out.steps[0]["outcome"] == "failed"


# ---------- the failure paths of launch / focus / keys ----------
# These are the cases that matter on a real desktop and that the happy-path tests
# above never reach. They still run against the TEST DOUBLE: passing here says the
# logic is right, not that Windows behaves this way.
async def test_launch_reports_honestly_when_no_window_appears(desk_ctx, monkeypatch):
    from claw.tools import desktop_tools

    monkeypatch.setattr(desktop_tools, "LAUNCH_TIMEOUT_S", 1.0)
    monkeypatch.setattr(desk_ctx.fake, "launch", lambda target: desk_ctx.fake.launched.append(target))
    r = await call(desk_ctx, "launch_app", name="Notepad")
    assert r.ok is False and r.verified is False
    assert "no new window appeared" in r.summary
    assert desk_ctx.fake.launched  # it really did try


async def test_launch_refuses_system_tools_before_touching_the_desktop(desk_ctx):
    with pytest.raises(ToolError, match="system tools"):
        await call(desk_ctx, "launch_app", name="Command Prompt")
    assert desk_ctx.fake.launched == []


async def test_focus_is_not_verified_when_another_window_stays_in_front(desk_ctx, monkeypatch):
    await call(desk_ctx, "launch_app", name="Notepad")
    monkeypatch.setattr(desk_ctx.fake, "focus_window", lambda handle: None)  # focus refused
    r = await call(desk_ctx, "focus_window", title="file explorer")
    assert r.ok is False and r.verified is False
    assert "stayed in front" in r.summary


async def test_an_ambiguous_window_title_is_refused_with_the_candidates(desk_ctx):
    await call(desk_ctx, "launch_app", name="Notepad")
    desk_ctx.fake.windows[desk_ctx.fake.next_handle] = {
        "title": "Untitled - Notepad (2)", "process": "notepad.exe", "controls": []}
    with pytest.raises(ToolError, match="Several windows match"):
        await call(desk_ctx, "focus_window", title="notepad")


async def test_press_keys_reports_an_error_dialog_and_does_not_claim_success(desk_ctx):
    await call(desk_ctx, "launch_app", name="Notepad")

    def angry(keys):
        h = desk_ctx.fake.next_handle
        desk_ctx.fake.next_handle += 1
        desk_ctx.fake.windows[h] = {"title": "Error saving file", "process": "notepad.exe",
                                    "dialog": True, "controls": [{"role": "Button", "name": "OK"}]}
        desk_ctx.fake.active = h

    desk_ctx.fake.send_keys = angry
    r = await call(desk_ctx, "press_keys", keys=["ctrl", "s"])
    assert r.ok is False and r.verified is False
    assert "Error saving file" in r.summary


async def test_press_keys_with_no_effect_is_not_counted_as_verified(desk_ctx):
    await call(desk_ctx, "launch_app", name="Notepad")
    r = await call(desk_ctx, "press_keys", keys=["f5"])  # the stand-in ignores it
    assert r.ok is True and r.verified is False


async def test_typing_is_only_verified_when_it_reads_back(desk_ctx, monkeypatch):
    await call(desk_ctx, "launch_app", name="Notepad")
    await call(desk_ctx, "look_at_window")
    good = await call(desk_ctx, "type_into", number=0, text="Hello from Claw")
    assert good.verified is True
    monkeypatch.setattr(desk_ctx.fake, "read", lambda index: "something else entirely")
    bad = await call(desk_ctx, "type_into", number=0, text="Hello again")
    assert bad.verified is False and "could not read it back" in bad.summary
