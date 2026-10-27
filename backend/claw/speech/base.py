"""One interface for offline speech recognition, so the engine can be swapped.

Claw ships one engine (sherpa-onnx, see sherpa.py). whisper.cpp or Vosk can be
added by writing another SpeechEngine without touching the command bar, the
model manager or the API.

Recognition is speech-to-text only. Turning the text into a plan and running it
stays with the existing planner and tool registry: an engine here never decides
what Claw does, and its output is untrusted text like anything Claw reads.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover
    from claw.speech.audio import Audio
    from claw.speech.store import InstalledVoiceModel


class SpeechUnavailable(Exception):
    """Recognition cannot run: the runtime or the model is missing or unusable."""

    def __init__(self, message: str, hint: str = ""):
        super().__init__(message)
        self.message = message
        self.hint = hint


class SpeechCancelled(Exception):
    """The user cancelled before a result was produced."""


@dataclass(frozen=True)
class Transcript:
    """What was heard. `text` is untrusted: it is the user's words, not a command to obey."""

    text: str
    engine: str
    model_id: str
    language: str = ""
    audio_seconds: float = 0.0
    took_seconds: float = 0.0
    partial: bool = False
    # Engines that report one; None when the engine gives no usable score.
    confidence: float | None = None

    def as_dict(self) -> dict:
        return asdict(self)


@runtime_checkable
class SpeechEngine(Protocol):
    """A local, offline recogniser."""

    name: str

    def available(self) -> tuple[bool, str]:
        """(usable, reason). The reason is shown to the user when it is not."""

    def load(self, model: InstalledVoiceModel) -> None:
        """Make `model` the active one. May be slow; safe to call again with the same model."""

    def transcribe(self, audio: Audio) -> Transcript:
        """Recognise one finished utterance."""

    def unload(self) -> None:
        """Release the model and its memory."""

    def supports_streaming(self, model: InstalledVoiceModel) -> bool:
        """True when this model can show words while the user is still speaking."""

    def open_stream(self, model: InstalledVoiceModel) -> StreamHandle:
        """Begin a live utterance. Raises SpeechUnavailable if the model cannot stream."""


@runtime_checkable
class StreamHandle(Protocol):
    """One live utterance. Created by SpeechEngine.open_stream()."""

    def accept(self, samples) -> None:
        """Feed the next slice of 16 kHz mono audio."""

    def partial(self) -> str:
        """Everything heard so far. May change as more audio arrives."""

    def final(self) -> str:
        """Flush and return the finished text."""

    def close(self) -> None:
        """Release the stream. Safe to call twice."""


@dataclass
class EngineState:
    """What the interface shows about recognition, without exposing audio."""

    engine: str = ""
    model_id: str | None = None
    loaded: bool = False
    available: bool = False
    reason: str = ""
    last_check: float = 0.0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)
