"""Messaging tools: check WhatsApp unread chats (a private-data permission) and send a message
(always needs the user's OK, like deleting or buying)."""

from __future__ import annotations

import asyncio
import re

from pydantic import Field

from claw.agent.schemas import Capability
from claw.integrations.whatsapp import CONTROL_LIMIT, CheckStore, _chat_name, check_whatsapp, find_window
from claw.permissions.policy import RiskLevel
from claw.tools.base import NoArgs, ToolArgs, ToolContext, ToolError, ToolRegistry, ToolResult, ToolSpec


def _session(ctx: ToolContext):
    if ctx.desktop is None:
        raise ToolError("Desktop control is not available in this session.")
    return ctx.desktop


async def check_whatsapp_tool(args: NoArgs, ctx: ToolContext) -> ToolResult:
    s = _session(ctx)
    result = await check_whatsapp(s.call, s.driver, CheckStore(ctx.data_dir),
                                  with_previews=ctx.settings.messages.show_previews, open_if_needed=True)
    ok = result.state == "ok"
    text = "\n".join(f"- {c.name}: {c.unread if c.unread is not None else 'marked'} unread"
                     + (" (new)" if c.new_since_last_check else "") + (f" — \"{c.preview}\"" if c.preview else "")
                     for c in result.unread)
    return ToolResult(ok, result.message, result.as_dict(), verified=ok, untrusted_text=text)


class SendArgs(ToolArgs):
    chat: str = Field(min_length=1, max_length=80, description="Exact chat or contact name as shown in WhatsApp")
    text: str = Field(min_length=1, max_length=2000)


async def send_whatsapp_message(args: SendArgs, ctx: ToolContext) -> ToolResult:
    """Runs only after the user approved this exact recipient and text."""
    s = _session(ctx)
    d = s.driver
    ok, why = await s.call(d.available)
    if not ok:
        raise ToolError(why)
    win = find_window(await s.call(d.list_windows))
    if win is None:
        raise ToolError("WhatsApp isn't open. Open it (or check WhatsApp first), then try again.")
    await s.call(d.focus_window, win.handle)

    def find(controls, pred):
        return [c for c in controls if pred(c)]

    controls = await s.call(d.controls, win.handle, CONTROL_LIMIT)
    search = find(controls, lambda c: c.role == "Edit" and re.search(r"search", c.name, re.I))
    if not search:
        raise ToolError("Couldn't find WhatsApp's search box, so nothing was sent.")
    await s.call(d.set_text, search[0].index, args.chat)
    await asyncio.sleep(1.5)
    controls = await s.call(d.controls, win.handle, CONTROL_LIMIT)
    rows, current = [], None
    for c in controls:
        if c.role in ("ListItem", "DataItem", "TreeItem"):
            current = [c, []]
            rows.append(current)
        elif current:
            current[1].append(c)
    matches = [r for r, kids in rows if _chat_name(r, kids).lower() == args.chat.strip().lower()]
    if not matches:
        raise ToolError(f"No chat named exactly '{args.chat}' was found, so nothing was sent.")
    if len(matches) > 1:
        raise ToolError(f"{len(matches)} chats are named '{args.chat}'. Nothing was sent; please send it yourself.")
    await s.call(d.invoke, matches[0].index)
    await asyncio.sleep(1.0)
    controls = await s.call(d.controls, win.handle, CONTROL_LIMIT)
    boxes = find(controls, lambda c: c.role in ("Edit", "Document") and re.search(r"type a message|message", c.name, re.I)
                 and not re.search(r"search", c.name, re.I))
    if not boxes:
        raise ToolError("Couldn't find the message box in that chat, so nothing was sent.")
    await s.call(d.set_text, boxes[0].index, args.text)
    typed = await s.call(d.read, boxes[0].index)
    if " ".join(args.text.split())[:60] not in " ".join(typed.split()):
        raise ToolError("The message didn't appear in the message box correctly, so it was not sent.")
    await s.call(d.send_keys, ["enter"])
    await asyncio.sleep(1.5)
    after = await s.call(d.controls, win.handle, CONTROL_LIMIT)
    box_after = find(after, lambda c: c.role in ("Edit", "Document") and re.search(r"type a message|message", c.name, re.I)
                     and not re.search(r"search", c.name, re.I))
    cleared = bool(box_after) and not box_after[0].value.strip()
    shown = any(args.text.strip()[:40] in (c.name + " " + c.value) for c in after if c.role not in ("Edit", "Document"))
    ok = cleared and shown
    return ToolResult(True, f"Sent the message to {args.chat}" + (" and saw it in the chat." if ok else ", but couldn't confirm it appeared in the chat. Check WhatsApp."),
                      {"chat": args.chat, "confirmed": ok}, verified=ok)


def register_message_tools(reg: ToolRegistry) -> None:
    D = Capability.DESKTOP
    reg.register(ToolSpec("check_whatsapp",
                          "Check the WhatsApp Desktop app for chats with unread messages (names and counts; opens WhatsApp if needed).",
                          D, RiskLevel.READ_ONLY, NoArgs, check_whatsapp_tool, sensitive_scope="messages_read"))
    reg.register(ToolSpec("send_whatsapp_message",
                          "Send a WhatsApp message to one existing chat. Always asks the user first.",
                          D, RiskLevel.DESTRUCTIVE, SendArgs, send_whatsapp_message))
