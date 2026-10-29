"""Offline voice input: audio handling, the model manager, the service and the API.

REAL here: audio decoding and resampling, the model store, downloads against the
local stand-in hub (checksums, resume, corruption, disk space, cancel), settings,
the API with its token, and the privacy rules.

TEST DOUBLE: the recogniser itself. sherpa-onnx's wheel and a voice model are not
installed in this workspace and Hugging Face is unreachable here, so accuracy,
microphone capture and the floating bar are BLOCKED -- see
docs/VOICE_NIGERIAN_ENGLISH.md and docs/WINDOWS_ACCEPTANCE.md. No test in this
file measures recognition quality, and none may be read as doing so.
"""

from __future__ import annotations

import asyncio
import io
import math
import wave
from array import array

import pytest

from claw.config import Settings, VoiceSettings
from claw.speech import catalog
from claw.speech.audio import (
    MAX_SECONDS,
    TARGET_RATE,
    Audio,
    AudioError,
    from_wav,
    prepare,
    resample,
    to_pcm16,
    write_wav,
)
from claw.speech.base import SpeechUnavailable, Transcript
from claw.speech.service import SpeechService
from claw.speech.store import InstalledVoiceModel, VoiceModelStore


# ---------- helpers ----------
def tone(seconds=1.0, rate=TARGET_RATE, freq=440.0, channels=1, width=2, amplitude=0.3) -> bytes:
    """A deterministic WAV. A tone, not speech: it exercises plumbing, never accuracy."""
    frames = int(seconds * rate)
    kind, peak, bias = {1: ("b", 127, 128), 2: ("h", 32767, 0), 4: ("i", 2147483647, 0)}[width]
    samples = array(kind)
    for i in range(frames):
        v = int(amplitude * peak * math.sin(2 * math.pi * freq * i / rate))
        for _ in range(channels):
            samples.append(v)
    if width == 1:  # 8-bit WAV is unsigned
        raw = bytes((v + bias) & 0xFF for v in samples)
    else:
        raw = samples.tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(raw)
    return buf.getvalue()


class FakeEngine:
    """Stands in for sherpa-onnx. Records what it was asked, invents no words."""

    name = "fake"

    def __init__(self, available=True, reason="", text="open notepad and write my assignment"):
        self._available, self._reason, self._text = available, reason, text
        self.loaded_model = None
        self.loads = 0
        self.seen_rate = None

    def available(self):
        return self._available, self._reason

    def load(self, model):
        if model.missing():
            raise SpeechUnavailable(f"The '{model.name}' voice model is incomplete.")
        self.loads += 1
        self.loaded_model = model.id

    def transcribe(self, audio):
        self.seen_rate = audio.rate
        return Transcript(text=self._text, engine=self.name, model_id=self.loaded_model or "",
                          audio_seconds=audio.seconds)

    def unload(self):
        self.loaded_model = None

    def supports_streaming(self, model):
        return False  # a plain offline engine; StreamingEngine below overrides this

    def open_stream(self, model):
        raise SpeechUnavailable("This engine shows the words after you stop speaking.")


def install(store: VoiceModelStore, model_id="whisper-base", *, damaged=False) -> InstalledVoiceModel:
    folder = store.folder_for(model_id)
    folder.mkdir(parents=True, exist_ok=True)
    files, sizes = {}, {}
    for role, name in (("encoder", "encoder.onnx"), ("decoder", "decoder.onnx"), ("tokens", "tokens.txt")):
        blob = b"x" * 64
        (folder / name).write_bytes(blob)
        files[role] = name
        sizes[role] = len(blob)
    if damaged:
        (folder / "encoder.onnx").write_bytes(b"short")  # wrong size = damaged, not missing
    m = InstalledVoiceModel(id=model_id, name="Balanced", engine="sherpa-onnx", folder=folder, kind="offline",
                            files=files, sizes=sizes, languages=["en"], license="mit",
                            source="huggingface.co/test", verified=True)
    store.save_meta(m)
    return m


def voice_settings(**kw) -> Settings:
    s = Settings()
    s.voice = VoiceSettings(**{"enabled": True, **kw})
    return s


# ---------- audio ----------
def test_wav_decodes_to_mono_floats():
    a = from_wav(tone(seconds=0.5))
    assert a.rate == TARGET_RATE
    assert abs(a.seconds - 0.5) < 0.01
    assert max(abs(s) for s in a.samples) <= 1.0


@pytest.mark.parametrize("rate", [8000, 22050, 44100, 48000])
def test_any_rate_becomes_16k(rate):
    a = prepare(tone(seconds=0.4, rate=rate))
    assert a.rate == TARGET_RATE
    assert abs(a.seconds - 0.4) < 0.05


def test_stereo_is_mixed_to_one_channel():
    a = prepare(tone(seconds=0.4, channels=2))
    assert abs(a.seconds - 0.4) < 0.05


@pytest.mark.parametrize("width", [1, 2, 4])
def test_sample_widths(width):
    assert prepare(tone(seconds=0.3, width=width)).rate == TARGET_RATE


def test_downsampling_does_not_simply_drop_samples():
    """Averaging the window low-passes; point-picking would alias into the speech band."""
    high = prepare(tone(seconds=0.3, rate=48000, freq=20000))  # above 16k's Nyquist
    assert max(abs(s) for s in high.samples) < 0.3  # attenuated, not folded back at full strength


@pytest.mark.parametrize("bad,message", [
    (b"", "empty"),
    (b"not a wav at all", "WAV"),
    (tone(seconds=0.05), "too short"),
])
def test_unusable_audio_is_explained(bad, message):
    with pytest.raises(AudioError, match=message):
        from_wav(bad)


def test_overlong_recording_is_refused():
    a = Audio(array("f", [0.0] * int((MAX_SECONDS + 5) * 8000)), 8000)
    with pytest.raises(AudioError, match="seconds long"):
        from_wav(write_wav(a))


def test_silence_is_detected():
    assert Audio(array("f", [0.0] * 16000), TARGET_RATE).is_silent()
    assert not from_wav(tone(seconds=0.5)).is_silent()


def test_pcm16_roundtrip_and_clipping():
    a = Audio(array("f", [0.0, 0.5, -0.5, 2.0, -2.0]), TARGET_RATE)
    got = array("h")
    got.frombytes(to_pcm16(a))
    assert got[3] == 32767 and got[4] == -32768  # clipped, not wrapped


def test_resample_to_same_rate_is_a_no_op():
    a = from_wav(tone(seconds=0.3))
    assert resample(a, TARGET_RATE).samples == a.samples


# ---------- catalogue and store ----------
def test_catalog_entries_are_complete_and_unique():
    ids = [m.id for m in catalog.CATALOG]
    assert len(ids) == len(set(ids))
    assert catalog.get(catalog.DEFAULT_ID) is not None
    for m in catalog.CATALOG:
        assert m.repo and m.engine and m.languages
        assert set(m.files) >= {"encoder", "decoder", "tokens"}
        assert m.approx_download_mb > 0 and m.min_ram_gb > 0


def test_no_checksum_is_hard_coded_in_the_catalogue():
    """Checksums come from the library at download time; a literal here would be a guess."""
    import inspect
    import re

    src = inspect.getsource(catalog)
    assert not re.search(r"[0-9a-f]{64}", src)


def test_recommendation_follows_memory():
    assert catalog.recommended(2).min_ram_gb <= 2.5
    assert catalog.recommended(None).id == catalog.DEFAULT_ID


def test_store_reports_damaged_separately_from_missing(tmp_path):
    store = VoiceModelStore(tmp_path / "voice-models")
    assert store.list() == []
    m = install(store)
    assert m.present() and store.load(m.id).present()

    bad = install(store, "whisper-tiny-en", damaged=True)
    assert not bad.present()
    assert bad.missing() == ["encoder"]  # present but wrong size
    assert store.load("whisper-tiny-en").as_dict()["damaged_parts"] == ["encoder"]


def test_store_ignores_a_folder_without_usable_meta(tmp_path):
    store = VoiceModelStore(tmp_path / "voice-models")
    (store.folder_for("junk")).mkdir(parents=True)
    (store.folder_for("broken")).mkdir(parents=True)
    (store.folder_for("broken") / "meta.json").write_text("{not json")
    assert store.list() == []


def test_remove_deletes_the_model(tmp_path):
    store = VoiceModelStore(tmp_path / "voice-models")
    install(store)
    assert store.remove("whisper-base")
    assert store.list() == []
    assert not store.remove("whisper-base")  # already gone


# ---------- the service ----------
async def test_transcribe_converts_audio_and_uses_the_installed_model(tmp_path):
    store = VoiceModelStore(tmp_path / "voice-models")
    install(store)
    engine = FakeEngine()
    svc = SpeechService(store, engine=engine)
    got = await svc.transcribe(tone(seconds=0.6, rate=44100), voice_settings())
    assert got.text == "open notepad and write my assignment"
    assert engine.seen_rate == TARGET_RATE  # the engine is always handed 16 kHz
    assert engine.loaded_model == "whisper-base"


async def test_transcribe_refuses_when_voice_is_off(tmp_path):
    store = VoiceModelStore(tmp_path / "voice-models")
    install(store)
    svc = SpeechService(store, engine=FakeEngine())
    with pytest.raises(SpeechUnavailable, match="turned off"):
        await svc.transcribe(tone(), voice_settings(enabled=False))


async def test_transcribe_without_a_model_says_so(tmp_path):
    svc = SpeechService(VoiceModelStore(tmp_path / "voice-models"), engine=FakeEngine())
    with pytest.raises(SpeechUnavailable, match="No voice model is installed"):
        await svc.transcribe(tone(), voice_settings())


async def test_silence_is_reported_not_recognised(tmp_path):
    store = VoiceModelStore(tmp_path / "voice-models")
    install(store)
    svc = SpeechService(store, engine=FakeEngine())
    quiet = write_wav(Audio(array("f", [0.0] * TARGET_RATE), TARGET_RATE))
    with pytest.raises(AudioError, match="silence"):
        await svc.transcribe(quiet, voice_settings())


async def test_damaged_model_is_reported_not_loaded(tmp_path):
    store = VoiceModelStore(tmp_path / "voice-models")
    install(store, damaged=True)
    svc = SpeechService(store, engine=FakeEngine())
    with pytest.raises(SpeechUnavailable, match="No voice model is installed"):
        await svc.transcribe(tone(), voice_settings())


async def test_missing_runtime_is_explained_not_crashed(tmp_path):
    store = VoiceModelStore(tmp_path / "voice-models")
    install(store)
    svc = SpeechService(store, engine=FakeEngine(available=False, reason="The speech recognition runtime is not installed."))
    st = svc.status(voice_settings())
    assert not st["ready"] and "runtime is not installed" in st["reason"]


async def test_one_recognition_at_a_time(tmp_path):
    """The model is not re-entrant; two recordings must not decode at once."""
    store = VoiceModelStore(tmp_path / "voice-models")
    install(store)

    overlap = {"now": 0, "max": 0}

    class Slow(FakeEngine):
        def transcribe(self, audio):
            overlap["now"] += 1
            overlap["max"] = max(overlap["max"], overlap["now"])
            import time

            time.sleep(0.05)
            overlap["now"] -= 1
            return super().transcribe(audio)

    svc = SpeechService(store, engine=Slow())
    s = voice_settings()
    await asyncio.gather(*(svc.transcribe(tone(seconds=0.3), s) for _ in range(4)))
    assert overlap["max"] == 1


def test_status_never_contains_audio(tmp_path):
    store = VoiceModelStore(tmp_path / "voice-models")
    install(store)
    st = SpeechService(store, engine=FakeEngine()).status(voice_settings())
    blob = repr(st).lower()
    assert "wav" not in blob and "samples" not in blob and "audio" not in blob
    assert st["ready"] and st["model"]["id"] == "whisper-base"
    assert st["catalog"] and st["download"]["status"] == "idle"


async def test_recognised_text_is_not_written_to_disk(tmp_path, caplog):
    """The words are private: the log records how many, never which."""
    store = VoiceModelStore(tmp_path / "voice-models")
    install(store)
    svc = SpeechService(store, engine=FakeEngine(text="open the sales app and prepare a sale"))
    with caplog.at_level("INFO"):
        await svc.transcribe(tone(seconds=0.5), voice_settings())
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "sales app" not in logged.lower()
    assert not list((tmp_path).rglob("*.wav"))


# ---------- settings ----------
def test_voice_is_off_by_default_and_never_listens_in_the_background():
    v = Settings().voice
    assert v.enabled is False  # no model, no surprise download
    assert v.mode == "click"
    assert v.auto_submit is False
    assert v.keep_recordings is False  # audio is not stored unless the user opts in


@pytest.mark.parametrize("bad", ["", "V", "Ctrl+", "nonsense", "Ctrl+Shift+"])
def test_bad_push_to_talk_shortcut_is_rejected(bad):
    if bad == "":
        assert VoiceSettings(push_to_talk="").push_to_talk == ""  # "" = no shortcut
        return
    with pytest.raises(Exception):
        VoiceSettings(push_to_talk=bad)


def test_settings_roundtrip_keeps_voice(tmp_path):
    from claw.config import SettingsStore

    store = SettingsStore(tmp_path)
    s = Settings()
    s.voice = VoiceSettings(enabled=True, model="whisper-small", mode="push_to_talk")
    store.save(s)
    back = store.load()
    assert back.voice.enabled and back.voice.model == "whisper-small" and back.voice.mode == "push_to_talk"


# ---------- downloading a voice model (against the local stand-in library) ----------
import os  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from claw.runtime.hub import DownloadError  # noqa: E402
from claw.speech.manager import VoiceModels  # noqa: E402
from tests.conftest import TOKEN  # noqa: E402
from tests.fake_hub import FakeHub  # noqa: E402

REPO = "csukuangfj/sherpa-onnx-whisper-base"
PARTS = {"base-encoder.int8.onnx": b"E" * 3000, "base-decoder.int8.onnx": b"D" * 2000, "base-tokens.txt": b"T" * 500}


@pytest.fixture
def library(monkeypatch):
    with FakeHub() as h:
        monkeypatch.setenv("CLAW_HF_BASE", h.base_url)
        h.repos[REPO] = {"license": "mit", "files": dict(PARTS)}
        yield h


async def wait_for(models: VoiceModels, *, timeout=10.0):
    for _ in range(int(timeout / 0.02)):
        if models.download.status in ("done", "failed", "cancelled"):
            return models.download
        await asyncio.sleep(0.02)
    raise AssertionError(f"download stuck at {models.download.status}")


async def test_download_verifies_every_file(tmp_path, library):
    models = VoiceModels(VoiceModelStore(tmp_path / "voice-models"))
    models.start_download("whisper-base")
    dl = await wait_for(models)
    assert dl.status == "done", dl.message
    got = models.get_installed("whisper-base")
    assert got and got.present() and got.verified and got.license == "mit"
    assert set(got.files) == {"encoder", "decoder", "tokens"}
    assert got.folder.joinpath(got.files["encoder"]).read_bytes() == PARTS["base-encoder.int8.onnx"]
    assert dl.done_bytes == dl.total_bytes == sum(len(v) for v in PARTS.values())


async def test_a_corrupted_download_is_refused_and_leaves_nothing(tmp_path, library):
    library.repos[REPO]["sha_override"] = {"base-decoder.int8.onnx": "0" * 64}
    models = VoiceModels(VoiceModelStore(tmp_path / "voice-models"))
    models.start_download("whisper-base")
    dl = await wait_for(models)
    assert dl.status == "failed"
    assert models.get_installed("whisper-base") is None
    assert models.store.list() == []  # no half-installed model left behind


async def test_download_resumes_from_a_part_file(tmp_path, library):
    store = VoiceModelStore(tmp_path / "voice-models")
    folder = store.folder_for("whisper-base")
    folder.mkdir(parents=True)
    (folder / "base-encoder.int8.onnx.part").write_bytes(PARTS["base-encoder.int8.onnx"][:1500])
    models = VoiceModels(store)
    models.start_download("whisper-base")
    assert (await wait_for(models)).status == "done"
    assert models.get_installed("whisper-base").present()
    ranged = [p for p in library.requests if "resolve" in p]
    assert ranged  # the file was fetched; the .part gave it a head start


async def test_unknown_model_and_double_download_are_refused(tmp_path, library):
    models = VoiceModels(VoiceModelStore(tmp_path / "voice-models"))
    with pytest.raises(DownloadError, match="no voice model called"):
        models.start_download("not-a-model")
    models.start_download("whisper-base")
    with pytest.raises(DownloadError, match="already setting up"):
        models.start_download("whisper-tiny-en")
    await wait_for(models)


async def test_a_disallowed_licence_stops_the_download(tmp_path, library):
    library.repos[REPO]["license"] = "cc-by-nc-4.0"
    models = VoiceModels(VoiceModelStore(tmp_path / "voice-models"))
    models.start_download("whisper-base")
    dl = await wait_for(models)
    assert dl.status == "failed" and "cc-by-nc-4.0" in dl.message
    assert models.store.list() == []


async def test_a_missing_repository_is_explained(tmp_path, library):
    library.repos.pop(REPO)
    models = VoiceModels(VoiceModelStore(tmp_path / "voice-models"))
    models.start_download("whisper-base")
    dl = await wait_for(models)
    assert dl.status == "failed" and "no longer has" in dl.message


async def test_cancelling_removes_the_partial_model(tmp_path, library):
    library.chunk_delay = 0.05
    models = VoiceModels(VoiceModelStore(tmp_path / "voice-models"))
    models.start_download("whisper-base")
    await asyncio.sleep(0.08)
    models.cancel()
    dl = await wait_for(models)
    assert dl.status in ("cancelled", "failed")
    assert models.get_installed("whisper-base") is None


async def test_no_disk_space_is_reported_before_downloading(tmp_path, library, monkeypatch):
    import shutil as sh

    Usage = __import__("collections").namedtuple("Usage", "total used free")
    monkeypatch.setattr(sh, "disk_usage", lambda _p: Usage(10**9, 10**9, 1))
    models = VoiceModels(VoiceModelStore(tmp_path / "voice-models"))
    models.start_download("whisper-base")
    dl = await wait_for(models)
    assert dl.status == "failed" and "disk space" in dl.message


# ---------- the API ----------
def test_speech_routes_need_the_token(make_client):
    client = make_client()
    assert client.get("/speech", headers={"X-Claw-Token": ""}).status_code == 401
    assert client.post("/speech/transcribe", content=b"x", headers={"X-Claw-Token": ""}).status_code == 401
    assert client.get("/speech").status_code == 200


def test_speech_status_shape(make_client):
    body = make_client().get("/speech").json()
    assert body["enabled"] is False  # off until the user installs a model
    assert body["ready"] is False and body["reason"]
    assert [m["id"] for m in body["catalog"]] == [m.id for m in catalog.CATALOG]
    assert body["download"]["status"] == "idle"
    assert body["auto_submit"] is False and body["keep_recordings"] is False


def test_transcribe_without_a_model_is_a_clear_409(make_client):
    client = make_client({"voice": {"enabled": True}})
    r = client.post("/speech/transcribe", content=tone(seconds=0.5))
    assert r.status_code == 409
    assert "voice model" in r.json()["error"]["message"].lower()


def test_transcribe_rejects_rubbish_audio(make_client):
    client = make_client({"voice": {"enabled": True}})
    r = client.post("/speech/transcribe", content=b"this is not audio")
    assert r.status_code == 400 and "WAV" in r.json()["error"]["message"]


def test_transcribe_refused_while_voice_is_off(make_client):
    r = make_client().post("/speech/transcribe", content=tone(seconds=0.5))
    assert r.status_code == 409 and "turned off" in r.json()["error"]["message"]


def test_removing_a_model_that_is_not_there_is_404(make_client):
    assert make_client().post("/speech/models/remove", json={"id": "whisper-small"}).status_code == 404


def test_download_route_rejects_an_unknown_model(make_client):
    r = make_client().post("/speech/models/download", json={"id": "nope"})
    assert r.status_code == 409 and "no voice model" in r.json()["error"]["message"].lower()


# ---------- offline and independence ----------
def test_recognition_path_contains_no_network_code():
    """Test 14: audio must never leave the computer.

    Only manager.py may talk to the network, and only to fetch a model the user
    asked for. The modules that handle audio must contain no client at all, so a
    recognition cannot become a request however it is called.
    """
    import inspect
    import re

    from claw.speech import audio as audio_mod
    from claw.speech import base as base_mod
    from claw.speech import service as service_mod
    from claw.speech import sherpa as sherpa_mod
    from claw.speech import store as store_mod

    forbidden = re.compile(r"\b(httpx|requests|urllib|socket|aiohttp|fetch|http://|https://)\b", re.I)
    for mod in (audio_mod, base_mod, sherpa_mod, store_mod, service_mod):
        src = inspect.getsource(mod)
        # Strip comments and docstrings: a URL in prose is not a request.
        code = "\n".join(line.split("#")[0] for line in src.splitlines())
        code = re.sub(r'""".*?"""', "", code, flags=re.S)
        hit = forbidden.search(code)
        assert hit is None, f"{mod.__name__} mentions {hit.group(0)!r} in the recognition path"


async def test_recognition_works_with_no_brain_installed(tmp_path):
    """Test 17: speech recognition is independent of the AI model.

    A user with no brain must still be able to dictate and see the words; only
    carrying the instruction out needs the planner.
    """
    store = VoiceModelStore(tmp_path / "voice-models")
    install(store)
    svc = SpeechService(store, engine=FakeEngine(text="check my downloads folder"))
    assert not hasattr(svc, "brain")  # the service has no model adapter at all
    got = await svc.transcribe(tone(seconds=0.5), voice_settings())
    assert got.text == "check my downloads folder"


def test_voice_status_is_separate_from_the_brain(make_client):
    """A missing brain must not be reported as a voice problem, or the reverse."""
    body = make_client().get("/speech").json()
    assert "brain" not in repr(body).lower()
    assert set(body) >= {"runtime_ready", "ready", "reason", "model", "catalog"}


# ---------- live transcription ----------
from claw.speech.audio import StreamResampler, pcm16_to_floats  # noqa: E402
from claw.speech.stream import IDLE_TIMEOUT_S, StreamRegistry  # noqa: E402


class FakeStream:
    """Emits one word per ~0.2 s of audio, and commits across a simulated pause."""

    def __init__(self, words):
        self.words = list(words)
        self.samples = 0
        self.closed = False
        self.committed = []

    def accept(self, samples):
        assert not self.closed, "audio after close"
        self.samples += len(samples)

    def _heard(self):
        n = min(len(self.words), int(self.samples / (TARGET_RATE * 0.2)))
        return self.words[:n]

    def partial(self):
        return " ".join(self._heard())

    def final(self):
        self.closed = True
        return " ".join(self.words[: max(1, len(self._heard()))])

    def close(self):
        self.closed = True


class StreamingEngine(FakeEngine):
    name = "fake-stream"

    def __init__(self, words=("open", "notepad", "and", "write"), can_stream=True):
        super().__init__()
        self.words = words
        self.can_stream = can_stream
        self.streams = []

    def supports_streaming(self, model):
        return self.can_stream and model.kind == "streaming"

    def open_stream(self, model):
        if not self.supports_streaming(model):
            raise SpeechUnavailable(f"The '{model.name}' voice model shows the words after you stop speaking.")
        s = FakeStream(self.words)
        self.streams.append(s)
        return s


def install_streaming(store, model_id="zipformer-en-stream"):
    m = install(store, model_id)
    m.kind = "streaming"
    m.files["joiner"] = "joiner.onnx"
    (m.folder / "joiner.onnx").write_bytes(b"x" * 64)
    m.sizes["joiner"] = 64
    store.save_meta(m)
    return store.load(model_id)


def pcm(seconds=0.2, rate=TARGET_RATE):
    frames = int(seconds * rate)
    return array("h", [int(3000 * math.sin(2 * math.pi * 300 * i / rate)) for i in range(frames)]).tobytes()


def test_store_remembers_that_a_model_streams(tmp_path):
    store = VoiceModelStore(tmp_path / "voice-models")
    m = install_streaming(store)
    assert m.kind == "streaming" and m.as_dict()["streaming"] is True
    assert install(store, "whisper-base").as_dict()["streaming"] is False


def test_catalogue_offers_a_live_model():
    live = [m for m in catalog.CATALOG if m.kind == "streaming"]
    assert live, "no streaming model offered"
    for m in live:
        assert "joiner" in m.files  # a transducer, not Whisper
    for m in catalog.CATALOG:
        assert m.kind in ("streaming", "offline")


async def test_words_appear_while_speaking(tmp_path):
    store = VoiceModelStore(tmp_path / "voice-models")
    install_streaming(store)
    svc = SpeechService(store, engine=StreamingEngine())
    s = voice_settings(model="zipformer-en-stream")

    started = await svc.start_stream(s, TARGET_RATE)
    seen = []
    for _ in range(4):
        got = await svc.feed_stream(started["stream_id"], pcm(0.2))
        seen.append(got["text"])
        assert got["partial"] is True and got["untrusted"] is True
    # The text grows as the audio arrives: that is what "live" means.
    assert seen[0] and len(seen[0].split()) < len(seen[-1].split())
    assert seen == sorted(seen, key=lambda t: len(t.split()))
    final = await svc.finish_stream(started["stream_id"])
    assert final.text == "open notepad and write" and final.partial is False
    assert final.audio_seconds > 0.5


async def test_a_microphone_at_another_rate_is_resampled_live(tmp_path):
    store = VoiceModelStore(tmp_path / "voice-models")
    install_streaming(store)
    engine = StreamingEngine()
    svc = SpeechService(store, engine=engine)
    s = voice_settings(model="zipformer-en-stream")
    started = await svc.start_stream(s, 48000)
    for _ in range(5):
        await svc.feed_stream(started["stream_id"], pcm(0.2, rate=48000))
    await svc.finish_stream(started["stream_id"])
    # 1.0 s in at 48 kHz must be ~1.0 s of 16 kHz samples, not three times as many.
    assert abs(engine.streams[0].samples - TARGET_RATE) < TARGET_RATE * 0.05


async def test_cancelling_a_live_recording_stops_it_dead(tmp_path):
    store = VoiceModelStore(tmp_path / "voice-models")
    install_streaming(store)
    engine = StreamingEngine()
    svc = SpeechService(store, engine=engine)
    s = voice_settings(model="zipformer-en-stream")
    started = await svc.start_stream(s, TARGET_RATE)
    await svc.feed_stream(started["stream_id"], pcm())
    svc.cancel_stream()
    assert engine.streams[0].closed
    with pytest.raises(SpeechUnavailable, match="no longer open"):
        await svc.feed_stream(started["stream_id"], pcm())


async def test_only_one_live_recording_at_a_time(tmp_path):
    store = VoiceModelStore(tmp_path / "voice-models")
    install_streaming(store)
    engine = StreamingEngine()
    svc = SpeechService(store, engine=engine)
    s = voice_settings(model="zipformer-en-stream")
    first = await svc.start_stream(s, TARGET_RATE)
    second = await svc.start_stream(s, TARGET_RATE)
    assert first["stream_id"] != second["stream_id"]
    assert engine.streams[0].closed  # the first was released, not leaked
    with pytest.raises(SpeechUnavailable, match="no longer open"):
        await svc.feed_stream(first["stream_id"], pcm())


async def test_a_model_that_cannot_stream_says_so(tmp_path):
    store = VoiceModelStore(tmp_path / "voice-models")
    install(store)  # Whisper: offline only
    svc = SpeechService(store, engine=StreamingEngine())
    with pytest.raises(SpeechUnavailable, match="after you stop speaking"):
        await svc.start_stream(voice_settings(), TARGET_RATE)


async def test_status_says_whether_the_active_model_is_live(tmp_path):
    store = VoiceModelStore(tmp_path / "voice-models")
    install(store)
    svc = SpeechService(store, engine=StreamingEngine())
    assert svc.status(voice_settings())["streaming"] is False
    install_streaming(store)
    assert svc.status(voice_settings(model="zipformer-en-stream"))["streaming"] is True


async def test_an_overlong_live_recording_is_stopped(tmp_path, monkeypatch):
    import claw.speech.stream as stream_mod

    monkeypatch.setattr(stream_mod, "MAX_SECONDS", 0.5)
    store = VoiceModelStore(tmp_path / "voice-models")
    install_streaming(store)
    svc = SpeechService(store, engine=StreamingEngine())
    s = voice_settings(model="zipformer-en-stream")
    started = await svc.start_stream(s, TARGET_RATE)
    with pytest.raises(AudioError, match="was stopped"):
        for _ in range(6):
            await svc.feed_stream(started["stream_id"], pcm(0.2))


async def test_rubbish_chunks_are_refused(tmp_path):
    store = VoiceModelStore(tmp_path / "voice-models")
    install_streaming(store)
    svc = SpeechService(store, engine=StreamingEngine())
    started = await svc.start_stream(voice_settings(model="zipformer-en-stream"), TARGET_RATE)
    with pytest.raises(AudioError, match="empty"):
        await svc.feed_stream(started["stream_id"], b"")
    with pytest.raises(AudioError, match="too large"):
        await svc.feed_stream(started["stream_id"], b"\x00" * (3 * 1024 * 1024))


def test_an_abandoned_recording_does_not_pin_the_model(monkeypatch):
    """A bar that crashes mid-recording must not hold the model open for ever."""
    reg = StreamRegistry()
    handle = FakeStream(["hello"])
    session = reg.open("m", handle, TARGET_RATE)
    assert reg.active is session
    now = [0.0]
    monkeypatch.setattr("claw.speech.stream.time.monotonic", lambda: now[0])
    session.last_seen = 0.0
    now[0] = IDLE_TIMEOUT_S + 1
    assert reg.active is None
    assert handle.closed


def test_pcm16_decoding_round_trips():
    a = Audio(array("f", [0.0, 0.5, -0.5]), TARGET_RATE)
    back = pcm16_to_floats(to_pcm16(a))
    assert len(back) == 3 and abs(back[1] - 0.5) < 0.001
    assert len(pcm16_to_floats(b"\x01")) == 0  # an odd trailing byte is dropped, not a crash


def test_stream_resampler_matches_whole_file_resampling():
    src = array("f", [math.sin(2 * math.pi * 220 * i / 48000) for i in range(48000)])
    want = resample(Audio(src, 48000), TARGET_RATE).samples
    r = StreamResampler(48000, TARGET_RATE)
    got = array("f")
    for i in range(0, len(src), 1024):
        got.extend(r.feed(array("f", src[i:i + 1024])))
    got.extend(r.flush())
    assert len(got) == len(want)
    assert max(abs(a - b) for a, b in zip(got, want)) < 1e-6
