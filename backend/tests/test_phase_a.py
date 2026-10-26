"""Phase A: Windows-control hardening, Notepad test A, browser forms and downloads, file copies.

Real: the browser (Chromium) against the local test website, files on disk, permissions,
the executor. TEST DOUBLE: the Windows desktop (tests/fake_desktop.py) and the model's replies.
Test A on real Windows is BLOCKED here; see docs/WINDOWS_ACCEPTANCE.md.
"""

import json
import os
from pathlib import Path

import pytest

from claw.agent.executor import run_agent
from claw.models.openai_compat import OpenAICompatAdapter
from claw.permissions.policy import Decision, PermissionPolicy, RiskLevel
from claw.tools.base import ToolError
from claw.tools.registry import build_registry
from tests.test_desktop import act, call

REG = build_registry()
TEST_A_TEXT = "Oluwaseun Claw desktop-control test"


def finish(text):
    return json.dumps({"thought": "done", "action": "finish", "final_answer": text})


async def run(ctx, fake_server, replies, task, approve=True):
    fake_server.replies.extend(replies)
    approvals = []

    async def approval(payload):
        approvals.append(payload)
        return approve

    adapter = OpenAICompatAdapter(fake_server.base_url, "qwen2.5:7b", timeout_s=10, temperature=0)
    out = await run_agent(task, "", adapter, REG, ctx, lambda k, d: None, approval)
    return out, approvals


# ---------- Test A logic: Notepad → save → reopen → verify exact contents ----------
async def test_a_notepad_save_reopen_verify(desk_ctx, fake_server, tmp_path):
    docs = Path(desk_ctx.settings.permissions.authorized_folders[0])
    target = docs / "claw-test.txt"
    out, approvals = await run(desk_ctx, fake_server, [
        act("launch_app", name="Notepad"),
        act("look_at_window"),
        act("type_into", number=0, text=TEST_A_TEXT),
        act("choose_menu", path=["File", "Save As..."]),
        act("look_at_window", title="Save As"),
        act("type_into", number=0, text=str(target)),
        act("click_control", number=1),
        act("check_file", path=str(target), expected_text=TEST_A_TEXT),
        finish(f"Saved and verified {target}."),
    ], task=f"Open Notepad, type '{TEST_A_TEXT}', save it as claw-test.txt in Documents, reopen it, and verify the exact contents.")
    assert out.status == "completed", out.summary()
    assert [s["outcome"] for s in out.steps] == ["verified"] * 8
    assert target.read_text(encoding="utf-8") == TEST_A_TEXT
    assert "match exactly" in out.steps[-1]["detail"]


async def test_check_file_reports_mismatch_and_missing(tool_ctx):
    folder = Path(tool_ctx.settings.permissions.authorized_folders[0])
    (folder / "a.txt").write_text("Oluwaseun Claw desktop control test\n", encoding="utf-8")  # one hyphen missing
    r = await call(tool_ctx, "check_file", path=str(folder / "a.txt"), expected_text=TEST_A_TEXT)
    assert not r.ok and r.verified and "do not match" in r.summary
    r = await call(tool_ctx, "check_file", path=str(folder / "nope.txt"), expected_text=TEST_A_TEXT)
    assert not r.ok and "no file" in r.summary
    (folder / "b.txt").write_bytes(("\ufeff" + TEST_A_TEXT + "\r\n").encode("utf-8"))  # BOM + CRLF are not content
    assert (await call(tool_ctx, "check_file", path=str(folder / "b.txt"), expected_text=TEST_A_TEXT)).ok
    with pytest.raises(ToolError):
        await call(tool_ctx, "check_file", path="/etc/passwd", expected_text="root")


# ---------- unexpected dialogs ----------
async def test_error_dialog_is_detected_and_not_counted_as_done(desk_ctx):
    await call(desk_ctx, "launch_app", name="Notepad")
    await call(desk_ctx, "look_at_window")
    await call(desk_ctx, "type_into", number=0, text="x")
    await call(desk_ctx, "choose_menu", path=["File", "Save As"])
    await call(desk_ctx, "look_at_window", title="Save As")
    await call(desk_ctx, "type_into", number=0, text="C:\\Forbidden\\x.txt")
    r = await call(desk_ctx, "click_control", number=1)
    assert not r.ok and not r.verified and "error-like dialog" in r.summary and r.data["dialogs"] == ["Save As - Error"]


async def test_menu_scroll_and_wait(desk_ctx):
    await call(desk_ctx, "launch_app", name="Notepad")
    r = await call(desk_ctx, "choose_menu", path=["File", "Save As..."])
    assert r.verified and "A dialog opened: 'Save As'" in r.summary
    w = await call(desk_ctx, "wait_for_window", title="save as", seconds=2)
    assert w.verified and w.data["dialog"] is True
    missing = await call(desk_ctx, "wait_for_window", title="Photoshop", seconds=1)
    assert not missing.ok and "within 1 seconds" in missing.summary
    with pytest.raises(ToolError, match="no menu item"):
        await call(desk_ctx, "choose_menu", path=["Tools", "Nothing"], title="Notepad")
    s = await call(desk_ctx, "scroll", title="Untitled", direction="down", clicks=3)
    assert s.verified
    up = await call(desk_ctx, "scroll", title="Untitled", direction="up", clicks=10)
    assert up.verified
    top = await call(desk_ctx, "scroll", title="Untitled", direction="up", clicks=1)
    assert not top.verified and "Nothing changed" in top.summary


def test_menu_item_that_deletes_needs_ok():
    spec = REG.get("choose_menu")
    assert spec.effective_risk(spec.parse_args({"path": ["Edit", "Delete"]}), None) == RiskLevel.DESTRUCTIVE
    assert spec.effective_risk(spec.parse_args({"path": ["File", "Save As..."]}), None) == RiskLevel.LOCAL_WRITE


# ---------- browser forms ----------
async def test_fill_form_fields_but_never_secrets(tool_ctx, site):
    await call(tool_ctx, "open_url", url=site.base_url + "/form")
    r = await call(tool_ctx, "fill_field", field="Full name", value="Ada Okafor")
    assert r.verified
    r = await call(tool_ctx, "fill_field", field="you@example.com", value="ada@example.com")
    assert r.verified
    r = await call(tool_ctx, "fill_field", field="Country", value="Nigeria")
    assert r.verified and r.data["kind"] == "select"
    r = await call(tool_ctx, "fill_field", field="Send me news", value="yes")
    assert r.verified
    with pytest.raises(ToolError, match="never types"):
        await call(tool_ctx, "fill_field", field="Password", value="hunter2")
    with pytest.raises(ToolError, match="No form field"):
        await call(tool_ctx, "fill_field", field="Shoe size", value="44")
    page = await tool_ctx.browser.page()
    assert await page.locator("input[name=fullname]").input_value() == "Ada Okafor"
    assert (await (await tool_ctx.browser.page()).content()).count("Message sent") == 0  # nothing was submitted
    assert REG.get("click_button").effective_risk(REG.get("click_button").parse_args({"text": "Submit registration"}), tool_ctx) == RiskLevel.DESTRUCTIVE


# ---------- downloads ----------
async def test_download_into_authorized_folder_and_refuse_programs(tool_ctx, site):
    folder = Path(tool_ctx.settings.permissions.authorized_folders[0])
    await call(tool_ctx, "open_url", url=site.base_url + "/form")
    r = await call(tool_ctx, "download_file", link_text="Download price list")
    assert r.verified and Path(r.data["path"]).parent == folder
    assert Path(r.data["path"]).read_text() == "item,price\nCharger,3500\nCable,1500\n"
    again = await call(tool_ctx, "download_file", url=site.base_url + "/files/price-list.csv")
    assert again.verified and again.data["path"] != r.data["path"]  # never overwrites
    with pytest.raises(ToolError, match="programs or scripts"):
        await call(tool_ctx, "download_file", link_text="Get the installer")
    with pytest.raises(ToolError, match="programs or scripts"):
        await call(tool_ctx, "download_file", url=site.base_url + "/files/setup.exe")
    assert not list(folder.glob("*.exe"))
    with pytest.raises(ToolError):
        await call(tool_ctx, "download_file", link_text="Download price list", folder="/tmp")


# ---------- copy / organise files ----------
async def test_copy_screenshots_into_new_folder(tool_ctx):
    folder = Path(tool_ctx.settings.permissions.authorized_folders[0])
    pics = folder / "Pictures"
    pics.mkdir()
    for n in ("Screenshot 2026-10-01 101010.png", "Screenshot (2).png", "holiday.jpg", "notes.txt"):
        (pics / n).write_bytes(os.urandom(2048))
    r = await call(tool_ctx, "copy_files", source_folder=str(pics), only_screenshots=True, destination_folder="Screenshots copies")
    assert r.verified and len(r.data["copied"]) == 2
    dest = pics / "Screenshots copies"
    assert sorted(p.name for p in dest.iterdir()) == ["Screenshot (2).png", "Screenshot 2026-10-01 101010.png"]
    assert len(list(pics.iterdir())) == 5  # originals untouched (4 files + the new folder)
    r2 = await call(tool_ctx, "copy_files", source_folder=str(pics), only_screenshots=True, destination_folder="Screenshots copies")
    assert len(r2.data["copied"]) == 2 and len(list(dest.iterdir())) == 4  # second run adds "(2)" names, never overwrites
    none = await call(tool_ctx, "copy_files", source_folder=str(pics), pattern="*.pdf", destination_folder="PDFs")
    assert none.ok and "Nothing copied" in none.summary
    with pytest.raises(ToolError):
        await call(tool_ctx, "copy_files", source_folder=str(pics), destination_folder="/tmp/outside")
    with pytest.raises(ToolError):
        REG.get("copy_files").parse_args({"source_folder": str(pics), "pattern": "../*", "destination_folder": "x"})


async def test_copy_needs_approval_by_default(tool_ctx, fake_server):
    folder = Path(tool_ctx.settings.permissions.authorized_folders[0])
    (folder / "a.txt").write_text("a")
    out, approvals = await run(tool_ctx, fake_server, [
        act("copy_files", source_folder=str(folder), pattern="*.txt", destination_folder="backup"),
    ], task="Copy my text files into a backup folder", approve=False)
    assert [a["tool"] for a in approvals] == ["copy_files"] and not (folder / "backup").exists()


# ---------- Test B logic: search → open result → save title and URL ----------
async def test_b_search_open_and_save_title_url(tool_ctx, fake_server, site):
    tool_ctx.policy = PermissionPolicy({RiskLevel.LOCAL_WRITE: Decision.ALLOW}, tool_ctx.settings.permissions.authorized_folders)
    url = site.base_url + "/articles/motion-templates"
    out, _ = await run(tool_ctx, fake_server, [
        act("web_search", query="free motion graphics templates"),
        act("open_search_result", number=1),
        act("read_page"),
        act("save_links", file_name="video editing result", links=[{"title": "Free Motion Graphics Templates 2026", "url": url}]),
        finish("Saved the title and address."),
    ], task="Search for free motion graphics templates, open a relevant result, and save the title and URL.")
    assert out.status == "completed" and all(s["outcome"] == "verified" for s in out.steps), out.summary()
    saved = (Path(tool_ctx.settings.permissions.authorized_folders[0]) / "video editing result.md").read_text()
    assert url in saved and "Free Motion Graphics Templates 2026" in saved


async def test_stop_interrupts_long_typing(desk_ctx):
    """Cancelling the task (Stop / Ctrl+Alt+X) stops typing between short bursts."""
    import asyncio

    await call(desk_ctx, "launch_app", name="Notepad")
    real = desk_ctx.fake.type_keys
    calls = []

    def slow(text):
        calls.append(text)
        import time as _t
        _t.sleep(0.05)
        real(text)

    desk_ctx.fake.type_keys = slow
    task = asyncio.create_task(call(desk_ctx, "type_text", text="x" * 4000))
    await asyncio.sleep(0.3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0.2)
    typed = len(desk_ctx.fake.windows[desk_ctx.fake.active]["controls"][0]["value"])
    assert 0 < typed < 4000 and len(calls) < 100
