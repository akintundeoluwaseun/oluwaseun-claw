"""Milestone 7: video shape changes, black frames, silence cutting, loudness - on real media files made here."""

import math
import wave
from pathlib import Path

import av
import numpy as np
from PIL import Image

from tests.test_phase_a import call


def make_video(path: Path, seconds=3, w=640, h=360, fps=10, black=(1.0, 1.6)):
    with av.open(str(path), "w") as c:
        v = c.add_stream("libx264", rate=fps)
        v.width, v.height, v.pix_fmt = w, h, "yuv420p"
        a = c.add_stream("aac", rate=44100)
        for i in range(seconds * fps):
            t = i / fps
            colour = (0, 0, 0) if black[0] <= t < black[1] else (200, 80 + i * 3 % 100, 40)
            for p in v.encode(av.VideoFrame.from_image(Image.new("RGB", (w, h), colour))):
                c.mux(p)
        tone = (0.2 * np.sin(2 * np.pi * 440 * np.arange(44100 * seconds) / 44100)).astype("float32")
        for k in range(0, len(tone), 1024):
            f = av.AudioFrame.from_ndarray(tone[k:k + 1024].reshape(1, -1), format="flt", layout="mono")
            f.sample_rate = 44100
            for p in a.encode(f):
                c.mux(p)
        for s in (v, a):
            for p in s.encode():
                c.mux(p)


def make_speech(path: Path, parts, rate=16000, amp=0.3):
    """parts: [(seconds, loud?)]"""
    x = np.concatenate([(amp * np.sin(2 * np.pi * 220 * np.arange(int(rate * s)) / rate)) if loud
                        else np.zeros(int(rate * s)) for s, loud in parts]).astype("float32")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((x * 32767).astype("<i2").tobytes())


def folder(ctx):
    return Path(ctx.settings.permissions.authorized_folders[0])


async def test_vertical_version_and_black_frames(tool_ctx):
    src = folder(tool_ctx) / "promo.mp4"
    make_video(src)
    r = await call(tool_ctx, "reformat_video", path=str(src), shape="9:16")
    assert r.verified and (r.data["width"], r.data["height"]) == (1080, 1920) and r.data["audio"], r.summary
    r = await call(tool_ctx, "reformat_video", path="promo.mp4", shape="1:1", fit="bars")   # found by name
    assert r.verified and (r.data["width"], r.data["height"]) == (1080, 1080)
    r = await call(tool_ctx, "find_black_frames", path=str(src))
    assert len(r.data["black"]) == 1 and abs(r.data["black"][0][0] - 1.0) < 0.15 and abs(r.data["black"][0][1] - 1.6) < 0.15


async def test_silences_are_cut(tool_ctx):
    src = folder(tool_ctx) / "interview.wav"
    make_speech(src, [(1.0, True), (2.0, False), (1.0, True), (0.3, False), (1.0, True)])
    r = await call(tool_ctx, "cut_silence", path=str(src))
    assert r.verified and r.data["cuts"] == 1 and 3.2 < r.data["after"] < 3.8, r.summary    # 5.3 s -> about 3.6 s


async def test_recordings_are_levelled(tool_ctx):
    quiet, loud = folder(tool_ctx) / "quiet.wav", folder(tool_ctx) / "loud.wav"
    make_speech(quiet, [(2, True)], amp=0.02)
    make_speech(loud, [(2, True)], amp=0.6)
    r = await call(tool_ctx, "normalize_audio", paths=[str(quiet), str(loud)], target_db=-20)
    afters = [f["after_db"] for f in r.data["files"]]
    assert r.verified and all(abs(a + 20) < 1.5 for a in afters), r.summary
