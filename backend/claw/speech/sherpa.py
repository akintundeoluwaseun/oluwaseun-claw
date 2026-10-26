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
