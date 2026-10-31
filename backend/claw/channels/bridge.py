"""Your phone as a remote for S-CLAW - OpenClaw's main idea, done the S-CLAW way.

You message the bot from your phone; Claw runs the task on this computer in a chat of
its own, tells you it started, asks you on the phone before anything that needs your
OK (Allow / Don't allow buttons, or reply yes / no), and sends the result back.

Only one phone can give orders: the one paired with a six-digit code shown in Settings.
Messages from anyone else are refused and never reach the brain. Everything that asks
for approval on the computer still asks - from the phone instead - and the brain still
cannot do what the permission settings forbid.
"""

from __future__ import annotations

import asyncio
import logging
import re
import secrets
import time
from typing import Any

from claw.agent.runner import TaskBusy
from claw.channels.telegram import TelegramClient, TelegramError

log = logging.getLogger("claw.phone")
ACTIVE = {"created", "planning", "running", "awaiting_approval"}
PAIR_SECONDS = 600


class PhoneBridge:
    def __init__(self, state, client: TelegramClient):
        self.state = state
        self.client = client
        self.offset = 0
        self.thread: str | None = None          # the phone's current chat
        self.code: str | None = None
        self.code_until = 0.0
        self.status = "starting"
        self.bot_name = ""
        self._asked: set[str] = set()

    # ---------- pairing ----------
    def new_code(self) -> str:
        self.code = f"{secrets.randbelow(10**6):06d}"
        self.code_until = time.time() + PAIR_SECONDS
        return self.code

    @property
    def paired(self) -> int | None:
        return self.state.settings.phone.paired_chat_id

    def _pair(self, chat_id: int) -> None:
        s = self.state.settings
        s.phone.paired_chat_id = chat_id
        self.state.store.save(s)
        self.code = None

    # ---------- loop ----------
    async def run(self) -> None:
        try:
            self.bot_name = (await self.client.me()).get("username", "")
            self.status = "ready"
        except TelegramError as exc:
            self.status = f"error: {exc}"
            return
        while True:
            try:
                for upd in await self.client.updates(self.offset):
                    self.offset = max(self.offset, upd["update_id"] + 1)
                    await self.handle(upd)
                self.status = "ready"
            except asyncio.CancelledError:
                raise
            except TelegramError as exc:
                self.status = f"error: {exc}"
                await asyncio.sleep(10)
            except Exception:  # noqa: BLE001 - the remote must never take the app down
                log.exception("phone bridge step failed")
                await asyncio.sleep(5)

    async def handle(self, upd: dict) -> None:
        if "callback_query" in upd:
            cq = upd["callback_query"]
            chat = cq.get("message", {}).get("chat", {}).get("id")
            if chat != self.paired:
                await self.client.answered(cq["id"], "This Claw is private.")
                return
            m = re.fullmatch(r"ap:([0-9a-f]{32}):([01])", cq.get("data", ""))
            if m:
                ok = self.state.runner.answer(m.group(1), m.group(2) == "1")
                await self.client.answered(cq["id"], ("Allowed" if m.group(2) == "1" else "Not allowed") if ok else "Already answered")
            return
        msg = upd.get("message") or {}
        chat, text = msg.get("chat", {}).get("id"), (msg.get("text") or "").strip()
        voice = msg.get("voice") or msg.get("audio")
        if chat and voice and chat == self.paired:
            text = await self.hear(chat, voice)
        if not chat or not text:
            return
        if self.paired is None:
            code = re.sub(r"^/start\s*", "", text)
            if self.code and time.time() < self.code_until and secrets.compare_digest(code, self.code):
                self._pair(chat)
                await self.client.send(chat, "Paired. This phone can now give S-CLAW tasks. Send /new to start a fresh chat.")
            else:
                await self.client.send(chat, "Send the six-digit code shown in S-CLAW (Settings, Phone) to pair this phone.")
            return
        if chat != self.paired:
            await self.client.send(chat, "This Claw is private.")
            return
        await self.command(chat, text)

    async def hear(self, chat: int, voice: dict) -> str:
        """A voice note from the paired phone, turned into words on this computer (nothing is uploaded)."""
        from claw.speech.decode import to_wav16k

        try:
            raw = await self.client.download(voice["file_id"])
            wav = await asyncio.get_running_loop().run_in_executor(None, to_wav16k, raw)
            heard = await self.state.speech.transcribe(wav, self.state.settings)
        except Exception as exc:  # noqa: BLE001 - say what went wrong, never crash the remote
            msg = getattr(exc, "message", None) or str(exc) or exc.__class__.__name__
            hint = getattr(exc, "hint", "")
            await self.client.send(chat, f"I couldn't understand the voice note: {msg} {hint}".strip())
            return ""
        words = heard.text.strip()
        if not words:
            await self.client.send(chat, "I couldn't hear any words in that voice note.")
            return ""
        await self.client.send(chat, f"Heard: \u201c{words}\u201d")
        return words

    async def command(self, chat: int, text: str) -> None:
        runner = self.state.runner
        low = text.lower()
        if low in ("/new", "new chat"):
            self.thread = None
            await self.client.send(chat, "New chat. What should Claw do?")
            return
        if low in ("/stop", "stop"):
            stopped = runner.busy and runner.cancel(runner.current_id)
            await self.client.send(chat, "Stopping the task." if stopped else "Nothing is running.")
            return
        if low in ("/status", "status"):
            await self.client.send(chat, f"Working on: {self.state.db.get_task(runner.current_id)['task_text']}"
                                   if runner.busy else "Claw is free.")
            return
        pending = runner.pending()
        if pending and low in ("yes", "y", "allow", "ok", "no", "n", "deny"):
            runner.answer(pending[0]["id"], low in ("yes", "y", "allow", "ok"))
            await self.client.send(chat, "Allowed." if low in ("yes", "y", "allow", "ok") else "Not allowed.")
            return
        if text.startswith("/"):
            await self.client.send(chat, "Send a task in plain words, or /new, /status, /stop.")
            return
        try:
            task_id = runner.start(text, thread_id=self.thread)
        except TaskBusy:
            await self.client.send(chat, "Claw is busy with another task. Send /status or /stop.")
            return
        self.thread = self.state.db.get_task(task_id)["thread_id"]
        await self.client.send(chat, "On it. I'll tell you when it's done, and ask here before anything important.")
        asyncio.create_task(self.follow(chat, task_id))

    async def follow(self, chat: int, task_id: str) -> None:
        db = self.state.db
        while True:
            await asyncio.sleep(1.5)
            task = db.get_task(task_id)
            for a in self.state.runner.pending():
                if a["task_id"] == task_id and a["id"] not in self._asked:
                    self._asked.add(a["id"])
                    await self.client.send(chat, describe_approval(a), [("Allow", f"ap:{a['id']}:1"), ("Don't allow", f"ap:{a['id']}:0")])
            if task and task["status"] not in ACTIVE:
                await self.client.send(chat, describe_result(task))
                return


def describe_approval(a: dict[str, Any]) -> str:
    what = a.get("description") or a.get("tool", "a step")
    args = a.get("args") or {}
    shown = "\n".join(f"• {k.replace('_', ' ')}: {str(v)[:120]}" for k, v in list(args.items())[:6] if v not in (None, "", []))
    return f"Claw wants to: {what}\n{shown}\n\nAllow it? (or reply yes / no)".strip()


def describe_result(task: dict[str, Any]) -> str:
    res = task.get("result") or {}
    answer = (res.get("final_answer") or "").strip()
    files = [f.get("path", "") for f in res.get("files") or []]
    head = {"completed": "Done.", "failed": "That didn't work.", "cancelled": "Stopped.", "stopped": "Stopped.",
            "incomplete": "Ran out of steps."}.get(task["status"], task["status"])
    parts = [head]
    if answer:
        parts.append(answer)
    if task.get("error"):
        parts.append(task["error"])
    if files:
        parts.append("Files: " + ", ".join(p.split("\\")[-1].split("/")[-1] for p in files))
    return "\n\n".join(parts)
