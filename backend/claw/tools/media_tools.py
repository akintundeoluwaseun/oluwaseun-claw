"""Milestone 7 (sections 2 and 14): video and audio jobs done by code, not by clicking an editor.

Everything goes through PyAV (FFmpeg's libraries, already inside S-CLAW): no ffmpeg.exe and no
editor are needed. Every result is a NEW file, reopened and measured before S-CLAW says it is done:
size and length for video, length and loudness for audio.

  reformat_video     9:16 / 1:1 / 16:9 versions, by cropping the middle or adding bars
  find_black_frames  where the picture goes black (and for how long)
  cut_silence        an audio recording with its silent gaps removed
  normalize_audio    several recordings brought to the same loudness
"""

from __future__ import annotations

import asyncio
import math
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator

from claw.agent.schemas import Capability
from claw.permissions.policy import PathNotAuthorized, RiskLevel
from claw.tools.base import ToolArgs, ToolContext, ToolError, ToolRegistry, ToolResult, ToolSpec
from claw.tools.file_tools import safe_file_name, unique_path

VIDEO = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
AUDIO = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".flac"}
SHAPES = {"9:16": (1080, 1920), "1:1": (1080, 1080), "16:9": (1920, 1080), "4:5": (1080, 1350)}


def _input(ctx: ToolContext, raw: str, kinds: set[str]) -> Path:
    try:
        p = ctx.policy.check_path(raw)
    except PathNotAuthorized as exc:
        raise ToolError(str(exc)) from exc
    if not p.is_file():
        from claw.tools.table_tools import find_table  # noqa: PLC0415 - same lookup by file name
        try:
            p = find_table(ctx, raw)
        except ToolError:
            raise ToolError(f"There is no file '{raw}'.") from None
    if p.suffix.lower() not in kinds:
        raise ToolError(f"{p.name} is not a supported {'video' if kinds is VIDEO else 'audio'} file.")
    ctx.memory.note_file(p)
    return p


def _out(ctx: ToolContext, src: Path, suffix: str, ext: str) -> Path:
    out = unique_path(src.parent / safe_file_name(f"{src.stem} {suffix}", ext))
    ctx.policy.check_path(out, write=True)
    return out


# ---------- reformat_video ----------
class ReformatArgs(ToolArgs):
    path: str = Field(min_length=1, max_length=500)
    shape: Literal["9:16", "1:1", "16:9", "4:5"] = "9:16"
    fit: Literal["crop", "bars"] = Field(default="crop", description="crop the middle, or add bars")
    max_seconds: float | None = Field(default=None, ge=1, le=3600)


def _reformat(src: Path, out: Path, shape: str, fit: str, max_s: float | None) -> dict:
    import av  # noqa: PLC0415
    from PIL import Image  # noqa: PLC0415

    W, H = SHAPES[shape]
    with av.open(str(src)) as inp, av.open(str(out), "w") as outp:
        vin = inp.streams.video[0]
        ain = inp.streams.audio[0] if inp.streams.audio else None
        rate = vin.average_rate or 30
        vout = outp.add_stream("libx264", rate=rate)
        vout.width, vout.height, vout.pix_fmt = W, H, "yuv420p"
        vout.options = {"crf": "21", "preset": "veryfast"}
        aout = None
        if ain is not None:
            aout = outp.add_stream("aac", rate=ain.codec_context.sample_rate or 44100)
        streams = [vin] + ([ain] if ain is not None else [])
        for packet in inp.demux(*streams):
            for frame in packet.decode():
                t = float(frame.time or 0)
                if max_s and t > max_s:
                    continue
                if packet.stream.type == "video":
                    img = frame.to_image()
                    if fit == "crop":
                        scale = max(W / img.width, H / img.height)
                        img = img.resize((math.ceil(img.width * scale), math.ceil(img.height * scale)), Image.LANCZOS)
                        left, top = (img.width - W) // 2, (img.height - H) // 2
                        img = img.crop((left, top, left + W, top + H))
                    else:
                        scale = min(W / img.width, H / img.height)
                        img = img.resize((max(2, int(img.width * scale)), max(2, int(img.height * scale))), Image.LANCZOS)
                        canvas = Image.new("RGB", (W, H), (0, 0, 0))
                        canvas.paste(img, ((W - img.width) // 2, (H - img.height) // 2))
                        img = canvas
                    vf = av.VideoFrame.from_image(img)
                    for p in vout.encode(vf):
                        outp.mux(p)
                elif aout is not None:
                    frame.pts = None
                    for p in aout.encode(frame):
                        outp.mux(p)
        for p in vout.encode():
            outp.mux(p)
        if aout is not None:
            for p in aout.encode():
                outp.mux(p)
    return _probe(out)


def _probe(path: Path) -> dict:
    import av  # noqa: PLC0415
    with av.open(str(path)) as c:
        info = {"seconds": round(float(c.duration / 1_000_000), 2) if c.duration else 0.0, "bytes": path.stat().st_size}
        if c.streams.video:
            v = c.streams.video[0].codec_context
            info.update(width=v.width, height=v.height)
        info["audio"] = bool(c.streams.audio)
    return info


async def reformat_video(args: ReformatArgs, ctx: ToolContext) -> ToolResult:
    src = _input(ctx, args.path, VIDEO)
    before = await asyncio.to_thread(_probe, src)
    out = _out(ctx, src, args.shape.replace(":", "x"), ".mp4")
    info = await asyncio.to_thread(_reformat, src, out, args.shape, args.fit, args.max_seconds)
    W, H = SHAPES[args.shape]
    want = min(before["seconds"], args.max_seconds or before["seconds"])
    ok = (info.get("width"), info.get("height")) == (W, H) and abs(info["seconds"] - want) <= 1.0 and info["audio"] == before["audio"]
    ctx.memory.outputs.append({"path": str(out), "kind": "video", "verified": ok, "note": ""})
    return ToolResult(True, f"Saved {out.name}: {W}×{H} ({args.shape}, {'cropped to the middle' if args.fit == 'crop' else 'with bars'}), "
                            f"{info['seconds']} s{', sound kept' if info['audio'] else ''}. Reopened and measured; the original is untouched.",
                      {"path": str(out), **info}, verified=ok)


# ---------- find_black_frames ----------
class BlackArgs(ToolArgs):
    path: str = Field(min_length=1, max_length=500)
    min_seconds: float = Field(default=0.2, ge=0.04, le=60)


def _black(src: Path, min_s: float) -> tuple[list[tuple[float, float]], float]:
    import av  # noqa: PLC0415
    spans, start, last, dur = [], None, 0.0, 0.0
    with av.open(str(src)) as c:
        v = c.streams.video[0]
        v.thread_type = "AUTO"
        for frame in c.decode(v):
            t = float(frame.time or 0)
            g = frame.to_ndarray(format="gray") if hasattr(frame, "to_ndarray") else None
            mean = float(g.mean()) if g is not None else sum(frame.to_image().convert("L").getdata()) / (frame.width * frame.height)
            dark = mean < 16
            if dark and start is None:
                start = t
            if not dark and start is not None:
                if t - start >= min_s:
                    spans.append((round(start, 2), round(t, 2)))
                start = None
            last = t
        dur = float(c.duration / 1_000_000) if c.duration else last
    if start is not None and dur - start >= min_s:
        spans.append((round(start, 2), round(dur, 2)))
    return spans, dur


async def find_black_frames(args: BlackArgs, ctx: ToolContext) -> ToolResult:
    src = _input(ctx, args.path, VIDEO)
    spans, dur = await asyncio.to_thread(_black, src, args.min_seconds)
    where = "; ".join(f"{a:.2f}–{b:.2f} s" for a, b in spans[:20])
    return ToolResult(True, f"{src.name} ({dur:.1f} s): {len(spans)} black stretch(es)" + (f" at {where}." if spans else "."),
                      {"black": spans, "seconds": dur}, True)


# ---------- audio helpers ----------
def _read_audio(src: Path):
    import av  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415 - comes with PyAV's to_ndarray
    chunks, rate = [], 44100
    with av.open(str(src)) as c:
        a = c.streams.audio[0]
        rate = a.codec_context.sample_rate or 44100
        res = av.AudioResampler(format="flt", layout="mono", rate=rate)
        for frame in c.decode(a):
            for f in res.resample(frame):
                chunks.append(f.to_ndarray().reshape(-1))
        for f in res.resample(None):
            chunks.append(f.to_ndarray().reshape(-1))
    return (np.concatenate(chunks) if chunks else np.zeros(0, dtype="float32")), rate


def _write_wav(samples, rate: int, out: Path) -> None:
    import wave  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2")
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def _db(x) -> float:
    import numpy as np  # noqa: PLC0415
    rms = float(np.sqrt(np.mean(np.square(x)))) if len(x) else 0.0
    return 20 * math.log10(rms) if rms > 0 else -120.0


# ---------- cut_silence ----------
class SilenceArgs(ToolArgs):
    path: str = Field(min_length=1, max_length=500)
    min_silence: float = Field(default=0.7, ge=0.2, le=10, description="Seconds of quiet to cut")
    keep: float = Field(default=0.15, ge=0, le=1, description="Seconds of quiet left around speech")


def _cut(src: Path, out: Path, min_sil: float, keep: float) -> tuple[float, float, int]:
    import numpy as np  # noqa: PLC0415
    x, rate = _read_audio(src)
    win = int(rate * 0.02)
    n = len(x) // win
    if n == 0:
        raise ToolError("The recording is empty.")
    frames = x[: n * win].reshape(n, win)
    level = 20 * np.log10(np.sqrt(np.mean(frames ** 2, axis=1)) + 1e-9)
    speech_floor = np.percentile(level, 90)
    quiet = level < max(-45.0, speech_floor - 30.0)
    keep_mask = np.ones(n, dtype=bool)
    i, cuts = 0, 0
    min_w, pad = int(min_sil / 0.02), int(keep / 0.02)
    while i < n:
        if quiet[i]:
            j = i
            while j < n and quiet[j]:
                j += 1
            if j - i >= min_w:
                keep_mask[i + pad: j - pad] = False
                cuts += 1
            i = j
        else:
            i += 1
    y = frames[keep_mask].reshape(-1)
    _write_wav(y, rate, out)
    return len(x) / rate, len(y) / rate, cuts


async def cut_silence(args: SilenceArgs, ctx: ToolContext) -> ToolResult:
    src = _input(ctx, args.path, AUDIO | VIDEO)
    out = _out(ctx, src, "no silences", ".wav")
    before, after, cuts = await asyncio.to_thread(_cut, src, out, args.min_silence, args.keep)
    back = await asyncio.to_thread(_probe, out)
    ok = abs(back["seconds"] - after) <= 0.2 and after <= before
    ctx.memory.outputs.append({"path": str(out), "kind": "audio", "verified": ok, "note": ""})
    return ToolResult(True, f"Saved {out.name}: {cuts} silent gap(s) of {args.min_silence}s or more cut, {before:.1f} s → {after:.1f} s. "
                            "Reopened and measured; the original is untouched.",
                      {"path": str(out), "before": before, "after": after, "cuts": cuts}, verified=ok)


# ---------- normalize_audio ----------
class LoudArgs(ToolArgs):
    paths: list[str] = Field(min_length=1, max_length=30)
    target_db: float = Field(default=-20, ge=-40, le=-6, description="Average loudness to reach (dB)")

    @field_validator("paths", mode="before")
    @classmethod
    def _list(cls, v):
        return [v] if isinstance(v, str) else v


def _normalize(src: Path, out: Path, target: float) -> tuple[float, float]:
    import numpy as np  # noqa: PLC0415
    x, rate = _read_audio(src)
    before = _db(x)
    gain = 10 ** ((target - before) / 20)
    y = x * gain
    peak = float(np.max(np.abs(y))) if len(y) else 0.0
    if peak > 0.98:                                    # never clip: limit the gain instead
        y = y * (0.98 / peak)
    _write_wav(y, rate, out)
    after, _ = _read_audio(out)
    return before, _db(after)


async def normalize_audio(args: LoudArgs, ctx: ToolContext) -> ToolResult:
    results, all_ok = [], True
    for raw in args.paths:
        src = _input(ctx, raw, AUDIO | VIDEO)
        out = _out(ctx, src, "levelled", ".wav")
        before, after = await asyncio.to_thread(_normalize, src, out, args.target_db)
        ok = abs(after - args.target_db) <= 1.5 or after < args.target_db      # quieter only when held back to avoid clipping
        all_ok &= ok
        ctx.memory.outputs.append({"path": str(out), "kind": "audio", "verified": ok, "note": ""})
        results.append((out.name, before, after))
    line = "; ".join(f"{n}: {b:.1f} → {a:.1f} dB" for n, b, a in results)
    return ToolResult(True, f"Levelled {len(results)} recording(s) to about {args.target_db} dB average loudness, measured again after saving: {line}.",
                      {"files": [{"name": n, "before_db": b, "after_db": a} for n, b, a in results]}, verified=all_ok)


def register_media_tools(reg: ToolRegistry) -> None:
    D, W, R = Capability.DOCUMENTS, RiskLevel.LOCAL_WRITE, RiskLevel.READ_ONLY
    reg.register(ToolSpec("reformat_video", "Make a 9:16, 1:1, 4:5 or 16:9 version of a video.", D, W, ReformatArgs, reformat_video))
    reg.register(ToolSpec("find_black_frames", "Find where a video goes black.", D, R, BlackArgs, find_black_frames))
    reg.register(ToolSpec("cut_silence", "Remove silent gaps from a recording.", D, W, SilenceArgs, cut_silence))
    reg.register(ToolSpec("normalize_audio", "Make several recordings equally loud.", D, W, LoudArgs, normalize_audio))
