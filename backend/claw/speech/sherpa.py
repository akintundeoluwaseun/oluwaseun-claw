"""The sherpa-onnx recogniser (https://github.com/k2-fsa/sherpa-onnx, Apache-2.0).

Chosen over whisper.cpp because it installs as an ordinary Python wheel on
Windows -- no second native binary to fetch, build or ship beside llama-server --
and it runs Whisper exports on CPU through ONNX Runtime. The SpeechEngine
interface keeps that a swap, not a commitment.

Everything runs on this computer. Nothing here opens a network connection.
"""

from __future__ import annotations

import logging
import time

from claw.speech.audio import TARGET_RATE, Audio
from claw.speech.base import SpeechUnavailable, Transcript
from claw.speech.store import InstalledVoiceModel

log = logging.getLogger("claw.speech")

INSTALL_HINT = "Reinstall Claw, or run `pip install sherpa-onnx` in the backend folder."


def _import():
    try:
        import sherpa_onnx  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - exercised by test_missing_runtime
        raise SpeechUnavailable("The speech recognition runtime is not installed.", INSTALL_HINT) from exc
    return sherpa_onnx


class SherpaEngine:
    """Offline Whisper recognition through sherpa-onnx."""

    name = "sherpa-onnx"

    def __init__(self) -> None:
        self._recognizer = None
        self._model_id: str | None = None
        self._online = None
        self._online_id: str | None = None

    # ---------- state ----------
    def available(self) -> tuple[bool, str]:
        try:
            _import()
        except SpeechUnavailable as exc:
            return False, exc.message
        return True, ""

    @property
    def loaded_model(self) -> str | None:
        return self._model_id

    # ---------- lifecycle ----------
    def load(self, model: InstalledVoiceModel) -> None:
        if self._model_id == model.id and self._recognizer is not None:
            return
        sherpa_onnx = _import()
        missing = model.missing()
        if missing:
            raise SpeechUnavailable(
                f"The '{model.name}' voice model is incomplete ({', '.join(missing)}).",
                "Repair or download it again in Settings.",
            )
        for role in ("encoder", "decoder", "tokens"):
            if role not in model.files:
                raise SpeechUnavailable(
                    f"The '{model.name}' voice model has no {role} file.",
                    "Download it again in Settings.",
                )
        started = time.monotonic()
        try:
            self._recognizer = sherpa_onnx.OfflineRecognizer.from_whisper(
                encoder=str(model.path("encoder")),
                decoder=str(model.path("decoder")),
                tokens=str(model.path("tokens")),
                num_threads=2,
            )
        except Exception as exc:  # noqa: BLE001 - a bad file surfaces as a plain message
            self._recognizer = None
            self._model_id = None
            raise SpeechUnavailable(
                f"The '{model.name}' voice model could not be loaded.",
                "It may be damaged. Repair it in Settings.",
            ) from exc
        self._model_id = model.id
        log.info("voice model loaded: %s in %.1fs", model.id, time.monotonic() - started)

    def unload(self) -> None:
        self._recognizer = None
        self._model_id = None
        self._online = None
        self._online_id = None

    # ---------- live recognition ----------
    def supports_streaming(self, model: InstalledVoiceModel) -> bool:
        """Only a transducer decodes as you speak. Whisper needs the whole utterance."""
        return model.kind == "streaming" and "joiner" in model.files

    def open_stream(self, model: InstalledVoiceModel):
        if not self.supports_streaming(model):
            raise SpeechUnavailable(
                f"The '{model.name}' voice model shows the words after you stop speaking, not while you talk.",
                "Settings → Voice → choose a model marked 'Live' for that.",
            )
        sherpa_onnx = _import()
        missing = model.missing()
        if missing:
            raise SpeechUnavailable(
                f"The '{model.name}' voice model is incomplete ({', '.join(missing)}).",
                "Repair or download it again in Settings.",
            )
        if self._online is None or self._online_id != model.id:
            try:
                self._online = sherpa_onnx.OnlineRecognizer.from_transducer(
                    tokens=str(model.path("tokens")),
                    encoder=str(model.path("encoder")),
                    decoder=str(model.path("decoder")),
                    joiner=str(model.path("joiner")),
                    num_threads=2,
                    enable_endpoint_detection=True,
                )
            except Exception as exc:  # noqa: BLE001
                self._online = None
                self._online_id = None
                raise SpeechUnavailable(
                    f"The '{model.name}' voice model could not be loaded.",
                    "It may be damaged. Repair it in Settings.",
                ) from exc
            self._online_id = model.id
        return SherpaStream(self._online, self._online.create_stream())

    # ---------- recognition ----------
    def transcribe(self, audio: Audio) -> Transcript:
        if self._recognizer is None:
            raise SpeechUnavailable("No voice model is loaded.", "Choose one in Settings.")
        if audio.rate != TARGET_RATE:
            raise SpeechUnavailable(f"Audio must be {TARGET_RATE} Hz; got {audio.rate}.")
        started = time.monotonic()
        stream = self._recognizer.create_stream()
        stream.accept_waveform(TARGET_RATE, list(audio.samples))
        self._recognizer.decode_stream(stream)
        text = (getattr(stream.result, "text", "") or "").strip()
        return Transcript(
            text=text,
            engine=self.name,
            model_id=self._model_id or "",
            audio_seconds=round(audio.seconds, 2),
            took_seconds=round(time.monotonic() - started, 2),
        )


class SherpaStream:
    """A live utterance against a streaming transducer.

    sherpa-onnx resets its hypothesis at each endpoint (a pause long enough to end
    a sentence), so the text so far is kept here and the current hypothesis is
    added to it. Without that, a pause mid-command would wipe what was already said.
    """

    def __init__(self, recognizer, stream):
        self._rec = recognizer
        self._stream = stream
        self._committed: list[str] = []
        self._closed = False

    def accept(self, samples) -> None:
        if self._closed:
            return
        self._stream.accept_waveform(TARGET_RATE, list(samples))
        while self._rec.is_ready(self._stream):
            self._rec.decode_stream(self._stream)
        if self._rec.is_endpoint(self._stream):
            text = (self._rec.get_result(self._stream) or "").strip()
            if text:
                self._committed.append(text)
            self._rec.reset(self._stream)

    def partial(self) -> str:
        if self._closed:
            return " ".join(self._committed).strip()
        current = (self._rec.get_result(self._stream) or "").strip()
        return " ".join([*self._committed, current]).strip()

    def final(self) -> str:
        if self._closed:
            return " ".join(self._committed).strip()
        self._stream.input_finished()
        while self._rec.is_ready(self._stream):
            self._rec.decode_stream(self._stream)
        text = (self._rec.get_result(self._stream) or "").strip()
        if text:
            self._committed.append(text)
        self._closed = True
        return " ".join(self._committed).strip()

    def close(self) -> None:
        self._closed = True
        self._stream = None
        self._rec = None
