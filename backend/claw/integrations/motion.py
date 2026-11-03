"""Motion graphics: short animated promo videos.

Two makers, and Claw always says which one made the result, as with flyers:
- **After Effects**, when it is installed: driven the way Adobe documents for automation -
  an ExtendScript (.jsx) run with `AfterFX.exe -r script.jsx`. The script builds the
  composition (shape and text layers with eased keyframes), saves an .aep project the
  person can open and change, and renders an MP4 through the render queue.
  NOT YET RUN on a real After Effects (none in the build workspace or on GitHub's machines).
- **Claw's built-in maker** (Pillow frames encoded with PyAV/FFmpeg): works on every
  computer, tested here end to end.

How it controls After Effects matters. Clicking through After Effects' panels from
screenshots is slow and breaks with every layout change; a small local brain cannot do
it reliably. So the brain only fills in the content (words, colours, length); Claw
writes the After Effects script from a fixed, tested template. User text goes into the
script through JSON encoding, so it cannot break out of it.

Every video is a NEW file in an authorized folder, reopened afterwards: its length, size
and frame count are checked, and a frame from the headline scene is read back with OCR.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from claw.integrations import images as im
from claw.integrations.pillow import Image, ImageDraw

SIZES = {"landscape": (1920, 1080), "square": (1080, 1080), "story": (1080, 1920)}
FPS = 30


@dataclass
class MotionSpec:
    title: str
    subtitle: str = ""
    points: list[str] = field(default_factory=list)
    contact: str = ""
    size: tuple[int, int] = SIZES["landscape"]
    background: str = "#14212b"
    accent: str = "#3cc2aa"
    seconds: float = 10.0
    style: str = "slide"  # slide | pop | fade | logo | lower_third
    transparent: bool = False  # lower_third only: a see-through background (.mov with alpha)

    def scenes(self) -> list[tuple[str, float, float]]:
        """(name, start, end) in seconds: the headline, each point, then the contact."""
        parts = ["title"] + [f"point{i}" for i in range(len(self.points[:5]))] + (["contact"] if self.contact else [])
        weights = [1.6] + [1.0] * (len(parts) - 1)
        total, t, out = sum(weights), 0.0, []
        for name, w in zip(parts, weights):
            d = self.seconds * w / total
            out.append((name, t, t + d))
            t += d
        return out

    def title_moment(self) -> float:
        """A time when the headline is fully on screen (for checking the video afterwards)."""
        if self.style in ("logo", "lower_third"):
            return self.seconds * 0.55
        _, s, e = self.scenes()[0]
        return s + (e - s) * 0.6


# ---------- easing ----------
def ease_out(t: float) -> float:
    t = min(max(t, 0.0), 1.0)
    return 1 - (1 - t) ** 3


def ease_back(t: float) -> float:
    t = min(max(t, 0.0), 1.0)
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


def _alpha_in_out(t: float, start: float, end: float, fade: float = 0.35) -> float:
    if t < start or t > end:
        return 0.0
    return min(1.0, (t - start) / fade, (end - t) / fade)


# ---------- built-in maker ----------
def _draw_text(base: Image.Image, text: str, f, xy, colour, alpha: float, max_w: int, max_lines: int = 3) -> int:
    """Text with its own opacity; returns the height used."""
    if alpha <= 0 or not text:
        return 0
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    lines = im._wrap(d, text, f, max_w, max_lines)
    x, y = xy
    line_h = int(f.size * 1.18)
    for i, line in enumerate(lines):
        d.text((x, y + i * line_h), line, font=f, fill=(*colour, int(255 * alpha)))
    base.alpha_composite(layer)
    return line_h * len(lines)


def _fit_inside(draw, text: str, width: int, start: int, max_lines: int):
    """The largest bold font at which the text wraps into max_lines with every line (even one long word) inside width."""
    size = start
    while size > 12:
        f = im.font(size, bold=True)
        lines = im._wrap(draw, text, f, width, 99)
        if len(lines) <= max_lines and all(draw.textlength(l, font=f) <= width for l in lines):
            return f
        size = int(size * 0.92)
    return im.font(12, bold=True)


def logo_name_box(spec: MotionSpec) -> tuple[int, int, int, int]:
    """The area inside the logo ring (OCR reads the name there; the ring itself confuses it)."""
    W, H = spec.size
    cx, cy, r = W // 2, int(H * 0.44), int(min(W, H) * 0.30)
    k = int(r * 0.85)
    return cx - k, cy - k, cx + k, cy + k


def _logo_frame(spec: MotionSpec, t: float) -> Image.Image:
    """Logo reveal: a ring draws itself, the name scales in inside it, the tagline follows, all hold, then fade."""
    W, H = spec.size
    bg, accent = im.hex_rgb(spec.background), im.hex_rgb(spec.accent)
    fg = im._on(bg)
    frame = Image.new("RGBA", (W, H), (*bg, 255))
    out_a = min(1.0, max(0.0, (spec.seconds - t) / 0.6))
    cx, cy, r = W // 2, int(H * 0.44), int(min(W, H) * 0.30)
    ring = ease_out(t / max(spec.seconds * 0.25, 0.1))
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    width = max(6, r // 14)
    if ring > 0:
        d.arc((cx - r, cy - r, cx + r, cy + r), -90, -90 + 360 * ring, fill=(*accent, int(255 * out_a)), width=width)
    frame.alpha_composite(layer)
    k = ease_back((t - spec.seconds * 0.15) / 0.7)
    if k > 0:
        tl = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        td = ImageDraw.Draw(tl)
        full = _fit_inside(td, spec.title, int(r * 1.45), int(min(W, H) * 0.12), 3)  # the whole name, inside the ring
        size = max(8, int(full.size * min(max(k, 0.01), 1.15)))
        f = im.font(size, bold=True)
        lines = im._wrap(td, spec.title, f, int(r * 1.45 * size / full.size) + 1, 3)
        line_h = int(size * 1.15)
        y0 = cy - line_h * len(lines) // 2
        for i, line in enumerate(lines):
            w = td.textlength(line, font=f)
            td.text((cx - w / 2, y0 + i * line_h), line, font=f, fill=(*fg, int(255 * min(1.0, k) * out_a)))
        frame.alpha_composite(tl)
    tag = spec.subtitle or spec.contact
    if tag:
        a = min(1.0, max(0.0, (t - spec.seconds * 0.4) / 0.5)) * out_a
        f = im.font(int(min(W, H) * 0.045))
        tl = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        td = ImageDraw.Draw(tl)
        w = td.textlength(tag, font=f)
        td.text((cx - w / 2, cy + r + int(H * 0.05)), tag, font=f, fill=(*accent, int(255 * a)))
        frame.alpha_composite(tl)
    return frame.convert("RGB")


def lower_third_frame(spec: MotionSpec, t: float) -> Image.Image:
    """A name bar for the bottom of a video: slides in, holds, slides out. RGBA (see-through when transparent)."""
    W, H = spec.size
    bg, accent = im.hex_rgb(spec.background), im.hex_rgb(spec.accent)
    frame = Image.new("RGBA", (W, H), (0, 0, 0, 0) if spec.transparent else (*bg, 255))
    inn = ease_out(t / 0.7)
    out = ease_out((t - (spec.seconds - 0.7)) / 0.7) if t > spec.seconds - 0.7 else 0.0
    k = inn - out
    if k <= 0:
        return frame
    m = int(W * 0.06)
    name_f = im.font(int(H * 0.055), bold=True)
    role_f = im.font(int(H * 0.034))
    d0 = ImageDraw.Draw(frame)
    box_w = int(max(d0.textlength(spec.title, font=name_f), d0.textlength(spec.subtitle or "", font=role_f)) + W * 0.05)
    box_w = min(box_w, W - 2 * m)
    name_h, role_h = int(H * 0.085), int(H * 0.06) if spec.subtitle else 0
    top = H - m - name_h - role_h
    x = int(m - (1 - k) * (box_w + m))
    panel = (20, 20, 20) if im._lum(bg) > 0.5 or spec.transparent else bg
    d = ImageDraw.Draw(frame)
    d.rectangle((x, top, x + int(W * 0.008), top + name_h + role_h), fill=(*accent, 255))
    d.rectangle((x + int(W * 0.008), top, x + box_w, top + name_h), fill=(*panel, 235))
    d.text((x + int(W * 0.025), top + (name_h - name_f.size) // 2 - 2), spec.title, font=name_f, fill=(*im._on(panel), 255))
    if spec.subtitle:
        d.rectangle((x + int(W * 0.008), top + name_h, x + box_w, top + name_h + role_h), fill=(*accent, 235))
        d.text((x + int(W * 0.025), top + name_h + (role_h - role_f.size) // 2 - 2), spec.subtitle, font=role_f,
               fill=(*im._on(accent), 255))
    return frame


def render_frame(spec: MotionSpec, t: float) -> Image.Image:
    if spec.style == "logo":
        return _logo_frame(spec, t)
    if spec.style == "lower_third":
        f = lower_third_frame(spec, t)
        return f if spec.transparent else f.convert("RGB")
    W, H = spec.size
    bg, accent = im.hex_rgb(spec.background), im.hex_rgb(spec.accent)
    fg = im._on(bg)
    frame = Image.new("RGBA", (W, H), (*bg, 255))
    d = ImageDraw.Draw(frame)
    m = int(min(W, H) * 0.08)
    # A slow drifting accent circle and a growing bar: movement in every frame.
    r = int(min(W, H) * 0.42)
    cx = int(W * 0.82 + math.sin(t * 0.6) * W * 0.03)
    cy = int(H * 0.25 + math.cos(t * 0.5) * H * 0.03)
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((cx - r, cy - r, cx + r, cy + r), fill=(*accent, 38))
    frame.alpha_composite(glow)
    bar_w = int((W - 2 * m) * ease_out(t / max(spec.seconds * 0.3, 0.1)))
    d.rectangle((m, H - m - 8, m + bar_w, H - m), fill=(*accent, 255))
    progress = t / spec.seconds
    d.rectangle((0, 0, int(W * progress), 6), fill=(*accent, 255))

    big = im.font(int(min(W, H) * 0.11), bold=True)
    mid = im.font(int(min(W, H) * 0.05))
    pt = im.font(int(min(W, H) * 0.075), bold=True)
    for name, s, e in spec.scenes():
        if not (s <= t <= e):
            continue
        local = (t - s) / 0.6
        a = _alpha_in_out(t, s, e)
        k = ease_back(local) if spec.style == "pop" else ease_out(local)
        shift = 0 if spec.style == "fade" else int((1 - k) * H * 0.08)
        if name == "title":
            y = int(H * 0.30) + shift
            used = _draw_text(frame, spec.title, big, (m, y), fg, a, W - 2 * m)
            if spec.subtitle:
                sub_a = _alpha_in_out(t, s + 0.4, e)
                _draw_text(frame, spec.subtitle, mid, (m, y + used + int(H * 0.03)), accent, sub_a, W - 2 * m)
        elif name.startswith("point"):
            i = int(name[5:])
            label = im.font(int(min(W, H) * 0.035), bold=True)
            _draw_text(frame, f"{i + 1:02d}", label, (m, int(H * 0.30) + shift), accent, a, W - 2 * m)
            _draw_text(frame, spec.points[i], pt, (m, int(H * 0.38) + shift), fg, a, W - 2 * m)
        elif name == "contact":
            _draw_text(frame, spec.title, mid, (m, int(H * 0.32) + shift), accent, a, W - 2 * m, 1)
            _draw_text(frame, spec.contact, pt, (m, int(H * 0.42) + shift), fg, a, W - 2 * m)
    return frame.convert("RGB")


def render_builtin(spec: MotionSpec, out: Path) -> str:
    """Encode the video. Returns the codec used."""
    import av  # noqa: PLC0415 - PyAV ships its own FFmpeg

    frames = max(1, int(round(spec.seconds * FPS)))
    if spec.transparent:  # PNG-in-MOV keeps the see-through background; video editors read it
        with av.open(str(out), mode="w") as container:
            stream = container.add_stream("png", rate=FPS)
            stream.width, stream.height = spec.size
            stream.pix_fmt = "rgba"
            for n in range(frames):
                for packet in stream.encode(av.VideoFrame.from_image(render_frame(spec, n / FPS))):
                    container.mux(packet)
            for packet in stream.encode():
                container.mux(packet)
        return "png"
    codec = "libx264"
    try:
        av.codec.Codec(codec, "w")
    except Exception:  # noqa: BLE001 - a build without x264
        codec = "mpeg4"
    with av.open(str(out), mode="w") as container:
        stream = container.add_stream(codec, rate=FPS)
        stream.width, stream.height = spec.size
        stream.pix_fmt = "yuv420p"
        if codec == "libx264":
            stream.options = {"crf": "20", "preset": "veryfast", "movflags": "+faststart"}
        else:
            stream.bit_rate = 8_000_000
        for n in range(frames):
            img = render_frame(spec, n / FPS)
            for packet in stream.encode(av.VideoFrame.from_image(img)):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    return codec


def _has_alpha(pix_fmt: str) -> bool:
    return pix_fmt.startswith(("rgba", "argb", "bgra", "abgr", "yuva", "ya"))


def inspect_video(path: Path, at_s: float | None = None) -> dict:
    """Open the finished video again: size, length, frame count, and one frame as a picture."""
    import av  # noqa: PLC0415

    info: dict = {"bytes": path.stat().st_size}
    with av.open(str(path)) as c:
        v = c.streams.video[0]
        info.update(width=v.codec_context.width, height=v.codec_context.height, codec=v.codec_context.name,
                    alpha=_has_alpha(v.codec_context.pix_fmt or ""))
        dur = float(c.duration / 1_000_000) if c.duration else (float(v.duration * v.time_base) if v.duration else 0.0)
        info["seconds"] = round(dur, 2)
        frames, grab = 0, None
        for frame in c.decode(v):
            frames += 1
            if at_s is not None and grab is None and frame.time is not None and frame.time >= at_s:
                grab = frame.to_image()
        info["frames"] = frames
        info["frame_image"] = grab
    return info


# ---------- After Effects (Windows, when installed) ----------
def find_after_effects() -> Path | None:
    if sys.platform != "win32":
        return None
    roots = [Path(os.environ.get(k, "")) / "Adobe" for k in ("ProgramFiles", "ProgramW6432") if os.environ.get(k)]
    hits = []
    for root in roots:
        if root.is_dir():
            hits += sorted(root.glob("Adobe After Effects */Support Files/AfterFX.exe"))
    return hits[-1] if hits else None  # the newest version sorts last


def after_effects_available() -> tuple[bool, str]:
    if sys.platform != "win32":
        return False, "After Effects automation works on Windows only."
    return (True, "") if find_after_effects() else (False, "After Effects is not installed on this computer.")


def after_effects_script(spec: MotionSpec, out: Path, project: Path, done: Path) -> str:
    """ExtendScript for After Effects: a composition with eased text and shape animation,
    saved as a project and rendered to MP4. Writes "ok" or the error to `done`."""
    W, H = spec.size
    data = json.dumps({
        "title": spec.title, "subtitle": spec.subtitle, "points": spec.points[:5], "contact": spec.contact,
        "bg": [c / 255 for c in im.hex_rgb(spec.background)], "accent": [c / 255 for c in im.hex_rgb(spec.accent)],
        "fg": [c / 255 for c in im._on(im.hex_rgb(spec.background))],
        "w": W, "h": H, "fps": FPS, "seconds": spec.seconds, "style": spec.style,
        "scenes": spec.scenes(), "out": str(out), "project": str(project), "done": str(done),
    })
    return """
var d = %s;
function finish(msg){ var f = new File(d.done); f.encoding = "UTF-8"; f.open("w"); f.write(msg); f.close(); }
try {
  // Scripts may only write files when this preference is on; it is what lets the script save
  // the project, render and leave its "done" note.
  try { app.preferences.savePrefAsLong("Main Pref Section", "Pref_SCRIPTING_FILE_NETWORK_SECURITY", 1, PREFType.PREF_Type_MACHINE_INDEPENDENT); } catch (pe) {}
  app.beginSuppressDialogs();
  app.newProject();
  var comp = app.project.items.addComp("S-CLAW promo", d.w, d.h, 1, d.seconds, d.fps);
  var bg = comp.layers.addSolid(d.bg, "Background", d.w, d.h, 1, d.seconds);
  var m = Math.round(Math.min(d.w, d.h) * 0.08);
  var ease = [new KeyframeEase(0, 75)], easeIn = [new KeyframeEase(0, 33)];
  function easeKeys(prop) {
    for (var k = 1; k <= prop.numKeys; k++) {
      var dims = prop.value instanceof Array ? prop.value.length : 1, e = [], ei = [];
      for (var j = 0; j < dims; j++) { e.push(ease[0]); ei.push(easeIn[0]); }
      if (prop.propertyValueType == PropertyValueType.ThreeD_SPATIAL || prop.propertyValueType == PropertyValueType.TwoD_SPATIAL) { e = [ease[0]]; ei = [easeIn[0]]; }
      prop.setTemporalEaseAtKey(k, ei, e);
    }
  }
  // A drifting accent circle.
  var circle = comp.layers.addShape(); circle.name = "Accent circle";
  var grp = circle.property("Contents").addProperty("ADBE Vector Group");
  var r = Math.round(Math.min(d.w, d.h) * 0.42);
  grp.property("Contents").addProperty("ADBE Vector Shape - Ellipse").property("Size").setValue([2*r, 2*r]);
  var fill = grp.property("Contents").addProperty("ADBE Vector Graphic - Fill");
  fill.property("Color").setValue(d.accent); fill.property("Opacity").setValue(15);
  var cp = circle.property("Transform").property("Position");
  cp.setValueAtTime(0, [d.w*0.80, d.h*0.27]); cp.setValueAtTime(d.seconds, [d.w*0.85, d.h*0.22]);
  // The accent bar grows along the bottom.
  var bar = comp.layers.addShape(); bar.name = "Accent bar";
  var bg2 = bar.property("Contents").addProperty("ADBE Vector Group");
  bg2.property("Contents").addProperty("ADBE Vector Shape - Rect").property("Size").setValue([d.w - 2*m, 8]);
  bg2.property("Contents").addProperty("ADBE Vector Graphic - Fill").property("Color").setValue(d.accent);
  bar.property("Transform").property("Position").setValue([d.w/2, d.h - m - 4]);
  var bs = bar.property("Transform").property("Scale");
  bs.setValueAtTime(0, [0, 100]); bs.setValueAtTime(d.seconds * 0.3, [100, 100]); easeKeys(bs);

  function textLayer(s, size, colour, x, y, start, end, bold) {
    var l = comp.layers.addText(s); var p = l.property("Source Text"); var t = p.value;
    t.fontSize = size; t.fillColor = colour; t.justification = ParagraphJustification.LEFT_JUSTIFY;
    t.applyStroke = false; try { t.fauxBold = !!bold; } catch (fb) {} p.setValue(t);  // fauxBold is writable from AE 24
    l.inPoint = start; l.outPoint = end;
    var pos = l.property("Transform").property("Position"), op = l.property("Transform").property("Opacity");
    var drop = d.style == "fade" ? 0 : d.h * 0.08;
    pos.setValueAtTime(start, [x, y + drop]); pos.setValueAtTime(start + 0.6, [x, y]);
    op.setValueAtTime(start, 0); op.setValueAtTime(start + 0.35, 100);
    op.setValueAtTime(Math.max(start + 0.4, end - 0.35), 100); op.setValueAtTime(end, 0);
    if (d.style == "pop") {
      var sc = l.property("Transform").property("Scale");
      sc.setValueAtTime(start, [80, 80]); sc.setValueAtTime(start + 0.45, [104, 104]); sc.setValueAtTime(start + 0.6, [100, 100]);
      easeKeys(sc);
    }
    easeKeys(pos); return l;
  }
  var big = Math.round(Math.min(d.w, d.h) * 0.11), mid = Math.round(Math.min(d.w, d.h) * 0.05), pt = Math.round(Math.min(d.w, d.h) * 0.075);
  for (var i = 0; i < d.scenes.length; i++) {
    var sc = d.scenes[i], name = sc[0], s = sc[1], e = sc[2];
    if (name == "title") {
      textLayer(d.title, big, d.fg, m, d.h * 0.30 + big, s, e, true);
      if (d.subtitle) textLayer(d.subtitle, mid, d.accent, m, d.h * 0.30 + big * 2.3, s + 0.4, e, false);
    } else if (name.indexOf("point") == 0) {
      var n = parseInt(name.substr(5), 10);
      textLayer((n < 9 ? "0" : "") + (n + 1), Math.round(Math.min(d.w, d.h) * 0.035), d.accent, m, d.h * 0.30 + 40, s, e, true);
      textLayer(d.points[n], pt, d.fg, m, d.h * 0.38 + pt, s, e, true);
    } else if (name == "contact") {
      textLayer(d.title, mid, d.accent, m, d.h * 0.32 + mid, s, e, false);
      textLayer(d.contact, pt, d.fg, m, d.h * 0.42 + pt, s, e, true);
    }
  }
  app.project.save(new File(d.project));
  var item = app.project.renderQueue.items.add(comp);
  var om = item.outputModule(1), templates = om.templates, pick = null;
  for (var t = 0; t < templates.length; t++) { if (templates[t].indexOf("H.264") == 0) { pick = templates[t]; break; } }
  if (pick) { om.applyTemplate(pick); }
  om.file = new File(d.out);
  app.project.renderQueue.render();
  app.project.save(new File(d.project));
  app.endSuppressDialogs(false);
  finish(new File(d.out).exists ? "ok" : "After Effects rendered, but no MP4 appeared (no H.264 output template on this version).");
} catch (err) {
  finish("error: " + err.toString() + " (line " + err.line + ")");
}
""" % data


def run_after_effects(spec: MotionSpec, out: Path, project: Path, timeout_s: float = 900) -> None:
    exe = find_after_effects()
    if exe is None:
        raise RuntimeError("After Effects is not installed on this computer.")
    tmp = Path(tempfile.mkdtemp(prefix="claw-ae-"))
    done = tmp / "done.txt"
    script = tmp / "promo.jsx"
    script.write_text(after_effects_script(spec, out, project, done), encoding="utf-8")
    # -r runs the script in a running After Effects, or starts one first. It returns at once,
    # so Claw waits for the script's own "done" note rather than for the program to exit.
    subprocess.Popen([str(exe), "-r", str(script)], close_fds=True)
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        if done.is_file():
            msg = done.read_text(encoding="utf-8", errors="replace").strip()
            if msg != "ok":
                raise RuntimeError(msg[:300])
            return
        time.sleep(1.0)
    raise RuntimeError("After Effects did not finish within the time allowed. If it is open, check "
                       "Edit > Preferences > Scripting & Expressions > 'Allow Scripts to Write Files and Access Network'.")
