"""Cutting a clip, taking the sound out, grabbing a still, shrinking to send.

The four things people do to a video every week that otherwise need an
editor. All through PyAV, which S-CLAW already ships.

Each test measures the file that came out - its length, its size, its
picture - rather than trusting what the tool said about it.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from claw.tools.base import ToolError
from claw.tools.clip_tools import parse_time
from tests.test_phase_a import call


def folder(ctx, name="Videos"):
    d = Path(ctx.settings.permissions.authorized_folders[0]) / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def make_video(path: Path, seconds: int = 6, with_sound: bool = True,
               width: int = 640, height: int = 480) -> None:
    """A real encoded video: moving picture, and a tone if asked for."""
    import math

    import av
    import numpy as np
    from PIL import Image

    rate = 24
    with av.open(str(path), "w") as c:
        v = c.add_stream("libx264", rate=rate)
        v.width, v.height, v.pix_fmt = width, height, "yuv420p"
        a = None
        if with_sound:
            a = c.add_stream("aac", rate=44100)
        for n in range(seconds * rate):
            # The colour changes with time, so a frame grabbed at 4 s is
            # visibly different from one at 1 s.
            shade = int(255 * n / (seconds * rate))
            img = Image.new("RGB", (width, height), (shade, 60, 255 - shade))
            for p in v.encode(av.VideoFrame.from_image(img)):
                c.mux(p)
        if a is not None:
            total = seconds * 44100
            t = np.arange(total, dtype=np.float32) / 44100.0
            wave = (np.sin(2 * math.pi * 440 * t) * 8000).astype(np.int16)
            for start in range(0, total, 1024):
                chunk = wave[start:start + 1024]
                if not len(chunk):
                    break
                frame = av.AudioFrame.from_ndarray(
                    chunk.reshape(1, -1), format="s16", layout="mono")
                frame.sample_rate = 44100
                frame.pts = None
                for p in a.encode(frame):
                    c.mux(p)
            for p in a.encode():
                c.mux(p)
        for p in v.encode():
            c.mux(p)


def seconds_of(path: Path) -> float:
    import av
    with av.open(str(path)) as c:
        return float(c.duration / 1_000_000) if c.duration else 0.0


def digest(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ---------- reading a time the way a person writes it ----------
def test_a_time_can_be_written_the_way_the_player_shows_it():
    assert parse_time("30") == 30
    assert parse_time(30) == 30
    assert parse_time("1:30") == 90
    assert parse_time("01:02:03") == 3723
    assert parse_time("2m30s") == 150
    assert parse_time("1h5m") == 3900
    assert parse_time("0") == 0


def test_a_time_that_is_not_a_time_is_refused():
    for bad in ("about a minute", "", "1:2:3:4", "soon"):
        with pytest.raises(ToolError, match="(?i)not a time|give a time"):
            parse_time(bad)


# ---------- trimming ----------
async def test_trimming_takes_the_span_asked_for(tool_ctx):
    d = folder(tool_ctx)
    make_video(d / "promo.mp4", seconds=6)
    before = digest(d / "promo.mp4")

    r = await call(tool_ctx, "trim_video", path=str(d / "promo.mp4"), start="1", end="3")
    out = Path(r.data["path"])
    assert out.is_file()
    assert 1.5 <= seconds_of(out) <= 2.6, f"asked for 2 s, got {seconds_of(out)}"
    assert digest(d / "promo.mp4") == before, "the original was changed"


async def test_trimming_accepts_a_length_instead_of_an_end(tool_ctx):
    d = folder(tool_ctx)
    make_video(d / "clip.mp4", seconds=6)
    r = await call(tool_ctx, "trim_video", path=str(d / "clip.mp4"), start="0:01", seconds=2)
    assert 1.5 <= seconds_of(Path(r.data["path"])) <= 2.6


async def test_a_backwards_or_impossible_clip_is_refused(tool_ctx):
    d = folder(tool_ctx)
    make_video(d / "clip.mp4", seconds=4)
    with pytest.raises(ToolError, match="before it starts"):
        await call(tool_ctx, "trim_video", path=str(d / "clip.mp4"), start="3", end="1")
    with pytest.raises(ToolError, match="nothing at"):
        await call(tool_ctx, "trim_video", path=str(d / "clip.mp4"), start="30", end="40")
    with pytest.raises(ToolError, match="not both"):
        await call(tool_ctx, "trim_video", path=str(d / "clip.mp4"), start="0", end="2", seconds=2)


async def test_an_end_past_the_video_is_pulled_back_not_refused(tool_ctx):
    """"from 3 seconds to the end" is a normal thing to ask for."""
    d = folder(tool_ctx)
    make_video(d / "clip.mp4", seconds=5)
    r = await call(tool_ctx, "trim_video", path=str(d / "clip.mp4"), start="3", end="99")
    assert 1.0 <= seconds_of(Path(r.data["path"])) <= 2.6


# ---------- the sound on its own ----------
async def test_the_sound_comes_out_at_the_right_length(tool_ctx):
    d = folder(tool_ctx)
    make_video(d / "talk.mp4", seconds=5, with_sound=True)
    before = digest(d / "talk.mp4")

    r = await call(tool_ctx, "extract_audio", path=str(d / "talk.mp4"), format="mp3")
    out = Path(r.data["path"])
    assert out.suffix == ".mp3" and out.stat().st_size > 0
    assert abs(seconds_of(out) - 5) <= 1.0, f"the sound is {seconds_of(out)} s, the video is 5"
    assert digest(d / "talk.mp4") == before


async def test_a_silent_video_says_there_is_no_sound(tool_ctx):
    """Rather than writing an empty file and calling it done."""
    d = folder(tool_ctx)
    make_video(d / "silent.mp4", seconds=3, with_sound=False)
    with pytest.raises(ToolError, match="no sound"):
        await call(tool_ctx, "extract_audio", path=str(d / "silent.mp4"))


async def test_an_unknown_audio_format_is_refused(tool_ctx):
    d = folder(tool_ctx)
    make_video(d / "a.mp4", seconds=2)
    with pytest.raises(Exception, match="(?i)mp3, m4a or wav"):
        await call(tool_ctx, "extract_audio", path=str(d / "a.mp4"), format="flac")


# ---------- one still ----------
async def test_a_still_is_taken_from_the_moment_asked_for(tool_ctx):
    from PIL import Image
    d = folder(tool_ctx)
    make_video(d / "promo.mp4", seconds=6)

    early = await call(tool_ctx, "grab_frame", path=str(d / "promo.mp4"), at="0")
    late = await call(tool_ctx, "grab_frame", path=str(d / "promo.mp4"), at="5")
    for r in (early, late):
        assert Path(r.data["path"]).suffix == ".png"
        assert r.data["width"] == 640 and r.data["height"] == 480

    # The picture changes through the video, so two different moments must
    # not give the same image. Otherwise "at" is being ignored.
    a = Image.open(early.data["path"]).convert("RGB").getpixel((320, 240))
    b = Image.open(late.data["path"]).convert("RGB").getpixel((320, 240))
    assert a != b, f"the same picture came back for 0 s and 5 s ({a})"


async def test_a_still_past_the_end_is_refused(tool_ctx):
    d = folder(tool_ctx)
    make_video(d / "short.mp4", seconds=3)
    with pytest.raises(ToolError, match="no picture at"):
        await call(tool_ctx, "grab_frame", path=str(d / "short.mp4"), at="2:00")


# ---------- small enough to send ----------
async def test_a_video_already_small_enough_is_left_alone(tool_ctx):
    """No new file, and no pretending work was done."""
    d = folder(tool_ctx)
    make_video(d / "tiny.mp4", seconds=2)
    before = sorted(p.name for p in d.iterdir())
    r = await call(tool_ctx, "shrink_video", path=str(d / "tiny.mp4"), target_mb=16)
    assert r.ok and "already" in r.summary
    assert sorted(p.name for p in d.iterdir()) == before, "a file was written anyway"


async def test_shrinking_gets_under_the_limit_and_keeps_the_length(tool_ctx):
    d = folder(tool_ctx)
    make_video(d / "big.mp4", seconds=6, width=1920, height=1080)
    size_before = (d / "big.mp4").stat().st_size
    target_mb = max(0.1, size_before / 2**20 / 3)        # a third of what it is now

    r = await call(tool_ctx, "shrink_video", path=str(d / "big.mp4"), target_mb=target_mb)
    out = Path(r.data["path"])
    assert out.is_file()
    assert out.stat().st_size < size_before, "it did not get smaller"
    assert abs(seconds_of(out) - 6) <= 1.2, "shrinking changed how long it is"
    assert (d / "big.mp4").stat().st_size == size_before, "the original was changed"
