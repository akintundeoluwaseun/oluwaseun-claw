"""Cutting a clip, pulling the sound out, grabbing a still, making it sendable.

media_tools already reshapes a video, finds black frames, cuts silence and
evens out loudness. What was missing is the handful of things people do to a
video every week and otherwise need an editor for:

  trim_video     the thirty seconds that matter, not the whole eight minutes
  extract_audio  the sound on its own, for a podcast, a voice note, a transcript
  grab_frame     one still, for a thumbnail or to show somebody
  shrink_video   small enough for WhatsApp, which stops at about 16 MB

All on PyAV, FFmpeg's libraries, already inside S-CLAW: no editor and no
ffmpeg.exe to install. Every result is a NEW file, reopened and measured
before anything is reported - the length, the size, the picture.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from pydantic import Field, field_validator

from claw.agent.schemas import Capability
from claw.permissions.policy import RiskLevel
from claw.tools.base import ToolArgs, ToolContext, ToolError, ToolRegistry, ToolResult, ToolSpec
from claw.tools.media_tools import AUDIO, VIDEO, _input, _out, _probe

#: WhatsApp refuses much over this, and e-mail is not far behind.
WHATSAPP_BYTES = 16 * 1024 * 1024
#: Longer than this and re-encoding takes long enough to feel broken.
MAX_SECONDS = 2 * 60 * 60


def parse_time(text: str | float | int) -> float:
    """"90", "1:30", "01:02:03" or "1m30s" into seconds.

    People write a time into a video the way it appears on the player, so all
    of these have to work. A number on its own is seconds.
    """
    if isinstance(text, (int, float)):
        value = float(text)
        if value < 0:
            raise ToolError("A time cannot be negative.")
        return value
    raw = str(text).strip().lower().replace(" ", "")
    if not raw:
        raise ToolError("Give a time, like 30, 1:30 or 00:01:30.")
    if re.fullmatch(r"\d+(\.\d+)?", raw):
        return float(raw)
    if ":" in raw:
        parts = raw.split(":")
        if len(parts) > 3 or not all(re.fullmatch(r"\d+(\.\d+)?", p) for p in parts if p != ""):
            raise ToolError(f"'{text}' is not a time. Write it like 30, 1:30 or 00:01:30.")
        total = 0.0
        for p in parts:
            total = total * 60 + float(p or 0)
        return total
    m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s)?", raw)
    if m and any(m.groups()):
        h, mi, se = (float(g) if g else 0.0 for g in m.groups())
        return h * 3600 + mi * 60 + se
    raise ToolError(f"'{text}' is not a time. Write it like 30, 1:30 or 00:01:30.")


def _clock(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    m, s = divmod(int(round(seconds)), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


# ---------- trim ----------
class TrimArgs(ToolArgs):
    path: str = Field(min_length=1, max_length=500)
    start: str = Field(default="0", max_length=20, description='Where to start, e.g. "0", "1:30"')
    end: str = Field(default="", max_length=20, description='Where to stop; leave out for the end')
    seconds: float | None = Field(default=None, gt=0, le=MAX_SECONDS,
                                  description="Or how long the clip should be, from the start point")
    file_name: str = Field(default="", max_length=120)


async def trim_video(args: TrimArgs, ctx: ToolContext) -> ToolResult:
    src = _input(ctx, args.path, VIDEO | AUDIO)
    before = await asyncio.to_thread(_probe, src)
    length = before.get("seconds") or 0.0

    start = parse_time(args.start)
    if args.end and args.seconds:
        raise ToolError("Give an end time or a length, not both.")
    if args.end:
        end = parse_time(args.end)
    elif args.seconds:
        end = start + args.seconds
    else:
        end = length or start + 30
    if length and start >= length:
        raise ToolError(f"{src.name} is {_clock(length)} long, so it has nothing at {_clock(start)}.")
    if end <= start:
        raise ToolError(f"The clip would end ({_clock(end)}) before it starts ({_clock(start)}).")
    if length:
        end = min(end, length)

    out = _out(ctx, src, f"{_clock(start).replace(':', '.')}-{_clock(end).replace(':', '.')}",
               src.suffix.lower() if src.suffix.lower() in (".mp4", ".mov", ".mp3", ".wav", ".m4a") else ".mp4")
    if args.file_name:
        out = _out(ctx, src.with_name(args.file_name), "", out.suffix)

    info = await asyncio.to_thread(_cut, src, out, start, end)
    wanted = end - start
    ok = abs(info["seconds"] - wanted) <= max(1.0, wanted * 0.1)
    ctx.memory.outputs.append({"path": str(out), "kind": "video", "verified": ok, "note": ""})
    return ToolResult(
        True,
        f"Cut {_clock(start)} to {_clock(end)} out of {src.name} into {out.name}: "
        f"{info['seconds']} s"
        + (", sound kept" if info.get("audio") else "")
        + (". Reopened and measured." if ok
           else f". WARNING: asked for {round(wanted, 2)} s and the file is {info['seconds']} s.")
        + f" {src.name} is unchanged.",
        {"path": str(out), "start": start, "end": end, **info}, verified=ok)


def _cut(src: Path, out: Path, start: float, end: float) -> dict:
    """Re-encode the wanted span. Slower than copying, and exact.

    Copying the packets straight across is faster but can only start on a
    keyframe, so "from 1:30" silently becomes "from 1:27" - or the clip opens
    on a grey smear. For clips of the length people actually ask for,
    correctness is worth the seconds.
    """
    import av  # noqa: PLC0415

    with av.open(str(src)) as inp:
        v_in = inp.streams.video[0] if inp.streams.video else None
        a_in = inp.streams.audio[0] if inp.streams.audio else None
        if v_in is None and a_in is None:
            raise ToolError(f"{src.name} has neither picture nor sound.")

        with av.open(str(out), "w") as outp:
            v_out = a_out = None
            if v_in is not None:
                rate = v_in.average_rate or 25
                v_out = outp.add_stream("libx264", rate=rate)
                v_out.width, v_out.height = v_in.codec_context.width, v_in.codec_context.height
                v_out.pix_fmt = "yuv420p"
            if a_in is not None:
                a_out = outp.add_stream("aac", rate=a_in.codec_context.sample_rate or 44100)

            # Timestamps are set by hand rather than left to PyAV.
            # Clearing pts and letting the encoder invent them looked right on
            # one test video and collapsed on another: every frame came out
            # with the same timestamp, so a three-second cut of an
            # eight-second advert saved as a 0.1-second file. (The tool said
            # so - it measures what it wrote - but it was still wrong.) The
            # frames are counted instead, which does not depend on how the
            # source happened to be encoded.
            from fractions import Fraction  # noqa: PLC0415
            if v_out is not None:
                v_out.codec_context.time_base = Fraction(1, int(round(float(rate))) or 25)
            v_n = a_n = 0
            sample_rate = (a_in.codec_context.sample_rate or 44100) if a_in is not None else 44100

            inp.seek(max(0, int((start - 1) * 1_000_000)))      # a little before, then skip
            for frame in inp.decode(*(s for s in (v_in, a_in) if s is not None)):
                when = float(frame.time or 0)
                if when < start:
                    continue
                if when >= end:
                    break
                if isinstance(frame, av.VideoFrame) and v_out is not None:
                    frame.pts = v_n
                    frame.time_base = v_out.codec_context.time_base
                    v_n += 1
                    for p in v_out.encode(frame):
                        outp.mux(p)
                elif isinstance(frame, av.AudioFrame) and a_out is not None:
                    frame.pts = a_n
                    frame.time_base = Fraction(1, sample_rate)
                    a_n += frame.samples
                    for p in a_out.encode(frame):
                        outp.mux(p)
            for stream in (v_out, a_out):
                if stream is not None:
                    for p in stream.encode():
                        outp.mux(p)
    return _probe(out)


# ---------- the sound on its own ----------
class ExtractAudioArgs(ToolArgs):
    path: str = Field(min_length=1, max_length=500)
    format: str = Field(default="mp3", description="mp3, m4a or wav")
    file_name: str = Field(default="", max_length=120)

    @field_validator("format")
    @classmethod
    def _known(cls, v: str) -> str:
        text = str(v).strip().lower().lstrip(".")
        if text not in ("mp3", "m4a", "wav"):
            raise ValueError("Format is mp3, m4a or wav.")
        return text


CODEC_FOR = {"mp3": "libmp3lame", "m4a": "aac", "wav": "pcm_s16le"}


async def extract_audio(args: ExtractAudioArgs, ctx: ToolContext) -> ToolResult:
    src = _input(ctx, args.path, VIDEO)
    before = await asyncio.to_thread(_probe, src)
    if not before.get("audio"):
        raise ToolError(f"{src.name} has no sound in it, so there is nothing to take out.")
    out = _out(ctx, src, "sound", f".{args.format}")

    def work():
        import av  # noqa: PLC0415
        with av.open(str(src)) as inp, av.open(str(out), "w") as outp:
            a_in = inp.streams.audio[0]
            sample_rate = a_in.codec_context.sample_rate or 44100
            a_out = outp.add_stream(CODEC_FOR[args.format], rate=sample_rate)
            # Counted, not left to the encoder: see the note in _cut.
            from fractions import Fraction  # noqa: PLC0415
            n = 0
            for frame in inp.decode(a_in):
                frame.pts = n
                frame.time_base = Fraction(1, sample_rate)
                n += frame.samples
                for p in a_out.encode(frame):
                    outp.mux(p)
            for p in a_out.encode():
                outp.mux(p)
        return _probe(out)

    info = await asyncio.to_thread(work)
    ok = info["seconds"] > 0 and abs(info["seconds"] - (before.get("seconds") or 0)) <= max(
        1.0, (before.get("seconds") or 0) * 0.1)
    ctx.memory.outputs.append({"path": str(out), "kind": "audio", "verified": ok, "note": ""})
    return ToolResult(
        True,
        f"Took the sound out of {src.name} into {out.name}: {_clock(info['seconds'])}, "
        f"{info['bytes'] / 2**20:,.1f} MB."
        + (" Reopened and measured." if ok else " WARNING: the length does not match the video.")
        + f" {src.name} is unchanged.",
        {"path": str(out), **info}, verified=ok)


# ---------- one still ----------
class FrameArgs(ToolArgs):
    path: str = Field(min_length=1, max_length=500)
    at: str = Field(default="0", max_length=20, description='When, e.g. "5" or "1:30"')
    file_name: str = Field(default="", max_length=120)


async def grab_frame(args: FrameArgs, ctx: ToolContext) -> ToolResult:
    src = _input(ctx, args.path, VIDEO)
    before = await asyncio.to_thread(_probe, src)
    when = parse_time(args.at)
    length = before.get("seconds") or 0.0
    if length and when >= length:
        raise ToolError(f"{src.name} is {_clock(length)} long, so there is no picture at {_clock(when)}.")
    out = _out(ctx, src, f"at {_clock(when).replace(':', '.')}", ".png")

    def work():
        import av  # noqa: PLC0415
        with av.open(str(src)) as inp:
            stream = inp.streams.video[0]
            inp.seek(max(0, int(when * 1_000_000)))
            for frame in inp.decode(stream):
                if float(frame.time or 0) >= when - 0.5:
                    frame.to_image().save(out, "PNG")
                    return float(frame.time or 0)
        raise ToolError(f"Claw could not read a picture at {_clock(when)} in {src.name}.")

    got = await asyncio.to_thread(work)
    from PIL import Image  # noqa: PLC0415
    with Image.open(out) as img:
        size = img.size
    ok = out.is_file() and size[0] > 0
    ctx.memory.outputs.append({"path": str(out), "kind": "image", "verified": ok, "note": ""})
    return ToolResult(
        ok,
        f"Saved the picture at {_clock(got)} of {src.name} as {out.name} ({size[0]}x{size[1]}). "
        f"Reopened it to check. {src.name} is unchanged.",
        {"path": str(out), "at": got, "width": size[0], "height": size[1]}, verified=ok)


# ---------- small enough to send ----------
class ShrinkVideoArgs(ToolArgs):
    path: str = Field(min_length=1, max_length=500)
    #: 0.1 MB, not 1: some mail gateways and embedding limits are tighter
    #: than a megabyte, and there is no reason to refuse a smaller target.
    target_mb: float = Field(default=16, ge=0.1, le=500, description="How big it may be, in MB")
    file_name: str = Field(default="", max_length=120)


async def shrink_video(args: ShrinkVideoArgs, ctx: ToolContext) -> ToolResult:
    src = _input(ctx, args.path, VIDEO)
    before = await asyncio.to_thread(_probe, src)
    target = args.target_mb * 1024 * 1024
    if before["bytes"] <= target:
        return ToolResult(
            True,
            f"{src.name} is already {before['bytes'] / 2**20:,.1f} MB, which is under "
            f"{args.target_mb:g} MB. Nothing was made.",
            {"path": str(src), **before}, verified=True)
    seconds = before.get("seconds") or 0.0
    if seconds <= 0:
        raise ToolError(f"Claw could not read how long {src.name} is, so it cannot work out a size.")
    out = _out(ctx, src, "small", ".mp4")

    # Budget: 92% of the target for the picture, the rest for the sound and
    # the container's own overhead. Aiming at exactly the limit overshoots it.
    audio_bits = 64_000 if before.get("audio") else 0
    video_bits = max(120_000, int((target * 8 * 0.92) / seconds) - audio_bits)

    def work():
        import av  # noqa: PLC0415
        with av.open(str(src)) as inp, av.open(str(out), "w") as outp:
            v_in = inp.streams.video[0]
            a_in = inp.streams.audio[0] if inp.streams.audio else None
            w, h = v_in.codec_context.width, v_in.codec_context.height
            # 720p is plenty for a phone, and halves the work on a big file.
            if max(w, h) > 1280:
                scale = 1280 / max(w, h)
                w, h = int(w * scale) // 2 * 2, int(h * scale) // 2 * 2
            v_out = outp.add_stream("libx264", rate=v_in.average_rate or 25)
            v_out.width, v_out.height, v_out.pix_fmt = w, h, "yuv420p"
            v_out.bit_rate = video_bits
            a_out = outp.add_stream("aac", rate=a_in.codec_context.sample_rate or 44100) if a_in else None
            if a_out is not None:
                a_out.bit_rate = audio_bits
            from fractions import Fraction  # noqa: PLC0415
            fps = int(round(float(v_in.average_rate or 25))) or 25
            v_out.codec_context.time_base = Fraction(1, fps)
            sample_rate = (a_in.codec_context.sample_rate or 44100) if a_in is not None else 44100
            v_n = a_n = 0
            for frame in inp.decode(*(s for s in (v_in, a_in) if s is not None)):
                if isinstance(frame, av.VideoFrame):
                    frame = frame.reformat(width=w, height=h, format="yuv420p")
                    frame.pts = v_n
                    frame.time_base = v_out.codec_context.time_base
                    v_n += 1
                    for p in v_out.encode(frame):
                        outp.mux(p)
                elif a_out is not None:
                    frame.pts = a_n
                    frame.time_base = Fraction(1, sample_rate)
                    a_n += frame.samples
                    for p in a_out.encode(frame):
                        outp.mux(p)
            for stream in (v_out, a_out):
                if stream is not None:
                    for p in stream.encode():
                        outp.mux(p)
        return _probe(out)

    info = await asyncio.to_thread(work)
    under = info["bytes"] <= target
    ok = under and info["seconds"] > 0
    ctx.memory.outputs.append({"path": str(out), "kind": "video", "verified": ok, "note": ""})
    saved = round((before["bytes"] - info["bytes"]) * 100 / before["bytes"])
    return ToolResult(
        True,
        f"{src.name}: {before['bytes'] / 2**20:,.1f} MB down to {info['bytes'] / 2**20:,.1f} MB "
        f"({saved}% smaller), {info.get('width')}x{info.get('height')}, {_clock(info['seconds'])}, "
        f"saved as {out.name}."
        + (" It is under the limit; measured from the saved file." if under
           else f" WARNING: it is still over {args.target_mb:g} MB. A longer video may need to be cut shorter.")
        + f" {src.name} is unchanged.",
        {"path": str(out), "bytes_before": before["bytes"], **info}, verified=ok)


def register_clip_tools(reg: ToolRegistry) -> None:
    M, W = Capability.DESIGN, RiskLevel.LOCAL_WRITE
    reg.register(ToolSpec(
        "trim_video", "Cut a piece out of a video or recording into a new file, by start and end time.",
        M, W, TrimArgs, trim_video))
    reg.register(ToolSpec(
        "extract_audio", "Save the sound of a video as an mp3, m4a or wav.", M, W,
        ExtractAudioArgs, extract_audio))
    reg.register(ToolSpec(
        "grab_frame", "Save one picture from a video, for a thumbnail or to show somebody.",
        M, W, FrameArgs, grab_frame))
    reg.register(ToolSpec(
        "shrink_video", "Make a video small enough to send on WhatsApp or by e-mail.",
        M, W, ShrinkVideoArgs, shrink_video))
