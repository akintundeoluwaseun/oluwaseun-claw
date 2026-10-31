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


def test_voice_notes_are_decoded_heard_and_run(tmp_path):
    """A real OGG/Opus voice note is decoded to 16 kHz WAV; the words go in as the task."""
    import io
    import math
    import wave

    import av
    import numpy as np

    from claw.speech.decode import to_wav16k

    # make a one-second OGG/Opus note, as Telegram sends them
    buf = io.BytesIO()
    with av.open(buf, "w", format="ogg") as c:
        st = c.add_stream("libopus", rate=48000)
        st.layout = "mono"
        t = np.arange(48000) / 48000
        samples = (0.3 * np.sin(2 * math.pi * 440 * t) * 32767).astype("int16").reshape(1, -1)
        frame = av.AudioFrame.from_ndarray(samples, format="s16", layout="mono")
        frame.sample_rate = 48000
        for p in st.encode(frame):
            c.mux(p)
        for p in st.encode(None):
            c.mux(p)
    wav = to_wav16k(buf.getvalue())
    with wave.open(io.BytesIO(wav)) as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1 and 0.8 < w.getnframes() / 16000 < 1.3

    started = []

    class Speech:
        async def transcribe(self, wav, settings):
            return type("T", (), {"text": "open notepad"})()

    class Runner:
        busy = False
        def pending(self):
            return []
        def start(self, text, thread_id=None):
            started.append(text)
            return "a" * 32

    class DB:
        def get_task(self, tid):
            return {"thread_id": tid, "status": "completed", "result": {}, "error": None}

    class Client(FakeTelegram):
        async def download(self, file_id):
            return buf.getvalue()

    s = type("S", (), {})()
    s.runner, s.db, s.speech = Runner(), DB(), Speech()
    s.settings = type("X", (), {"phone": type("P", (), {"paired_chat_id": 42})()})()
    tg = Client()
    b = br.PhoneBridge(s, tg)

    async def go():
        await b.handle({"update_id": 1, "message": {"chat": {"id": 42}, "voice": {"file_id": "v1", "duration": 1}}})
        await asyncio.sleep(0)

    asyncio.run(go())
    assert started == ["open notepad"] and tg.sent[0]["text"] == "Heard: “open notepad”"
