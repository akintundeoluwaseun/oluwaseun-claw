"""Image work: promotional flyers and basic edits.

Two editors, and Claw always says which one made the result:
- **Photoshop**, when it is installed: driven through its own scripting interface (COM + ExtendScript),
  which Adobe documents for automation. NOT YET RUN (no Windows/Photoshop in the build workspace).
- **Claw's built-in editor** (Pillow, MIT-CMU): works on every computer, fully tested.

Every output is a NEW file in an authorized folder (never overwrites), reopened afterwards to check its
format and size, and for flyers, read back with OCR to confirm the headline is really on the image.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from claw.integrations.pillow import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps

PRESETS = {
    "square": (1080, 1080),  # Instagram / WhatsApp status square
    "story": (1080, 1920),  # status / story
    "a5": (1748, 2480),  # A5 at 300 dpi
    "a4": (2480, 3508),  # A4 at 300 dpi
    "landscape": (1920, 1080),
}
FORMATS = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".pdf": "PDF", ".webp": "WEBP"}

_FONT_DIRS = [Path(os.environ.get("WINDIR", "C:\\Windows")) / "Fonts", Path("/usr/share/fonts/truetype/dejavu"),
              Path("/usr/share/fonts/truetype/liberation"), Path("/Library/Fonts")]
_BOLD = ["segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"]
_REGULAR = ["segoeui.ttf", "arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"]


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for name in _BOLD if bold else _REGULAR:
        for d in _FONT_DIRS:
            if (d / name).is_file():
                return ImageFont.truetype(str(d / name), size)
    return ImageFont.load_default(size=size)


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _lum(rgb) -> float:
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def _on(rgb) -> tuple[int, int, int]:
    return (20, 24, 28) if _lum(rgb) > 150 else (255, 255, 255)


@dataclass
class FlyerSpec:
    title: str
    subtitle: str = ""
    points: list[str] = field(default_factory=list)
    contact: str = ""
    size: tuple[int, int] = PRESETS["a5"]
    background: str = "#14212b"
    accent: str = "#3cc2aa"
    images: list[Path] = field(default_factory=list)


def _wrap(draw: ImageDraw.ImageDraw, text: str, f, width: int, max_lines: int) -> list[str]:
    words, lines, line = text.split(), [], ""
    for w in words:
        trial = f"{line} {w}".strip()
        if draw.textlength(trial, font=f) <= width or not line:
            line = trial
        else:
            lines.append(line)
            line = w
    if line:
        lines.append(line)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        while lines[-1] and draw.textlength(lines[-1] + "…", font=f) > width:
            lines[-1] = lines[-1][:-1]
        lines[-1] += "…"
    return lines


def _fit_title(draw, text, width, start, max_lines=2):
    size = start
    while size > 24:
        f = font(size, bold=True)
        lines = _wrap(draw, text, f, width, 99)
        if len(lines) <= max_lines:
            return f, lines
        size = int(size * 0.9)
    f = font(24, bold=True)
    return f, _wrap(draw, text, f, width, max_lines)


def _cover(img: Image.Image, box: tuple[int, int]) -> Image.Image:
    return ImageOps.fit(ImageOps.exif_transpose(img).convert("RGB"), box, Image.LANCZOS)


def render_flyer(spec: FlyerSpec) -> Image.Image:
    W, H = spec.size
    bg, accent = hex_rgb(spec.background), hex_rgb(spec.accent)
    ink, accent_ink = _on(bg), _on(accent)
    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)
    # Gentle vertical gradient for depth.
    darker = tuple(max(0, int(c * (0.92 if _lum(bg) > 150 else 0.72))) for c in bg)
    for y in range(H):
        t = y / H
        draw.line([(0, y), (W, y)], fill=tuple(int(bg[i] * (1 - t) + darker[i] * t) for i in range(3)))
    m = int(W * 0.07)
    y = m
    if spec.images:
        hero_h = int(H * (0.38 if len(spec.images) == 1 else 0.30))
        hero = _cover(Image.open(spec.images[0]), (W - 2 * m, hero_h))
        img.paste(hero, (m, y))
        y += hero_h + int(H * 0.012)
        extras = spec.images[1:4]
        if extras:
            gap = int(W * 0.015)
            tw = (W - 2 * m - gap * (len(extras) - 1)) // len(extras)
            th = int(H * 0.11)
            for i, p in enumerate(extras):
                img.paste(_cover(Image.open(p), (tw, th)), (m + i * (tw + gap), y))
            y += th
        y += int(H * 0.03)
    else:
        y += int(H * 0.04)
    band = int(H * 0.09) if spec.contact else 0
    # Text goes on its own layer first, so it can be centred in the space left under the pictures,
    # and shrunk until it fits that space.
    def text_block(scale: float):
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        ty = 0
        ld.rectangle([m, ty, m + int(W * 0.12), ty + max(6, H // 300)], fill=accent)
        ty += int(H * 0.03 * scale)
        tf, tlines = _fit_title(ld, spec.title, W - 2 * m, int(W * 0.11 * scale))
        for line in tlines:
            ld.text((m, ty), line, font=tf, fill=ink)
            ty += int(tf.size * 1.12)
        if spec.subtitle:
            ty += int(H * 0.01 * scale)
            sf = font(int(W * 0.042 * scale))
            for line in _wrap(ld, spec.subtitle, sf, W - 2 * m, 3):
                ld.text((m, ty), line, font=sf, fill=accent)
                ty += int(sf.size * 1.3)
        if spec.points:
            ty += int(H * 0.025 * scale)
            pf = font(int(W * 0.036 * scale))
            r = max(3, pf.size // 5)
            indent = int(pf.size * 1.1)
            for p in spec.points[:6]:
                ld.ellipse([m, ty + pf.size // 2 - r, m + 2 * r, ty + pf.size // 2 + r], fill=accent)
                for line in _wrap(ld, p, pf, W - 2 * m - indent, 2):
                    ld.text((m + indent, ty), line, font=pf, fill=ink)
                    ty += int(pf.size * 1.3)
                ty += int(pf.size * 0.25)
        return layer, ty

    room = (H - band - m) - y
    scale = 1.0
    layer, ty = text_block(scale)
    while ty > room and scale > 0.45:
        scale *= 0.9
        layer, ty = text_block(scale)
    top = y + max(0, (room - ty) // 2) if spec.images else y + max(0, int((room - ty) * 0.42))
    img.paste(layer.crop((0, 0, W, max(1, ty))), (0, top), layer.crop((0, 0, W, max(1, ty))))
    draw = ImageDraw.Draw(img)
    if spec.contact:
        draw.rectangle([0, H - band, W, H], fill=accent)
        cf, _ = _fit_title(draw, spec.contact, W - 2 * m, int(W * 0.045), max_lines=1)
        cf = font(min(cf.size, int(W * 0.045)), bold=True)
        text = _wrap(draw, spec.contact, cf, W - 2 * m, 1)[0]
        draw.text((m, H - band + (band - cf.size) // 2), text, font=cf, fill=accent_ink)
    return img


def save_image(img: Image.Image, path: Path) -> None:
    fmt = FORMATS[path.suffix.lower()]
    if fmt in ("JPEG", "PDF"):
        img = img.convert("RGB")
    with open(path, "xb") as fh:  # "x": never overwrite
        img.save(fh, fmt, **({"quality": 92} if fmt == "JPEG" else {}), **({"resolution": 300.0} if fmt == "PDF" else {}))


def inspect(path: Path) -> dict:
    with Image.open(path) as im:
        im.verify()
    with Image.open(path) as im:
        return {"format": im.format, "width": im.width, "height": im.height, "mode": im.mode,
                "bytes": path.stat().st_size, "frames": getattr(im, "n_frames", 1)}


# ---------- Photoshop (Windows, when installed) ----------
def photoshop_available() -> tuple[bool, str]:
    if sys.platform != "win32":
        return False, "Photoshop automation works on Windows only."
    try:
        import winreg  # noqa: PLC0415

        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "Photoshop.Application"))
    except OSError:
        return False, "Photoshop is not installed on this computer."
    return True, ""


def photoshop_script(spec: FlyerSpec, out: Path) -> str:
    """ExtendScript for Photoshop: new document, background, placed images, text layers, save as PNG/JPG/PSD.
    All user text goes in through JSON encoding, so it cannot break out of the script."""
    W, H = spec.size
    data = json.dumps({"title": spec.title, "subtitle": spec.subtitle, "points": spec.points[:6], "contact": spec.contact,
                       "bg": spec.background.lstrip("#"), "accent": spec.accent.lstrip("#"),
                       "images": [str(p) for p in spec.images[:4]], "out": str(out), "w": W, "h": H})
    return """
var d = %s;
app.preferences.rulerUnits = Units.PIXELS;
app.displayDialogs = DialogModes.NO;
function rgb(h){var c=new SolidColor();c.rgb.hexValue=h;return c;}
var doc = app.documents.add(d.w, d.h, 300, "Claw flyer", NewDocumentMode.RGB, DocumentFill.WHITE);
app.foregroundColor = rgb(d.bg); doc.selection.selectAll(); doc.selection.fill(app.foregroundColor); doc.selection.deselect();
var m = Math.round(d.w*0.07), y = m;
for (var i=0;i<d.images.length && i<1;i++){
  var f = new File(d.images[i]); var placed = app.open(f); placed.flatten();
  var hh = Math.round(d.h*0.38); placed.resizeImage(UnitValue(d.w-2*m,"px"), UnitValue(hh,"px"), null, ResampleMethod.BICUBIC);
  placed.selection.selectAll(); placed.selection.copy(); placed.close(SaveOptions.DONOTSAVECHANGES);
  app.activeDocument = doc; doc.paste(); doc.activeLayer.translate(m - doc.activeLayer.bounds[0], y - doc.activeLayer.bounds[1]);
  y += hh + Math.round(d.h*0.04);
}
function text(s, size, color, top, bold){
  var l = doc.artLayers.add(); l.kind = LayerKind.TEXT; var t = l.textItem;
  t.kind = TextType.PARAGRAPHTEXT; t.contents = s; t.size = UnitValue(size, "px"); t.color = rgb(color);
  t.position = [UnitValue(m,"px"), UnitValue(top,"px")]; t.width = UnitValue(d.w-2*m,"px"); t.height = UnitValue(size*3,"px");
  if (bold) { t.fauxBold = true; } return l;
}
y += Math.round(d.h*0.06); text(d.title, Math.round(d.w*0.09), "FFFFFF", y, true); y += Math.round(d.w*0.24);
if (d.subtitle) { text(d.subtitle, Math.round(d.w*0.042), d.accent, y, false); y += Math.round(d.w*0.12); }
if (d.points.length) { text("\\u2022 " + d.points.join("\\r\\u2022 "), Math.round(d.w*0.036), "FFFFFF", y, false); }
if (d.contact) { text(d.contact, Math.round(d.w*0.04), d.accent, d.h - Math.round(d.h*0.08), true); }
var ext = d.out.split(".").pop().toLowerCase(), opts;
if (ext == "png") { opts = new PNGSaveOptions(); } else if (ext == "psd") { opts = new PhotoshopSaveOptions(); }
else { opts = new JPEGSaveOptions(); opts.quality = 10; }
doc.saveAs(new File(d.out), opts, true, Extension.LOWERCASE);
doc.close(SaveOptions.DONOTSAVECHANGES);
"ok";
""" % data


def run_photoshop(spec: FlyerSpec, out: Path) -> None:
    import win32com.client  # noqa: PLC0415 — pywin32, Windows only

    ps = win32com.client.Dispatch("Photoshop.Application")
    result = ps.DoJavaScript(photoshop_script(spec, out))
    if str(result).strip() != "ok" or not out.is_file():
        raise RuntimeError(f"Photoshop did not save the file ({str(result)[:200]}).")


def temp_png() -> Path:
    fd, name = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    return Path(name)
