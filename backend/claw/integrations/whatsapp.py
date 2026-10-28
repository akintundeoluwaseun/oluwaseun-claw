"""WhatsApp: check unread chats in the official WhatsApp Desktop app via Windows UI Automation.

Chosen with the user (Oct 2026): no unofficial WhatsApp libraries and no linked-device tricks.
Claw reads what the WhatsApp window itself shows to accessibility tools: the chat list rows and
their unread badges. It never reads message history, never stores message text, and shows short
previews only when the user turns previews on.

Honesty rules:
- If WhatsApp isn't installed or open, or isn't linked to a phone, Claw says so.
- If it can't recognise the chat list (WhatsApp changed its layout), it says "couldn't read",
  never "no unread messages".
- Only chats visible in the list are checked, and the result says how many were checked.

NOT YET RUN AGAINST THE REAL APP: the accessible names matched below ("3 unread messages",
"Unread", the QR-code linking screen) are best guesses from WhatsApp Desktop's English interface
and must be confirmed on Windows (docs/WINDOWS_ACCEPTANCE.md, Test C). Parsing is tolerant and is
tested here only against labelled sample control lists.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from claw.computer.driver import ControlInfo, DesktopDriver, WindowInfo

WHATSAPP_PROCESSES = {"whatsapp.exe", "whatsapp.root.exe"}
LAUNCH_URI = "whatsapp:"  # registered by WhatsApp Desktop (Microsoft Store and installer versions)
ROW_ROLES = {"ListItem", "DataItem", "TreeItem"}
CONTROL_LIMIT = 800

UNREAD_N = re.compile(r"(\d{1,4})\s+unread\s+messages?", re.I)
UNREAD_MARK = re.compile(r"\b(marked as )?unread\b", re.I)
NOT_LINKED = re.compile(r"scan (the |this )?qr code|link with phone number|log in with phone|to use whatsapp on your computer|link a device", re.I)
LOADING = re.compile(r"loading (your )?chats|syncing|connecting|end-to-end encrypted.*loading", re.I)
TIME_LIKE = re.compile(r"^(\d{1,2}:\d{2}(\s?[ap]m)?|yesterday|today|monday|tuesday|wednesday|thursday|friday|saturday|sunday|\d{1,2}/\d{1,2}/\d{2,4})$", re.I)


@dataclass
class UnreadChat:
    name: str
    unread: int | None  # None = marked unread without a count
    preview: str = ""
    new_since_last_check: bool = False


@dataclass
class WhatsAppCheck:
    state: str  # ok | not_installed | not_open | not_linked | loading | unreadable | unavailable
    message: str
    chats_checked: int = 0
    unread: list[UnreadChat] = field(default_factory=list)
    checked_at: float = field(default_factory=time.time)
    previews_shown: bool = False
    #: The title of the window this was read from. The person has to be able to
    #: see which WhatsApp a standing reply would answer for.
    window_title: str = ""

    def as_dict(self) -> dict:
        d = asdict(self)
        d["new_count"] = sum(1 for c in self.unread if c.new_since_last_check)
        return d

    def summary(self) -> str:
        if self.state != "ok":
            return self.message
        if not self.unread:
            return f"No unread chats among the {self.chats_checked} chat(s) shown in WhatsApp."
        names = ", ".join(f"{c.name} ({c.unread})" if c.unread else f"{c.name} (marked unread)" for c in self.unread[:10])
        new = [c.name for c in self.unread if c.new_since_last_check]
        extra = f" New since the last check: {', '.join(new[:10])}." if new else ""
        return f"{len(self.unread)} chat(s) with unread messages: {names}.{extra}"


def find_window(windows: list[WindowInfo]) -> WindowInfo | None:
    by_process = [w for w in windows if w.process.lower() in WHATSAPP_PROCESSES]
    if by_process:
        return by_process[0]
    by_title = [w for w in windows if w.title.strip().lower() == "whatsapp" or w.title.strip().lower().startswith("whatsapp -")]
    return by_title[0] if by_title else None


def _chat_name(row: ControlInfo, children: list[ControlInfo]) -> str:
    texts = [c.name for c in children if c.role in ("Text", "Edit") and c.name and not TIME_LIKE.match(c.name.strip())
             and not UNREAD_N.search(c.name) and not UNREAD_MARK.fullmatch(c.name.strip())]
    if texts:
        return texts[0].strip()
    # Row names usually read "Name, …details…".
    first = re.split(r",\s+|\n", row.name, maxsplit=1)[0]
    return UNREAD_N.sub("", first).strip(" ,")


def parse_chat_list(controls: list[ControlInfo], with_previews: bool) -> tuple[str, int, list[UnreadChat]]:
    """(state, chats_checked, unread chats) from a flat list of the window's controls."""
    names = " ".join(c.name for c in controls)
    if NOT_LINKED.search(names):
        return "not_linked", 0, []
    rows: list[tuple[ControlInfo, list[ControlInfo]]] = []
    for c in controls:
        if c.role in ROW_ROLES:
            rows.append((c, []))
        elif rows:
            rows[-1][1].append(c)
    rows = [(r, kids) for r, kids in rows if (r.name or kids)]
    if not rows:
        return ("loading" if LOADING.search(names) else "unreadable"), 0, []
    unread: list[UnreadChat] = []
    for row, kids in rows:
        blob = " ".join([row.name] + [k.name for k in kids])
        m = UNREAD_N.search(blob)
        count = int(m.group(1)) if m else None
        marked = count is None and any(UNREAD_MARK.fullmatch(k.name.strip()) for k in kids if k.name)
        if count is None and not marked:
            continue
        name = _chat_name(row, kids)
        if not name:
            continue
        preview = ""
        if with_previews:
            others = [k.name.strip() for k in kids if k.role == "Text" and k.name and k.name.strip() != name
                      and not TIME_LIKE.match(k.name.strip()) and not UNREAD_N.search(k.name) and not UNREAD_MARK.fullmatch(k.name.strip())]
            preview = (others[-1] if others else "")[:60]
        unread.append(UnreadChat(name=name[:80], unread=count, preview=preview))
    return "ok", len(rows), unread


class CheckStore:
    """Remembers the last check (chat names and unread counts only — never message text)."""

    def __init__(self, data_dir: Path):
        self.path = data_dir / "whatsapp-last-check.json"

    def load(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def save(self, check: WhatsAppCheck) -> None:
        if check.state != "ok":
            prev = self.load()
            prev.update(last_attempt=check.checked_at, last_state=check.state)
            data = prev
        else:
            data = {"checked_at": check.checked_at, "last_attempt": check.checked_at, "last_state": "ok",
                    "counts": {c.name: c.unread if c.unread is not None else -1 for c in check.unread}}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data), encoding="utf-8")

    def mark_new(self, check: WhatsAppCheck) -> None:
        """A chat is 'new since the last check' if it wasn't unread then, or its count went up.
        (WhatsApp shows no message IDs to accessibility tools, so counts are the reliable signal.)"""
        prev = self.load().get("counts")
        if prev is None:
            return  # first check: nothing to compare with, so nothing is called "new"
        for c in check.unread:
            before = prev.get(c.name)
            now = c.unread if c.unread is not None else -1
            c.new_since_last_check = before is None or (now > before >= 0)


async def check_whatsapp(call, driver: DesktopDriver, store: CheckStore, *, with_previews: bool, open_if_needed: bool) -> WhatsAppCheck:
    """`call` runs a driver method on the desktop thread (DesktopSession.call)."""
    ok, why = await call(driver.available)
    if not ok:
        return WhatsAppCheck("unavailable", why)
    win = find_window(await call(driver.list_windows))
    if win is None and open_if_needed:
        try:
            await call(driver.launch, LAUNCH_URI)
        except Exception:  # noqa: BLE001 — the protocol isn't registered: WhatsApp isn't installed
            return WhatsAppCheck("not_installed", "WhatsApp Desktop doesn't seem to be installed. Install it from the Microsoft Store and link it to your phone.")
        for _ in range(40):
            await asyncio.sleep(0.5)
            win = find_window(await call(driver.list_windows))
            if win:
                await asyncio.sleep(2)  # let the chat list appear
                break
    if win is None:
        return WhatsAppCheck("not_open" if not open_if_needed else "not_installed",
                             "WhatsApp isn't open." if not open_if_needed else "WhatsApp didn't open within 20 seconds.")
    controls = await call(driver.controls, win.handle, CONTROL_LIMIT)
    state, checked, unread = parse_chat_list(controls, with_previews)
    messages = {
        "not_linked": "WhatsApp is open but not linked to your phone. Link it (scan the QR code), then check again.",
        "loading": "WhatsApp is still loading your chats. Try again in a moment.",
        "unreadable": "Claw couldn't read WhatsApp's chat list (the window may be minimised, or WhatsApp changed its layout). "
                      "Nothing is assumed about unread messages.",
    }
    check = WhatsAppCheck(state, messages.get(state, ""), checked, unread, previews_shown=with_previews,
                          window_title=(win.title or "").strip() if win else "")
    if state == "ok":
        store.mark_new(check)
        check.message = check.summary()
    store.save(check)
    return check
