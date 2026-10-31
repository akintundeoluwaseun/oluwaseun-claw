"""Turn a voice note (OGG/Opus from Telegram or WhatsApp, M4A, MP3...) into the 16 kHz mono WAV
the offline recogniser reads. PyAV (BSD-3, bundles FFmpeg's decoders) does the decoding."""

from __future__ import annotations

import io
import wave

MAX_SECONDS = 120


def to_wav16k(data: bytes) -> bytes:
    import av
    import numpy as np

    out = io.BytesIO()
    with av.open(io.BytesIO(data)) as container:
        stream = next(s for s in container.streams if s.type == "audio")
        res = av.AudioResampler(format="s16", layout="mono", rate=16000)
        chunks = []
        total = 0
        for frame in container.decode(stream):
            for f in res.resample(frame):
                a = f.to_ndarray().reshape(-1)
                chunks.append(a)
                total += a.size
                if total > MAX_SECONDS * 16000:
                    raise ValueError(f"The voice note is longer than {MAX_SECONDS // 60} minutes.")
        for f in res.resample(None):
            chunks.append(f.to_ndarray().reshape(-1))
    pcm = np.concatenate(chunks).astype("<i2").tobytes() if chunks else b""
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(pcm)
    return out.getvalue()
