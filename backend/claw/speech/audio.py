"""Microphone audio: decode, check, and convert to what the recogniser expects.

The command bar records in the browser engine and sends a WAV. Recognisers want
16 kHz mono, so everything is converted here, with stdlib only (audioop was
removed in Python 3.13).

Audio is held in memory and never written to disk by this module.
"""

from __future__ import annotations

import io
import wave
from array import array
from dataclasses import dataclass

TARGET_RATE = 16_000
MAX_SECONDS = 120.0  # one spoken command; longer is almost always a stuck microphone
MIN_SECONDS = 0.20  # shorter than this carries no word
MAX_BYTES = 40 * 1024 * 1024


class AudioError(ValueError):
    """The recording could not be read. The message is shown to the user."""


@dataclass(frozen=True)
class Audio:
    """Mono PCM as floats in -1.0..1.0."""

    samples: array  # 'f'
    rate: int

    @property
    def seconds(self) -> float:
        return len(self.samples) / self.rate if self.rate else 0.0

    def is_silent(self, threshold: float = 0.004) -> bool:
        """True when nothing above microphone noise was recorded."""
        if not self.samples:
            return True
        peak = max(abs(s) for s in self.samples)
        return peak < threshold


def from_wav(data: bytes) -> Audio:
    """Decode a PCM WAV into mono floats, without changing the sample rate."""
    if not data:
        raise AudioError("The recording was empty.")
    if len(data) > MAX_BYTES:
        raise AudioError("That recording is too large to process.")
    try:
        with wave.open(io.BytesIO(data), "rb") as w:
            channels, width, rate, frames = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
            raw = w.readframes(frames)
    except (wave.Error, EOFError) as exc:
        raise AudioError("That audio is not a WAV recording Claw can read.") from exc

    if rate <= 0 or channels <= 0:
        raise AudioError("The recording has no usable audio.")
    if rate > 192_000:
        raise AudioError("The recording's sample rate is out of range.")
    seconds = frames / rate
    if seconds > MAX_SECONDS:
        raise AudioError(f"That recording is {seconds:.0f} seconds long; Claw takes up to {MAX_SECONDS:.0f}.")

    mono = _to_mono_floats(raw, width, channels)
    if len(mono) / rate < MIN_SECONDS:
        raise AudioError("That recording was too short to contain a command.")
    return Audio(mono, rate)


def _to_mono_floats(raw: bytes, width: int, channels: int) -> array:
    """Interleaved integer PCM -> averaged mono floats."""
    if width == 1:  # 8-bit WAV is unsigned
        ints = array("b", ((b - 128) for b in raw))
        scale = 128.0
    elif width == 2:
        ints = array("h")
        ints.frombytes(raw[: len(raw) - (len(raw) % 2)])
        scale = 32768.0
    elif width == 4:
        ints = array("i")
        ints.frombytes(raw[: len(raw) - (len(raw) % 4)])
        scale = 2147483648.0
    else:
        raise AudioError(f"Claw cannot read {width * 8}-bit audio.")
    if sys_is_big_endian():  # pragma: no cover - WAV is little-endian
        ints.byteswap()

    out = array("f")
    if channels == 1:
        out.extend(v / scale for v in ints)
        return out
    usable = len(ints) - (len(ints) % channels)
    for i in range(0, usable, channels):
        out.append(sum(ints[i : i + channels]) / (channels * scale))
    return out


def sys_is_big_endian() -> bool:
    import sys

    return sys.byteorder == "big"


def resample(audio: Audio, rate: int = TARGET_RATE) -> Audio:
    """Change the sample rate.

    Downsampling averages each source window before picking the value, which
    low-passes the signal; plain point-picking would fold high frequencies back
    into the speech band and cost accuracy.
    """
    if audio.rate == rate or not audio.samples:
        return Audio(audio.samples, rate) if audio.rate == rate else audio
    src, ratio = audio.samples, audio.rate / rate
    count = int(len(src) / ratio)
    if count <= 0:
        raise AudioError("That recording was too short to contain a command.")
    out = array("f", bytes(4 * count))
    if ratio > 1:  # downsample: average the window each output sample covers
        for i in range(count):
            a = int(i * ratio)
            b = min(len(src), max(a + 1, int((i + 1) * ratio)))
            out[i] = sum(src[a:b]) / (b - a)
    else:  # upsample: linear interpolation between neighbours
        last = len(src) - 1
        for i in range(count):
            pos = i * ratio
            a = int(pos)
            frac = pos - a
            nxt = src[a + 1] if a < last else src[last]
            out[i] = src[a] * (1.0 - frac) + nxt * frac
    return Audio(out, rate)


def prepare(data: bytes, rate: int = TARGET_RATE) -> Audio:
    """WAV bytes -> mono audio at `rate`, ready for a recogniser."""
    return resample(from_wav(data), rate)


def to_pcm16(audio: Audio) -> bytes:
    """Mono floats -> little-endian 16-bit PCM, for engines that want bytes."""
    out = array("h", bytes(2 * len(audio.samples)))
    for i, s in enumerate(audio.samples):
        v = int(s * 32767.0)
        out[i] = -32768 if v < -32768 else (32767 if v > 32767 else v)
    if sys_is_big_endian():  # pragma: no cover
        out.byteswap()
    return out.tobytes()


def write_wav(audio: Audio, width: int = 2) -> bytes:
    """Mono audio -> WAV bytes (tests and the optional, opt-in save-a-recording path)."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(width)
        w.setframerate(audio.rate)
        w.writeframes(to_pcm16(audio))
    return buf.getvalue()
