"""Driving the whole laptop, which is what makes the rest unnecessary.

S-CLAW does not integrate with Telegram, Instagram or a mail provider. It opens
the app or the site and works it the way a person would. These tests cover the
three things that makes or breaks:

  - Enter must count as sending inside a browser, not only in a desktop app.
  - An app with no Start-menu shortcut must still be reachable if it is open.
  - A drafted mail must never be a sent mail.
"""

import pytest

from claw.permissions.policy import RiskLevel
from claw.tools import desktop_tools as dt
from claw.tools.base import ToolError
from claw.tools.mail_tools import MailArgs, compose_url
from claw.tools.registry import build_registry

REG = build_registry()


async def call(ctx, tool, **args):
    spec = REG.get(tool)
    parsed = spec.parse_args(args)
    if spec.precheck:
        spec.precheck(parsed, ctx)
    return await spec.handler(parsed, ctx)


def risk_of(name, ctx, **args):
    spec = REG.get(name)
    parsed = spec.parse_args(args)
    return spec.risk_for(parsed, ctx) if hasattr(spec, "risk_for") else spec.risk


# ---------- Enter sends, wherever you are ----------
def test_enter_in_a_messaging_app_is_destructive(desk_ctx):
    desk_ctx.desktop.last_process = "telegram.exe"
    desk_ctx.desktop.last_title = "Telegram"
    assert dt.keys_risk(REG.get("press_keys").parse_args({"keys": ["enter"]}), desk_ctx) is RiskLevel.DESTRUCTIVE


@pytest.mark.parametrize("title", [
    "(2) John • Instagram — Google Chrome",
    "WhatsApp — Google Chrome",
    "Telegram Web — Google Chrome",
    "Inbox (12) - me@example.com - Gmail — Google Chrome",
    "Mail - Outlook — Microsoft Edge",
    "Messages | LinkedIn — Google Chrome",
])
def test_enter_on_a_messaging_site_in_a_browser_is_destructive(desk_ctx, title):
    """The process is only ever the browser; the site is in the title."""
    desk_ctx.desktop.last_process = "chrome.exe"
    desk_ctx.desktop.last_title = title
    risk = dt.keys_risk(REG.get("press_keys").parse_args({"keys": ["enter"]}), desk_ctx)
    assert risk is RiskLevel.DESTRUCTIVE, f"Enter would have sent without asking on: {title}"


def test_enter_on_an_ordinary_page_is_not_treated_as_sending(desk_ctx):
    desk_ctx.desktop.last_process = "chrome.exe"
    desk_ctx.desktop.last_title = "Python Documentation — Google Chrome"
    assert dt.keys_risk(REG.get("press_keys").parse_args({"keys": ["enter"]}), desk_ctx) is RiskLevel.LOCAL_WRITE


def test_typing_a_newline_on_a_messaging_site_is_destructive_too(desk_ctx):
    desk_ctx.desktop.last_process = "msedge.exe"
    desk_ctx.desktop.last_title = "WhatsApp"
    # An interior newline is how a typed message would send one line and start
    # another, which on these sites sends it.
    args = REG.get("type_text").parse_args({"text": "Running late\nsee you at 2"})
    assert dt.typing_risk(args, desk_ctx) is RiskLevel.DESTRUCTIVE


def test_a_trailing_newline_cannot_reach_the_typing_rule_at_all(desk_ctx):
    """Worth pinning down: tool arguments arrive with whitespace stripped.

    So type_text can never carry a trailing newline, and the only way to send on
    these sites is press_keys(enter) - which is covered above. If argument
    stripping ever changes, this test fails and the rule needs revisiting.
    """
    assert REG.get("type_text").parse_args({"text": "Running late\n"}).text == "Running late"


async def test_the_title_is_remembered_when_claw_switches_window(desk_ctx):
    await call(desk_ctx, "launch_app", name="Notepad")
    assert desk_ctx.desktop.last_title, "the window title must be kept for the sending rules"


# ---------- apps with no Start-menu shortcut ----------
async def test_an_app_with_no_shortcut_is_found_if_it_is_already_open(desk_ctx):
    """Store apps and anything pinned to the taskbar have no .lnk to find."""
    fake = desk_ctx.fake
    handle = fake.next_handle
    fake.next_handle += 1
    fake.windows[handle] = {"title": "Telegram (3)", "process": "telegram.exe", "controls": []}

    r = await call(desk_ctx, "launch_app", name="Telegram")
    assert r.data["was_running"] is True
    assert "already open" in r.summary
    assert desk_ctx.fake.active == handle
    assert desk_ctx.launched_nothing if hasattr(desk_ctx, "launched_nothing") else True
    assert fake.launched == [], "it should switch to the open window, not start a second copy"


async def test_an_app_that_is_neither_installed_nor_open_is_still_refused(desk_ctx):
    with pytest.raises(ToolError, match="No installed app|No app clearly matches"):
        await call(desk_ctx, "launch_app", name="Photoshop")


async def test_a_system_tool_is_still_refused_even_if_a_window_is_open(desk_ctx):
    fake = desk_ctx.fake
    handle = fake.next_handle
    fake.next_handle += 1
    fake.windows[handle] = {"title": "Command Prompt", "process": "cmd.exe", "controls": []}
    with pytest.raises(ToolError, match="system tools"):
        await call(desk_ctx, "launch_app", name="Command Prompt")


# ---------- mail is a draft, never a send ----------
def test_a_gmail_draft_carries_everything_and_sends_nothing():
    url = compose_url(MailArgs(to=["john@example.com"], subject="Running late",
                               body="On my way — about 10 minutes.", service="gmail"))
    assert url.startswith("https://mail.google.com/mail/?view=cm&fs=1&")
    assert "to=john%40example.com" in url
    assert "su=Running%20late" in url
    assert "body=On%20my%20way" in url


def test_an_outlook_draft_uses_outlooks_own_field_names():
    url = compose_url(MailArgs(to=["a@example.com"], cc=["b@example.com"],
                               subject="Hello", body="Hi", service="outlook"))
    assert url.startswith("https://outlook.office.com/mail/deeplink/compose?")
    assert "subject=Hello" in url and "cc=b%40example.com" in url


def test_the_default_mail_program_gets_a_mailto():
    url = compose_url(MailArgs(to=["a@example.com", "b@example.com"], subject="Hi", service="default"))
    assert url.startswith("mailto:a@example.com,b@example.com?")
    assert "subject=Hi" in url


def test_an_address_that_is_not_an_address_is_refused():
    for bad in ("john", "john@", "@example.com", "john at example.com"):
        with pytest.raises(Exception, match="not an e-mail address"):
            MailArgs(to=[bad])


def test_a_subject_cannot_smuggle_in_a_second_line():
    with pytest.raises(Exception, match="one line"):
        MailArgs(to=["a@example.com"], subject="Hello\nBcc: someone@else.com")


async def test_composing_opens_the_page_and_says_nothing_was_sent(tool_ctx, site):
    """Opened for real, against a local page standing in for the mail service."""
    import claw.tools.mail_tools as mail

    mail.SERVICES = {**mail.SERVICES, "gmail": site.base_url + "/articles/cooking?{params}"}
    r = await call(tool_ctx, "compose_mail", to=["john@example.com"], subject="Hi", body="Hello")
    assert r.data["sent"] is False
    assert "Nothing has been sent" in r.summary
    assert r.data["to"] == ["john@example.com"]


def test_compose_is_external_so_it_needs_the_usual_permission():
    assert REG.get("compose_mail").risk is RiskLevel.EXTERNAL


# ---------- what the person is actually approving ----------
def test_the_approval_for_enter_names_the_chat_and_quotes_the_message(desk_ctx):
    """'press_keys: ["enter"]' is true and tells the person nothing.

    The window title and the text already typed are the two facts that decide
    whether this approval is safe, and neither is in the arguments.
    """
    desk_ctx.desktop.last_process = "telegram.exe"
    desk_ctx.desktop.last_title = "John Doe - Telegram"
    desk_ctx.desktop.last_typed = "Running late, see you at 2"
    spec = REG.get("press_keys")
    said = spec.approval_context(spec.parse_args({"keys": ["enter"]}), desk_ctx)
    assert "John Doe" in said
    assert "telegram.exe" in said
    assert "Running late, see you at 2" in said


def test_the_unread_count_is_not_mistaken_for_the_contact(desk_ctx):
    desk_ctx.desktop.last_process = "chrome.exe"
    desk_ctx.desktop.last_title = "(2) John • Instagram — Google Chrome"
    desk_ctx.desktop.last_typed = "hi"
    spec = REG.get("press_keys")
    said = spec.approval_context(spec.parse_args({"keys": ["enter"]}), desk_ctx)
    assert "John" in said and "(2)" not in said


def test_type_text_quotes_the_text_it_is_about_to_type_not_the_last_one(desk_ctx):
    """The card is shown before the handler runs, so last_typed is still stale."""
    desk_ctx.desktop.last_process = "whatsapp.exe"
    desk_ctx.desktop.last_title = "WhatsApp"
    desk_ctx.desktop.last_typed = "an older message"
    spec = REG.get("type_text")
    said = spec.approval_context(spec.parse_args({"text": "the new one\nsent now"}), desk_ctx)
    assert "the new one sent now" in said
    assert "older" not in said


def test_no_context_is_added_where_enter_does_not_send(desk_ctx):
    desk_ctx.desktop.last_process = "notepad.exe"
    desk_ctx.desktop.last_title = "Untitled - Notepad"
    spec = REG.get("press_keys")
    assert spec.approval_context(spec.parse_args({"keys": ["enter"]}), desk_ctx) == ""


def test_a_send_with_nothing_typed_says_so_rather_than_quoting_nothing(desk_ctx):
    desk_ctx.desktop.last_process = "telegram.exe"
    desk_ctx.desktop.last_title = "Jane - Telegram"
    desk_ctx.desktop.last_typed = ""
    spec = REG.get("press_keys")
    said = spec.approval_context(spec.parse_args({"keys": ["enter"]}), desk_ctx)
    assert "Jane" in said and "check on screen" in said


def test_an_explanation_that_raises_never_blocks_the_approval():
    """A missing sentence costs clarity; an exception would cost the approval."""
    spec = REG.get("press_keys")
    assert spec.approval_context(spec.parse_args({"keys": ["enter"]}), None) == ""
