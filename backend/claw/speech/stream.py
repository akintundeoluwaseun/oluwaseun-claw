"""Live utterances in progress.

One session per recording: the bar opens it when the microphone starts, pushes
audio as it arrives, and closes it when the user stops. Partial text is returned
with every chunk so the words can appear while the user is still speaking.

Limits exist because a session holds a loaded model and a growing buffer: one
session at a time (there is one microphone), a cap on how long an utterance may
run, and an idle timeout so a bar that crashes mid-recording does not pin the
model open for ever. Audio is held only as long as the session lives, and is
never written to disk.
"""

from __future__ import annotations

import secrets
import time
from array import array
from dataclasses import dataclass, field

from claw.speech.audio import MAX_SECONDS, TARGET_RATE, AudioError, StreamResampler
from claw.speech.base import SpeechUnavailable

IDLE_TIMEOUT_S = 30.0  # no audio for this long: the bar is gone, drop the session
MAX_CHUNK_BYTES = 2 * 1024 * 1024


@dataclass
class StreamSession:
    id: str
    model_id: str
    handle: object  # StreamHandle
    resampler: StreamResampler
    started: float = field(default_factory=time.monotonic)
    last_seen: float = field(default_factory=time.monotonic)
    samples: int = 0
    closed: bool = False

    @property
    def seconds(self) -> float:
        return self.samples / TARGET_RATE

    def idle_for(self) -> float:
        return time.monotonic() - self.last_seen

    def feed(self, floats: array) -> str:
        """Add source-rate samples, return the text so far."""
        if self.closed:
            raise SpeechUnavailable("That recording has already finished.")
        ready = self.resampler.feed(floats)
        if ready:
            self.samples += len(ready)
            if self.seconds > MAX_SECONDS:
                self.close()
                raise AudioError(f"That recording passed {MAX_SECONDS:.0f} seconds and was stopped.")
            self.handle.accept(ready)
        self.last_seen = time.monotonic()
        return self.handle.partial()

    def finish(self) -> str:
        if self.closed:
            return ""
        tail = self.resampler.flush()
        if tail:
            self.samples += len(tail)
            self.handle.accept(tail)
        text = self.handle.final()
        self.close()
        return text

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            try:
                self.handle.close()
            except Exception:  # noqa: BLE001 - closing must never raise at the caller
                pass


class StreamRegistry:
    """The live session, if there is one."""

    def __init__(self):
        self._session: StreamSession | None = None

    @property
    def active(self) -> StreamSession | None:
        self._expire_if_idle()
        return self._session

    def _expire_if_idle(self) -> None:
        s = self._session
        if s and not s.closed and s.idle_for() > IDLE_TIMEOUT_S:
            s.close()
            self._session = None

    def open(self, model_id: str, handle, src_rate: int) -> StreamSession:
        """Start a session, replacing any earlier one (there is only one microphone)."""
        self.close()
        session = StreamSession(
            id=secrets.token_urlsafe(12),
            model_id=model_id,
            handle=handle,
            resampler=StreamResampler(src_rate, TARGET_RATE),
        )
        self._session = session
        return session

    def get(self, stream_id: str) -> StreamSession:
        self._expire_if_idle()
        s = self._session
        if s is None or s.id != stream_id or s.closed:
            raise SpeechUnavailable("That recording is no longer open.", "Press the microphone and speak again.")
        return s

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None


def check_chunk(data: bytes) -> None:
    if not data:
        raise AudioError("That piece of the recording was empty.")
    if len(data) > MAX_CHUNK_BYTES:
        raise AudioError("That piece of the recording was too large.")
