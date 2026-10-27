"""A time-limited standing reply — drafted, never sent on its own.

The ask: "for the next two hours, anyone who messages me gets 'come back in
three hours'." This module is the part that can be built honestly today.

**Why it drafts and does not send.** S-CLAW has no WhatsApp connector. It reads
what the WhatsApp window shows Windows accessibility tools, and that surface has
no message identifiers (see claw/integrations/whatsapp.py) — only chat names and
unread counts. Sending unattended off a signal that weak would mean replying to
the wrong person on a mis-read, with nobody watching. The libraries that do
expose message ids are unofficial: whatsapp-web.js says in its own README that
"it is not guaranteed you will not be blocked", and Baileys' maintainers write
that they "discourage any ... automated messaging usage". Neither is worth the
person's account, and both would add a browser or a protocol stack to an
installer that currently ships no npm runtime dependencies at all.

So: authorisation is explicit and expires; eligibility is narrow; every reply is
**prepared** and queued for the person to send. Nothing here can press Send.

What it guarantees, and what each guarantee is for:

- an **expiry stored on disk**, so a restart cannot extend a window
- **groups, status updates and the person's own chats excluded**, by default
- **one reply per chat per window**, plus a cooldown, so a flapping unread
  count cannot produce a pile of drafts
- a **cap on drafts**, so a bad read cannot turn into fifty of them
- an **immediate stop**, which is just deleting the authorisation
- message text is **never stored**: only chat names and counts, as before
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

#: Longest window anyone may authorise in one go. A standing reply that outlives
#: the reason for it is how people end up telling customers to come back for a
#: week after they got back.
MAX_HOURS = 12
MAX_MESSAGE = 500
#: Per chat, within one window. The second message from the same person does not
#: need the same automatic answer.
ONE_REPLY_PER_CHAT = True
#: And not twice in quick succession even across windows.
COOLDOWN_SECONDS = 30 * 60
#: Most drafts a single window may produce.
MAX_DRAFTS = 25

#: Chats that are never eligible, however the authorisation is worded.
GROUP_HINTS = re.compile(r"\((\d+)\)|\bgroup\b|,\s*\+?\d|&\s", re.I)
STATUS_HINTS = re.compile(r"^(status|my status|status updates?|broadcast|announcements?)$", re.I)
SELF_HINTS = re.compile(r"^(you|me|message yourself|\(you\))$", re.I)


class NotAuthorised(Exception):
    """Nothing may be drafted: there is no live authorisation."""


@dataclass
class Authorisation:
    """What the person agreed to, and when it stops."""

    message: str
    expires_at: float
    created_at: float = field(default_factory=time.time)
    account_hint: str = ""        # which WhatsApp window this was granted for
    only_chats: list[str] = field(default_factory=list)   # empty = any eligible chat
    drafted: dict[str, float] = field(default_factory=dict)   # chat name -> when
    paused: bool = False

    def live(self, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        return not self.paused and now < self.expires_at

    def minutes_left(self, now: float | None = None) -> int:
        now = time.time() if now is None else now
        return max(0, int((self.expires_at - now) // 60))

    def as_dict(self) -> dict:
        d = asdict(self)
        d["live"] = self.live()
        d["minutes_left"] = self.minutes_left()
        d["drafts_made"] = len(self.drafted)
        return d


def eligible(chat_name: str, auth: Authorisation) -> tuple[bool, str]:
    """May this chat get a standing reply? Returns the reason when it may not."""
    name = (chat_name or "").strip()
    if not name:
        return False, "the chat has no readable name"
    if STATUS_HINTS.match(name):
        return False, "status updates are not a conversation"
    if SELF_HINTS.match(name):
        return False, "that is the person's own chat"
    if GROUP_HINTS.search(name):
        return False, "it looks like a group"
    if auth.only_chats and name.lower() not in {c.lower() for c in auth.only_chats}:
        return False, "it is not one of the chats you listed"
    return True, ""


@dataclass
class Draft:
    """A reply prepared for a person to look at and send."""

    chat: str
    message: str
    because: str          # what was observed, in the person's terms

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class StandingReply:
    """The authorisation on disk, and the drafting rules around it."""

    path: Path

    # ---------- the authorisation ----------
    def load(self) -> Authorisation | None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        try:
            return Authorisation(**raw)
        except TypeError:
            return None          # written by a different version: treat as none

    def save(self, auth: Authorisation) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(auth), indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    def authorise(self, message: str, hours: float, *, account_hint: str = "",
                  only_chats: list[str] | None = None, now: float | None = None) -> Authorisation:
        text = (message or "").strip()
        if not text:
            raise ValueError("say what the reply should be")
        if len(text) > MAX_MESSAGE:
            raise ValueError(f"keep the reply under {MAX_MESSAGE} characters")
        if not 0 < hours <= MAX_HOURS:
            raise ValueError(f"choose between a few minutes and {MAX_HOURS} hours")
        now = time.time() if now is None else now
        auth = Authorisation(message=text, expires_at=now + hours * 3600, created_at=now,
                             account_hint=account_hint, only_chats=list(only_chats or []))
        self.save(auth)
        return auth

    def stop(self) -> bool:
        """Immediate off switch: the authorisation simply stops existing."""
        try:
            self.path.unlink()
            return True
        except FileNotFoundError:
            return False

    def status(self, now: float | None = None) -> dict:
        auth = self.load()
        if auth is None:
            return {"authorised": False, "message": "", "minutes_left": 0, "drafts_made": 0}
        return {"authorised": auth.live(now), **auth.as_dict()}

    # ---------- drafting ----------
    def drafts_for(self, unread: list[tuple[str, int | None]], now: float | None = None) -> list[Draft]:
        """Replies to prepare for the chats that just became unread.

        `unread` is (chat name, unread count) as read from the WhatsApp window.
        Nothing here sends: the drafts go to the person.
        """
        now = time.time() if now is None else now
        auth = self.load()
        if auth is None or not auth.live(now):
            raise NotAuthorised("no standing reply is authorised right now")
        drafts: list[Draft] = []
        for name, count in unread:
            if len(auth.drafted) + len(drafts) >= MAX_DRAFTS:
                break
            ok, _why = eligible(name, auth)
            if not ok:
                continue
            last = auth.drafted.get(name)
            if last is not None and (ONE_REPLY_PER_CHAT or now - last < COOLDOWN_SECONDS):
                continue
            drafts.append(Draft(chat=name, message=auth.message,
                                because=f"{count} unread message(s)" if count else "a new message"))
        if drafts:
            for d in drafts:
                auth.drafted[d.chat] = now
            self.save(auth)
        return drafts
