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
    "banner": (1500, 500),  # X / Twitter header
    "cover": (1640, 624),  # Facebook page cover
    "portrait": (1080, 1350),  # Instagram portrait post
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
    # Type is sized from the width, except on very wide banners (X header, Facebook cover), where the
    # height would run out first: there it is sized as if the page were twice as wide as it is tall.
    u = W if W <= 2 * H else 2 * H
    m = int(u * 0.07)
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
    band = int(max(H * 0.09, u * 0.075)) if spec.contact else 0
    # Text goes on its own layer first, so it can be centred in the space left under the pictures,
    # and shrunk until it fits that space.
    def text_block(scale: float):
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        ty = 0
        ld.rectangle([m, ty, m + int(W * 0.12), ty + max(6, H // 300)], fill=accent)
        ty += int(H * 0.03 * scale)
        tf, tlines = _fit_title(ld, spec.title, W - 2 * m, int(u * 0.11 * scale))
        for line in tlines:
            ld.text((m, ty), line, font=tf, fill=ink)
            ty += int(tf.size * 1.12)
        if spec.subtitle:
            ty += int(H * 0.01 * scale)
            sf = font(int(u * 0.042 * scale))
            for line in _wrap(ld, spec.subtitle, sf, W - 2 * m, 3):
                ld.text((m, ty), line, font=sf, fill=accent)
                ty += int(sf.size * 1.3)
        if spec.points:
            ty += int(H * 0.025 * scale)
            pf = font(int(u * 0.036 * scale))
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
        cf, _ = _fit_title(draw, spec.contact, W - 2 * m, int(u * 0.045), max_lines=1)
        cf = font(min(cf.size, int(u * 0.045), int(band * 0.6)), bold=True)
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


# ---------------------------------------------------------------------------
# Milestone 8: the design jobs that do not need Photoshop.
#
# Section 1 of the challenge list is mostly Photoshop. Some of it genuinely
# needs a paid app or a far bigger brain and is marked OUT - cutting a person
# out of a crowd, rebuilding a background behind them, colourising black and
# white. What is left is layout and measurable pixel work, and Pillow does that
# on every machine with no install and no account.
#
# Each renderer here returns an image; the tool layer saves it, reopens it and
# checks it, exactly as make_flyer already does. Nothing here pretends to be
# Photoshop: when Photoshop is installed the existing COM path still takes
# precedence, and Claw says which editor made the result.

POSTER_SIZES = {
    "poster": (2480, 3508),        # A4 at 300 dpi
    "thumbnail": (1280, 720),      # YouTube
    "magazine": (2480, 3508),      # A4 cover
    "square": (1080, 1080),
}


def _scrim(img: Image.Image, frm: float = 0.42, strength: float = 0.88) -> Image.Image:
    """Darken the lower part of a picture so text laid over it stays readable.

    A poster puts its title over the photograph. Without this the title is
    legible or not depending on what happens to be behind it, which is how a
    layout looks accidental.
    """
    W, H = img.size
    layer = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(layer)
    start = int(H * frm)
    for y in range(start, H):
        t = (y - start) / max(1, H - start)
        d.line([(0, y), (W, y)], fill=int(255 * strength * (t ** 1.4)))
    black = Image.new("RGB", (W, H), (0, 0, 0))
    return Image.composite(black, img, layer)


def _readable(img: Image.Image, box: tuple[int, int, int, int], wanted) -> tuple[int, int, int]:
    """`wanted`, or something legible, against whatever is actually behind it.

    An accent colour is picked to suit the layout, not the photograph. The first
    poster set its tagline in amber over mid-brown and the two were within a few
    points of each other, so the line all but vanished - and an outline only
    disguises that. This measures the patch the text will cover and keeps the
    accent when it carries, swapping to white or near-black when it does not.
    """
    from claw.integrations.pillow import ImageStat

    x0, y0, x1, y1 = (max(0, box[0]), max(0, box[1]),
                      min(img.width, max(box[0] + 1, box[2])), min(img.height, max(box[1] + 1, box[3])))
    behind = ImageStat.Stat(img.convert("RGB").crop((x0, y0, x1, y1))).mean
    if abs(_lum(wanted) - _lum(behind)) >= 60:
        return wanted
    return (255, 255, 255) if _lum(behind) < 140 else (18, 20, 26)


def _over_photo(d, xy, text, f, fill, px: int):
    """Draw text with a photograph behind it: a thin dark outline to hold the edge."""
    d.text(xy, text, font=f, fill=fill, stroke_width=max(1, px), stroke_fill=(10, 12, 16))


@dataclass
class PosterSpec:
    """One design brief for a poster, a video thumbnail or a magazine cover."""

    title: str
    images: list[Path]
    style: str = "poster"              # poster | thumbnail | magazine
    subtitle: str = ""
    tagline: str = ""                  # the line above the title on a poster
    credits: str = ""                  # the small block at the foot
    cover_lines: list[str] = field(default_factory=list)   # magazine only
    size: tuple[int, int] | None = None
    background: str = "#0d0f14"
    accent: str = "#e4b43c"


def render_poster(spec: PosterSpec) -> Image.Image:
    W, H = spec.size or POSTER_SIZES.get(spec.style, POSTER_SIZES["poster"])
    bg, accent = hex_rgb(spec.background), hex_rgb(spec.accent)
    img = Image.new("RGB", (W, H), bg)

    if spec.images:
        img.paste(_cover(Image.open(spec.images[0]), (W, H)), (0, 0))
    else:
        # No photograph: a plain field rather than a white rectangle, so the
        # result still looks deliberate.
        d0 = ImageDraw.Draw(img)
        for y in range(H):
            t = y / H
            d0.line([(0, y), (W, y)], fill=tuple(int(bg[i] * (1 - t * 0.45)) for i in range(3)))

    if spec.style == "thumbnail":
        return _thumbnail(img, spec, accent)
    if spec.style == "magazine":
        return _magazine(img, spec, accent)
    return _poster(img, spec, accent)


def _poster(img: Image.Image, spec: PosterSpec, accent) -> Image.Image:
    """A film-poster shape: picture, darkened foot, tagline, title, credits."""
    W, H = img.size
    extras = spec.images[1:5]
    if extras:
        # A strip of the other pictures across the middle, as a poster does with
        # its cast: small, equal, and aligned to the same baseline.
        gap = int(W * 0.012)
        tw = (W - 2 * int(W * 0.08) - gap * (len(extras) - 1)) // len(extras)
        th = int(H * 0.11)
        top = int(H * 0.47)
        for i, p in enumerate(extras):
            img.paste(_cover(Image.open(p), (tw, th)), (int(W * 0.08) + i * (tw + gap), top))
    img = _scrim(img, frm=0.44, strength=0.95)
    d = ImageDraw.Draw(img)
    m = int(W * 0.08)
    y = int(H * 0.645)
    if spec.tagline:
        f = font(int(W * 0.026), bold=False)
        for line in _wrap(d, spec.tagline.upper(), f, W - 2 * m, 2):
            colour = _readable(img, (m, y, m + int(d.textlength(line, font=f)), y + f.size), accent)
            _over_photo(d, (m, y), line, f, colour, W // 900)
            y += int(f.size * 1.5)
        y += int(H * 0.012)
    tf, lines = _fit_title(d, spec.title.upper(), W - 2 * m, int(W * 0.105), max_lines=3)
    for line in lines:
        d.text((m, y), line, font=tf, fill=(255, 255, 255))
        y += int(tf.size * 1.08)
    if spec.subtitle:
        y += int(H * 0.012)
        f = font(int(W * 0.03))
        for line in _wrap(d, spec.subtitle, f, W - 2 * m, 2):
            d.text((m, y), line, font=f, fill=(228, 230, 236))
            y += int(f.size * 1.4)
    d.rectangle([m, int(H * 0.915), m + int(W * 0.14), int(H * 0.915) + max(4, H // 400)], fill=accent)
    if spec.credits:
        f = font(int(W * 0.019))
        cy = int(H * 0.932)
        for line in _wrap(d, spec.credits.upper(), f, W - 2 * m, 3):
            d.text((m, cy), line, font=f, fill=(196, 200, 210))
            cy += int(f.size * 1.45)
    return img


def _thumbnail(img: Image.Image, spec: PosterSpec, accent) -> Image.Image:
    """1280x720, read at the size of a thumbnail: few words, very large."""
    W, H = img.size
    img = _scrim(img, frm=0.0, strength=0.5)
    d = ImageDraw.Draw(img)
    m = int(W * 0.055)
    if len(spec.images) > 1:
        side = int(H * 0.42)
        inset = _cover(Image.open(spec.images[1]), (side, side))
        bx, by = W - side - m, H - side - m
        d.rectangle([bx - 6, by - 6, bx + side + 6, by + side + 6], fill=accent)
        img.paste(inset, (bx, by))
    width = int(W * 0.62) if len(spec.images) > 1 else W - 2 * m
    tf, lines = _fit_title(d, spec.title.upper(), width, int(W * 0.105), max_lines=3)
    y = m
    for line in lines:
        # A heavy outline, because a thumbnail lands on whatever colour the feed
        # happens to put behind it.
        d.text((m, y), line, font=tf, fill=(255, 255, 255), stroke_width=max(3, W // 300), stroke_fill=(8, 10, 14))
        y += int(tf.size * 1.06)
    if spec.subtitle:
        y += int(H * 0.02)
        f = font(int(W * 0.038), bold=True)
        line = _wrap(d, spec.subtitle.upper(), f, width, 1)[0]
        pad = int(W * 0.012)
        w = d.textlength(line, font=f)
        d.rectangle([m - pad, y - pad // 2, m + w + pad, y + f.size + pad], fill=accent)
        d.text((m, y), line, font=f, fill=_on(accent))
    return img


def _magazine(img: Image.Image, spec: PosterSpec, accent) -> Image.Image:
    """Masthead across the top, cover lines down one side."""
    W, H = img.size
    img = _scrim(img, frm=0.0, strength=0.28)
    d = ImageDraw.Draw(img)
    m = int(W * 0.06)
    mf, lines = _fit_title(d, spec.title.upper(), W - 2 * m, int(W * 0.16), max_lines=1)
    d.text((m, int(H * 0.035)), lines[0], font=mf, fill=(255, 255, 255))
    if spec.subtitle:
        f = font(int(W * 0.022))
        sy = int(H * 0.035) + int(mf.size * 1.02)
        text = spec.subtitle.upper()
        colour = _readable(img, (m, sy, m + int(d.textlength(text, font=f)), sy + f.size), accent)
        _over_photo(d, (m, sy), text, f, colour, W // 900)
    # Spread down the page rather than stacking under the masthead: a cover
    # with its lower half empty reads as an unfinished template.
    picked = spec.cover_lines[:5]
    top, step = int(H * 0.30), int(H * (0.58 / max(1, len(picked))))
    for n, text in enumerate(picked):
        y = top + step * n          # each entry starts at its own slot, so two identical lines cannot collide
        f = font(int(W * 0.034), bold=True)
        for line in _wrap(d, text, f, int(W * 0.5), 2):
            _over_photo(d, (m, y), line, f, (255, 255, 255), max(2, W // 700))
            y += int(f.size * 1.2)
        d.rectangle([m, y + int(H * 0.008), m + int(W * 0.06), y + int(H * 0.008) + max(3, H // 500)], fill=accent)

    return img


# ---------- collage (challenge 1.15) ----------
def render_collage(paths: list[Path], size: tuple[int, int] = (2480, 2480), background: str = "#101317",
                   gap_ratio: float = 0.012, even_exposure: bool = True) -> tuple[Image.Image, int]:
    """A grid of pictures, each levelled so the set looks like one shoot.

    "Consistent lighting" is the hard half of the challenge. There is no model
    here guessing at light direction: each picture is auto-levelled so its own
    darkest and lightest points reach the same ends of the scale, which is what
    makes a set of phone photographs stop looking like a jumble.
    """
    if not paths:
        raise ValueError("No pictures were given for the collage.")
    W, H = size
    bg = hex_rgb(background)
    n = len(paths)
    cols = 1 if n == 1 else 2 if n <= 4 else 3 if n <= 9 else 4
    rows = -(-n // cols)
    gap = int(min(W, H) * gap_ratio)
    cw = (W - gap * (cols + 1)) // cols
    ch = (H - gap * (rows + 1)) // rows
    sheet = Image.new("RGB", (W, H), bg)
    for i, p in enumerate(paths):
        im = ImageOps.exif_transpose(Image.open(p)).convert("RGB")
        if even_exposure:
            im = ImageOps.autocontrast(im, cutoff=1)
        r, c = divmod(i, cols)
        sheet.paste(ImageOps.fit(im, (cw, ch), Image.LANCZOS),
                    (gap + c * (cw + gap), gap + r * (ch + gap)))
    return sheet, n


# ---------- exposure (challenge 1.17) ----------
def brighten(path: Path, target: float = 128.0) -> tuple[Image.Image, float, float]:
    """Lift an underexposed photograph towards a normal mid-tone.

    Returns the picture and the mean brightness before and after, so the tool
    can report a number instead of an opinion. Nothing is applied blindly: a
    picture already at the target comes back auto-levelled only.
    """
    from claw.integrations.pillow import ImageStat

    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    before = ImageStat.Stat(im.convert("L")).mean[0]
    out = ImageOps.autocontrast(im, cutoff=1)
    mid = ImageStat.Stat(out.convert("L")).mean[0]
    if mid < target - 2:
        # Cap the lift: doubling a very dark frame turns noise into confetti.
        factor = min(target / max(mid, 1.0), 2.6)
        out = ImageEnhance.Brightness(out).enhance(factor)
        out = ImageEnhance.Contrast(out).enhance(1.06)
    after = ImageStat.Stat(out.convert("L")).mean[0]
    return out, round(before, 1), round(after, 1)


# ---------- passport photograph (challenge 1.18) ----------
#: width x height in millimetres, and the print resolution they are checked at.
PASSPORT = {"uk": (35, 45), "eu": (35, 45), "schengen": (35, 45), "ng": (35, 45), "us": (51, 51), "india": (51, 51)}


def passport_crop(path: Path, country: str = "uk", dpi: int = 300,
                  background: str | None = None) -> tuple[Image.Image, tuple[int, int], str]:
    """Crop and size a photograph to a passport standard.

    Honest about what it does not do: there is no face detection here, so the
    crop is positional - centred horizontally, weighted towards the top third
    where a head sits in a portrait. It gets the measurements and the print
    resolution exactly right and leaves the judgement of the face to the person,
    which is the half a library can be trusted with.
    """
    mm = PASSPORT.get(country.lower())
    if mm is None:
        raise ValueError(f"Unknown passport size '{country}'. Known: {', '.join(sorted(PASSPORT))}.")
    px = (round(mm[0] / 25.4 * dpi), round(mm[1] / 25.4 * dpi))
    im = ImageOps.exif_transpose(Image.open(path))
    if background:
        flat = Image.new("RGB", im.size, hex_rgb(background))
        flat.paste(im.convert("RGB"), (0, 0), im.convert("RGBA").getchannel("A") if im.mode in ("RGBA", "LA") else None)
        im = flat
    out = ImageOps.fit(im.convert("RGB"), px, Image.LANCZOS, centering=(0.5, 0.32))
    return out, px, f"{mm[0]}×{mm[1]} mm at {dpi} dpi"


# ---------- product shadow (challenge 1.09) ----------
def _subject_mask(im: Image.Image, tolerance: int = 26) -> Image.Image:
    """Where the product is: its alpha when it has one, else everything that is
    not the flat colour found in the corners."""
    if im.mode in ("RGBA", "LA"):
        a = im.convert("RGBA").getchannel("A")
        if a.getextrema()[0] < 250:
            return a
    rgb = im.convert("RGB")
    w, h = rgb.size
    corners = [rgb.getpixel(p) for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]
    base = tuple(sum(c[i] for c in corners) // 4 for i in range(3))
    flat = Image.new("RGB", rgb.size, base)
    from claw.integrations.pillow import ImageChops

    diff = ImageChops.difference(rgb, flat).convert("L")
    return diff.point(lambda v: 255 if v > tolerance else 0)


def add_product_shadow(path: Path, background: str = "#ffffff", softness: float = 0.045,
                       opacity: float = 0.42) -> tuple[Image.Image, bool]:
    """Set a product on a plain ground with a soft shadow under it.

    The shadow is the subject's own silhouette, squashed flat, blurred and laid
    beneath it - which is what a contact shadow is. It does not invent a light
    source or a reflection, because guessing those is what makes a composite
    look wrong.
    """
    from claw.integrations.pillow import ImageFilter

    src = ImageOps.exif_transpose(Image.open(path))
    mask = _subject_mask(src)
    box = mask.getbbox()
    found = box is not None
    W, H = src.size
    canvas = Image.new("RGB", (W, H), hex_rgb(background))
    if found:
        left, top, right, bottom = box
        sw, sh = right - left, bottom - top
        ellipse_h = max(8, int(sh * 0.16))
        shadow = Image.new("L", (W, H), 0)
        ImageDraw.Draw(shadow).ellipse(
            [left + sw * 0.06, bottom - ellipse_h // 2, right - sw * 0.06, bottom + ellipse_h // 2], fill=255)
        shadow = shadow.filter(ImageFilter.GaussianBlur(max(2.0, min(W, H) * softness)))
        shadow = shadow.point(lambda v: int(v * opacity))
        canvas = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), canvas, shadow)
    canvas.paste(src.convert("RGB"), (0, 0), mask)
    return canvas, found


# ---------- compare two designs (challenge 1.25) ----------
def compare_images(a: Path, b: Path, threshold: int = 24, grid: int = 44,
                   outline: str = "#ff3b5c") -> tuple[Image.Image, list[tuple[int, int, int, int]], float]:
    """Mark what changed between two versions of a design.

    A whole-image difference says "they differ"; what a person needs is where.
    The picture is divided into a grid, every cell whose mean difference passes
    the threshold is marked, and touching marked cells are merged into the
    rectangles that come back. No new dependency: this is the part of a vision
    library that this job actually needs.
    """
    from claw.integrations.pillow import ImageChops, ImageStat

    ia = ImageOps.exif_transpose(Image.open(a)).convert("RGB")
    ib = ImageOps.exif_transpose(Image.open(b)).convert("RGB")
    if ia.size != ib.size:
        ib = ib.resize(ia.size, Image.LANCZOS)
    diff = ImageChops.difference(ia, ib).convert("L")
    W, H = ia.size
    cw, ch = max(1, W // grid), max(1, H // grid)
    hits: set[tuple[int, int]] = set()
    changed_px = 0
    for gy in range(0, H, ch):
        for gx in range(0, W, cw):
            cell = diff.crop((gx, gy, min(gx + cw, W), min(gy + ch, H)))
            if ImageStat.Stat(cell).mean[0] >= threshold:
                hits.add((gx // cw, gy // ch))
                changed_px += cell.size[0] * cell.size[1]

    # Merge touching cells into rectangles, so the report lists regions rather
    # than hundreds of squares.
    boxes: list[tuple[int, int, int, int]] = []
    seen: set[tuple[int, int]] = set()
    for cell in sorted(hits):
        if cell in seen:
            continue
        stack, group = [cell], []
        seen.add(cell)
        while stack:
            cx, cy = stack.pop()
            group.append((cx, cy))
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nxt = (cx + dx, cy + dy)
                if nxt in hits and nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        xs = [g[0] for g in group]
        ys = [g[1] for g in group]
        boxes.append((min(xs) * cw, min(ys) * ch, min(W, (max(xs) + 1) * cw), min(H, (max(ys) + 1) * ch)))

    marked = ib.copy()
    d = ImageDraw.Draw(marked)
    for box in boxes:
        d.rectangle(box, outline=hex_rgb(outline), width=max(2, min(W, H) // 300))
    return marked, boxes, round(100 * changed_px / (W * H), 2)
