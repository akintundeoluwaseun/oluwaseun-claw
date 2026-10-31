"""Giving Claw a task from the phone (Telegram), against a stand-in Telegram server (TEST DOUBLE).

Pairing by code, a task run end to end, an approval answered from the phone, and a stranger refused.
"""

import asyncio
import json
import time

import pytest

from claw.channels import bridge as br
from claw.channels.telegram import TelegramClient, TelegramError
from tests.conftest import VALID_PLAN
from tests.test_api import settings_for
from tests.test_chats import finish


class FakeTelegram:
    """Records what the bot sends; hands out queued updates."""

    def __init__(self):
        self.sent: list[dict] = []
        self.callbacks: list[str] = []

    async def me(self):
        return {"username": "my_claw_bot"}

    async def send(self, chat_id, text, buttons=None):
        self.sent.append({"chat": chat_id, "text": text, "buttons": buttons})

    async def answered(self, cid, text=""):
        self.callbacks.append(text)

    async def close(self):
        pass


def msg(chat, text, uid=1):
    return {"update_id": uid, "message": {"chat": {"id": chat}, "text": text}}


def test_token_shape_is_checked():
    with pytest.raises(TelegramError):
        TelegramClient("not-a-token")


def test_pairing_then_a_task_end_to_end(make_client, fake_server):
    fake_server.replies += [json.dumps({**VALID_PLAN, "title": "Phone task"}), finish("All done from the phone.")]
    c = make_client(settings_for(fake_server)).__enter__()
    state = c.app.state.claw
    tg = FakeTelegram()
    b = br.PhoneBridge(state, tg)

    async def go():
        await b.handle(msg(42, "hello"))
        assert "six-digit code" in tg.sent[-1]["text"] and state.settings.phone.paired_chat_id is None
        code = b.new_code()
        await b.handle(msg(42, "999999" if code != "999999" else "000000"))
        assert state.settings.phone.paired_chat_id is None
        await b.handle(msg(42, f"/start {code}"))
        assert state.settings.phone.paired_chat_id == 42 and "Paired" in tg.sent[-1]["text"]
        await b.handle(msg(7, "delete my files"))                       # a stranger
        assert tg.sent[-1] == {"chat": 7, "text": "This Claw is private.", "buttons": None}
        await b.handle(msg(42, "Check whether anything needs doing"))
        assert "On it" in tg.sent[-1]["text"]
        end = time.time() + 15
        while time.time() < end and not any("All done from the phone" in m["text"] for m in tg.sent):
            await asyncio.sleep(0.2)

    c.portal.call(go) if hasattr(c, "portal") else asyncio.get_event_loop().run_until_complete(go())
    assert any(m["text"].startswith("Done.") and "All done from the phone" in m["text"] for m in tg.sent)


def test_approval_text_and_result_text():
    a = {"description": "Save a list of links to a file", "args": {"file_name": "links", "links": ["x"]}}
    assert "Save a list of links" in br.describe_approval(a) and "file name: links" in br.describe_approval(a)
    t = {"status": "completed", "result": {"final_answer": "Saved.", "files": [{"path": "C:\\Users\\a\\Documents\\links.md"}]}, "error": None}
    assert br.describe_result(t) == "Done.\n\nSaved.\n\nFiles: links.md"


def test_approval_buttons_and_yes_no_from_the_paired_phone_only():
    answered = []

    class Runner:
        busy = False
        def pending(self):
            return [{"id": "a" * 32, "task_id": "t"}]
        def answer(self, aid, ok):
            answered.append((aid, ok))
            return True

    class S:
        pass

    state = S()
    state.runner = Runner()
    state.settings = type("X", (), {"phone": type("P", (), {"paired_chat_id": 42})()})()
    tg = FakeTelegram()
    b = br.PhoneBridge(state, tg)

    async def go():
        await b.handle({"update_id": 1, "callback_query": {"id": "c1", "data": "ap:" + "a" * 32 + ":1", "message": {"chat": {"id": 42}}}})
        await b.handle({"update_id": 2, "callback_query": {"id": "c2", "data": "ap:" + "a" * 32 + ":1", "message": {"chat": {"id": 9}}}})
        await b.handle(msg(42, "no"))

    asyncio.run(go())
    assert answered == [("a" * 32, True), ("a" * 32, False)]
    assert tg.callbacks == ["Allowed", "This Claw is private."]
