"""Speech recognition as the rest of Claw sees it.

Holds the engine, the installed models and the download state, and answers two
questions: what is the state of voice input, and what were these words?

Deliberately not here: deciding what to do with the words. The command bar puts
the text in its field, the user reads it and submits it, and the existing
planner takes over. Recognised text is treated as untrusted input, exactly like
a web page or a document -- it is never run as a command on its own.
"""

from __future__ import annotations

import asyncio
import logging
import time

from claw.logging_setup import log_event
from claw.speech import catalog
from claw.speech.audio import AudioError, pcm16_to_floats, prepare
from claw.speech.base import SpeechUnavailable, Transcript
from claw.speech.manager import VoiceModels
from claw.speech.store import VoiceModelStore
from claw.speech.stream import StreamRegistry, check_chunk

log = logging.getLogger("claw.speech")


class SpeechService:
    def __init__(self, store: VoiceModelStore, engine=None, hardware_ram_gb: float | None = None):
        self.models = VoiceModels(store)
        self._engine = engine
        self._ram = hardware_ram_gb
        self._lock = asyncio.Lock()
        self.streams = StreamRegistry()
        self.last_check: float = 0.0

    @property
    def engine(self):
        if self._engine is None:
            from claw.speech.sherpa import SherpaEngine  # imported late: the wheel may be absent

            self._engine = SherpaEngine()
        return self._engine

    # ---------- state ----------
    def status(self, settings) -> dict:
        """Everything Settings and the command bar need, and no audio."""
        enabled = bool(settings.voice.enabled)
        ok, reason = self.engine.available()
        active = self.models.active(settings.voice.model)
        if ok and active is None:
            reason = "No voice model is installed yet."
        return {
            "enabled": enabled,
            "engine": self.engine.name,
            "runtime_ready": ok,
            "ready": bool(enabled and ok and active is not None),
            "reason": "" if (ok and active) else reason,
            "model": active.as_dict() if active else None,
            "selected": settings.voice.model,
            "loaded": getattr(self.engine, "loaded_model", None),
            "catalog": self.models.catalogue(self._ram),
            "installed": [m.as_dict() for m in self.models.installed()],
            "download": self.models.download.as_dict(),
            "streaming": bool(active and self.engine.supports_streaming(active)) if ok else False,
            "push_to_talk": settings.voice.push_to_talk,
            "auto_submit": settings.voice.auto_submit,
            "keep_recordings": settings.voice.keep_recordings,
            "last_check": self.last_check,
        }

    def unload(self) -> None:
        self.engine.unload()

    # ---------- recognition ----------
    async def transcribe(self, wav: bytes, settings) -> Transcript:
        """Recognise one recording. Raises SpeechUnavailable or AudioError with a readable message."""
        if not settings.voice.enabled:
            raise SpeechUnavailable("Voice input is turned off.", "Turn it on in Settings → Voice.")
        audio = prepare(wav)  # AudioError for anything unreadable, too long or too short
        if audio.is_silent():
            raise AudioError("Claw heard only silence. Check that the right microphone is selected.")
        active = self.models.active(settings.voice.model)
        if active is None:
            raise SpeechUnavailable(
                "No voice model is installed.", "Settings → Voice → choose a model and download it once."
            )
        async with self._lock:  # one recognition at a time: the model is not re-entrant
            loop = asyncio.get_running_loop()
            started = time.monotonic()
            result = await loop.run_in_executor(None, self._blocking_transcribe, active, audio)
        self.last_check = time.time()
        log_event(
            log,
            "speech recognised",
            model=active.id,
            seconds=round(audio.seconds, 2),
            took=round(time.monotonic() - started, 2),
            words=len(result.text.split()),  # never the words themselves
        )
        return result

    # ---------- live recognition ----------
    def _active_or_fail(self, settings):
        if not settings.voice.enabled:
            raise SpeechUnavailable("Voice input is turned off.", "Turn it on in Settings → Voice.")
        active = self.models.active(settings.voice.model)
        if active is None:
            raise SpeechUnavailable(
                "No voice model is installed.", "Settings → Voice → choose a model and download it once."
            )
        return active

    async def start_stream(self, settings, sample_rate: int) -> dict:
        """Open a live utterance. The words come back chunk by chunk."""
        active = self._active_or_fail(settings)
        if not 8000 <= sample_rate <= 192_000:
            raise AudioError("That microphone's sample rate is out of range.")
        loop = asyncio.get_running_loop()
        async with self._lock:
            handle = await loop.run_in_executor(None, self.engine.open_stream, active)
            session = self.streams.open(active.id, handle, sample_rate)
        log_event(log, "speech stream opened", model=active.id, rate=sample_rate)
        return {"stream_id": session.id, "model": active.id, "streaming": True}

    async def feed_stream(self, stream_id: str, pcm16: bytes) -> dict:
        """Add audio, get the words so far. Never raises on a late chunk's content."""
        check_chunk(pcm16)
        session = self.streams.get(stream_id)
        floats = pcm16_to_floats(pcm16)
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(None, session.feed, floats)
        return {"stream_id": stream_id, "text": text, "partial": True,
                "seconds": round(session.seconds, 2), "untrusted": True}

    async def finish_stream(self, stream_id: str) -> Transcript:
        session = self.streams.get(stream_id)
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(None, session.finish)
        self.streams.close()
        self.last_check = time.time()
        log_event(log, "speech stream finished", model=session.model_id,
                  seconds=round(session.seconds, 2), words=len(text.split()))
        return Transcript(text=text, engine=self.engine.name, model_id=session.model_id,
                          audio_seconds=round(session.seconds, 2), partial=False)

    def cancel_stream(self) -> None:
        """Throw the recording away without recognising anything more."""
        self.streams.close()

    def _blocking_transcribe(self, active, audio) -> Transcript:
        self.engine.load(active)
        return self.engine.transcribe(audio)


def default_store(data_dir) -> VoiceModelStore:
    from pathlib import Path

    return VoiceModelStore(Path(data_dir) / "voice-models")


__all__ = ["SpeechService", "catalog", "default_store"]
