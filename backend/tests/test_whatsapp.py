"""Phase B — WhatsApp unread check and sending, against the TEST DOUBLE desktop.

The stand-in imitates WhatsApp Desktop's accessible layout as a GUESS; the real app has not been
checked (Test C is BLOCKED here — docs/WINDOWS_ACCEPTANCE.md). Permissions, honesty rules,
"new since last check" and the send safeguards are tested for real.
"""

import json

import pytest

from claw.computer.driver import ControlInfo
from claw.integrations.whatsapp import CheckStore, parse_chat_list
from claw.permissions.policy import Decision, PermissionPolicy, RiskLevel
from tests.test_desktop import act, call
from tests.test_phase_a import finish, run

CHATS = [("Mum", 2, "Call me when you're free"), ("Shop staff", None, "Okay"), ("Tunde", "marked", "See you"),
         ("Akure IPE class", 15, "Lecture moved to 10am")]


def ci(i, role, name, value=""):
    return ControlInfo(index=i, role=role, name=name, value=value)


# ---------- parser ----------
def test_parser_counts_marked_and_previews():
    controls = [ci(0, "Edit", "Search or start a new chat"),
                ci(1, "ListItem", "Mum, 2 unread messages"), ci(2, "Text", "Mum"), ci(3, "Text", "10:42"), ci(4, "Text", "Call me"),
                ci(5, "Text", "2 unread messages"),
                ci(6, "ListItem", "Shop staff"), ci(7, "Text", "Shop staff"), ci(8, "Text", "Yesterday"), ci(9, "Text", "Okay"),
                ci(10, "ListItem", "Tunde"), ci(11, "Text", "Tunde"), ci(12, "Text", "Unread")]
    state, checked, unread = parse_chat_list(controls, with_previews=False)
    assert state == "ok" and checked == 3
    assert [(c.name, c.unread, c.preview) for c in unread] == [("Mum", 2, ""), ("Tunde", None, "")]
    _, _, with_prev = parse_chat_list(controls, with_previews=True)
    assert with_prev[0].preview == "Call me"


def test_parser_never_says_none_when_it_cannot_read():
    assert parse_chat_list([ci(0, "Text", "Scan the QR code with your phone")], False)[0] == "not_linked"
    assert parse_chat_list([ci(0, "Button", "Settings"), ci(1, "Pane", "")], False)[0] == "unreadable"
    assert parse_chat_list([ci(0, "Text", "Loading your chats")], False)[0] == "loading"


# ---------- checks through the tool ----------
async def test_check_lists_unread_chats_and_new_since_last(desk_ctx):
    fake = desk_ctx.fake
    fake.add_whatsapp(CHATS)
    r = await call(desk_ctx, "check_whatsapp")
    assert r.ok and r.verified and r.data["chats_checked"] == 4
    assert [(c["name"], c["unread"]) for c in r.data["unread"]] == [("Mum", 2), ("Tunde", None), ("Akure IPE class", 15)]
    assert r.data["new_count"] == 0  # first check: nothing to compare with
    assert "Call me" not in r.untrusted_text  # previews are off by default
    # More messages arrive in one chat, a new chat becomes unread, one is read on the phone
    fake._wa_chats = [("Mum", 2, "x"), ("Shop staff", 1, "Price?"), ("Tunde", None, "See you"), ("Akure IPE class", 18, "y")]
    fake.windows[fake._wa_handle]["controls"] = fake._wa_controls()
    r2 = await call(desk_ctx, "check_whatsapp")
    new = {c["name"] for c in r2.data["unread"] if c["new_since_last_check"]}
    assert new == {"Shop staff", "Akure IPE class"} and "New since the last check" in r2.summary
    stored = json.loads((desk_ctx.data_dir / "whatsapp-last-check.json").read_text())
    assert "Price?" not in json.dumps(stored)  # message text is never stored


async def test_previews_only_when_turned_on(desk_ctx):
    desk_ctx.fake.add_whatsapp(CHATS)
    desk_ctx.settings.messages.show_previews = True
    r = await call(desk_ctx, "check_whatsapp")
    assert '"Lecture moved to 10am"' in r.untrusted_text


async def test_opens_whatsapp_or_explains(desk_ctx):
    r = await call(desk_ctx, "check_whatsapp")
    assert not r.ok and r.data["state"] == "not_installed" and "Microsoft Store" in r.summary
    desk_ctx.fake.add_whatsapp(CHATS, open_now=False)
    r = await call(desk_ctx, "check_whatsapp")
    assert r.ok and "whatsapp:" in desk_ctx.fake.launched


async def test_not_linked_is_reported(desk_ctx):
    desk_ctx.fake.add_whatsapp(CHATS, linked=False)
    r = await call(desk_ctx, "check_whatsapp")
    assert not r.ok and r.data["state"] == "not_linked" and "scan the QR code" in r.summary
    stored = json.loads((desk_ctx.data_dir / "whatsapp-last-check.json").read_text())
    assert stored["last_state"] == "not_linked" and "counts" not in stored


async def test_locked_screen_is_reported(desk_ctx):
    desk_ctx.fake.add_whatsapp(CHATS)
    desk_ctx.fake.locked = True
    r = await call(desk_ctx, "check_whatsapp")
    assert not r.ok and r.data["state"] == "unavailable" and "locked" in r.summary


# ---------- permissions ----------
async def test_reading_messages_asks_by_default_and_never_when_denied(desk_ctx, fake_server):
    desk_ctx.fake.add_whatsapp(CHATS)
    out, approvals = await run(desk_ctx, fake_server, [act("check_whatsapp"), finish("Done.")],
                               task="Open WhatsApp and tell me which chats have new messages")
    assert [a["tool"] for a in approvals] == ["check_whatsapp"] and approvals[0]["sensitive_scope"] == "messages_read"
    assert out.steps[0]["outcome"] == "verified"
    desk_ctx.settings.messages.whatsapp_read = "deny"
    out, approvals = await run(desk_ctx, fake_server, [act("check_whatsapp")], task="Check WhatsApp")  # stops: no finish needed
    assert approvals == [] and out.steps[0]["outcome"] == "denied"
    desk_ctx.settings.messages.whatsapp_read = "allow"
    out, approvals = await run(desk_ctx, fake_server, [act("check_whatsapp"), finish("Done.")], task="Check WhatsApp")
    assert approvals == [] and out.steps[0]["outcome"] == "verified"


# ---------- sending ----------
async def test_send_always_asks_then_verifies(desk_ctx, fake_server):
    desk_ctx.policy = PermissionPolicy({RiskLevel.LOCAL_WRITE: Decision.ALLOW, RiskLevel.EXTERNAL: Decision.ALLOW}, [])
    desk_ctx.fake.add_whatsapp(CHATS)
    out, approvals = await run(desk_ctx, fake_server, [act("send_whatsapp_message", chat="Mum", text="I'll call you at 6")],
                               task="Tell Mum on WhatsApp I'll call at 6", approve=False)
    assert approvals[0]["risk"] == "destructive" and desk_ctx.fake.sent_messages == []
    out, approvals = await run(desk_ctx, fake_server, [act("send_whatsapp_message", chat="Mum", text="I'll call you at 6"), finish("Sent.")],
                               task="Tell Mum on WhatsApp I'll call at 6")
    assert desk_ctx.fake.sent_messages == [("Mum", "I'll call you at 6")]
    assert out.steps[0]["outcome"] == "verified"


async def test_send_refuses_unknown_or_partial_names(desk_ctx):
    from claw.tools.base import ToolError

    desk_ctx.fake.add_whatsapp(CHATS)
    with pytest.raises(ToolError, match="No chat named exactly"):
        await call(desk_ctx, "send_whatsapp_message", chat="Mu", text="hi")  # "Mu" matches Mum in search, but not exactly
    assert desk_ctx.fake.sent_messages == []


async def test_enter_in_a_messaging_app_counts_as_sending(desk_ctx):
    desk_ctx.fake.add_whatsapp(CHATS)
    await call(desk_ctx, "look_at_window", title="WhatsApp")
    keys = __import__("claw.tools.registry", fromlist=["x"]).build_registry().get("press_keys")
    assert keys.effective_risk(keys.parse_args({"keys": ["enter"]}), desk_ctx) == RiskLevel.DESTRUCTIVE
    typing = __import__("claw.tools.registry", fromlist=["x"]).build_registry().get("type_text")
    assert typing.effective_risk(typing.parse_args({"text": "hello\nthere"}), desk_ctx) == RiskLevel.DESTRUCTIVE
    assert typing.effective_risk(typing.parse_args({"text": "hello"}), desk_ctx) == RiskLevel.LOCAL_WRITE
    await call(desk_ctx, "launch_app", name="Notepad")
    assert keys.effective_risk(keys.parse_args({"keys": ["enter"]}), desk_ctx) == RiskLevel.LOCAL_WRITE


def test_check_store_first_check_marks_nothing_new(tmp_path):
    from claw.integrations.whatsapp import UnreadChat, WhatsAppCheck

    store = CheckStore(tmp_path)
    c = WhatsAppCheck("ok", "", 1, [UnreadChat("A", 3)])
    store.mark_new(c)
    assert not c.unread[0].new_since_last_check


def test_check_now_route_and_status(make_client):
    from claw.computer.driver import DesktopSession
    from tests.fake_desktop import FakeDesktop

    c = make_client()
    fake = FakeDesktop()
    fake.add_whatsapp(CHATS)
    c.app.state.claw.desktop = DesktopSession(fake)
    assert c.get("/messages/whatsapp").json()["seq"] == 0
    r = c.post("/messages/whatsapp/check")
    assert r.status_code == 200 and r.json()["state"] == "ok" and r.json()["manual"] is True
    status = c.get("/messages/whatsapp").json()
    assert status["seq"] == 1 and status["result"]["chats_checked"] == 4 and status["last_check_at"]
    s = c.get("/settings").json()["settings"]
    s["messages"]["whatsapp_read"] = "deny"
    assert c.put("/settings", json=s).status_code == 200
    assert c.post("/messages/whatsapp/check").status_code == 403
