"""A folder of photographs at once, and QR codes.

edit_image already does one picture well. What was missing is the job people
actually have: two hundred photographs off a phone or a camera, every one of
them four or five megabytes, that need to be small enough to send on
WhatsApp, attach to an e-mail or put on a website - and product photographs
that should carry the shop's name before they go out.

Three tools:
  resize_photos  - a whole folder, smaller, into a NEW folder.
  watermark_photos - the shop's name across a folder of pictures.
  make_qr_code   - a QR code for a link, a phone number or a payment page.

Originals are never touched. Everything lands in a new folder, and every
result is reopened and measured before it is reported.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from pydantic import Field, field_validator

from claw.agent.schemas import Capability
from claw.permissions.policy import RiskLevel
from claw.tools.base import ToolArgs, ToolContext, ToolError, ToolRegistry, ToolResult, ToolSpec
from claw.tools.file_tools import existing_folder, safe_file_name, unique_path
from claw.tools.image_tools import IMAGE_IN

#: More than this in one go is a mistake in the folder name, not a request.
MAX_PHOTOS = 500
#: Sizes people ask for by name, because "1600 pixels" is not how anyone
#: describes what they want.
PRESETS = {
    "whatsapp": 1600,
    "email": 1600,
    "website": 1920,
    "web": 1920,
    "small": 1000,
    "thumbnail": 400,
    "print": 3000,
}


def _photos_in(folder: Path) -> list[Path]:
    found = sorted((p for p in folder.iterdir()
                    if p.is_file() and p.suffix.lower() in IMAGE_IN and not p.name.startswith(".")),
                   key=lambda p: p.name.lower())
    if not found:
        raise ToolError(f"There are no pictures in {folder.name}.")
    if len(found) > MAX_PHOTOS:
        raise ToolError(f"{folder.name} holds {len(found)} pictures, which is more than Claw "
                        f"will do at once (the limit is {MAX_PHOTOS}).")
    return found


def _size(n: float) -> str:
    for unit in ("bytes", "KB", "MB"):
        if n < 1024 or unit == "MB":
            return f"{n:,.0f} {unit}" if unit == "bytes" else f"{n:,.1f} {unit}"
        n /= 1024.0
    return f"{n:,.1f} MB"


def _fit(img: Image.Image, longest: int) -> Image.Image:
    """Scale so the longer side is `longest`, keeping the shape.

    Never scales UP: asking for 1600 when the photo is 900 wide should leave
    it alone, not blow it up into a blurry 1600.
    """
    if max(img.size) <= longest:
        return img
    scale = longest / max(img.size)
    return img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))),
                      Image.LANCZOS)


def _flatten(img: Image.Image) -> Image.Image:
    """JPEG has no transparency; paste onto white rather than onto black."""
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        return bg
    return img.convert("RGB")


# ---------- a folder of photographs, smaller ----------
class ResizeArgs(ToolArgs):
    folder: str = Field(min_length=1, max_length=500, description="The folder of pictures")
    size: str = Field(default="whatsapp",
                      description='whatsapp, email, website, small, thumbnail, print, or a number of pixels')
    quality: int = Field(default=82, ge=40, le=95, description="JPEG quality; lower is smaller")
    keep_format: bool = Field(default=False, description="Keep PNG as PNG instead of making JPEGs")
    save_in: str | None = Field(default=None, max_length=500)

    @field_validator("size")
    @classmethod
    def _known(cls, v: str) -> str:
        text = str(v).strip().lower()
        if text in PRESETS:
            return text
        digits = "".join(c for c in text if c.isdigit())
        if digits and 100 <= int(digits) <= 10000:
            return digits
        raise ValueError("Size is one of " + ", ".join(PRESETS) + ", or a number of pixels from 100 to 10000.")


async def resize_photos(args: ResizeArgs, ctx: ToolContext) -> ToolResult:
    src = existing_folder(ctx, args.folder)
    photos = _photos_in(src)
    longest = PRESETS.get(args.size, 0) or int(args.size)
    base = existing_folder(ctx, args.save_in, write=True) if args.save_in else src.parent
    dest = unique_path(base / safe_file_name(f"{src.name} {args.size}", ""))
    ctx.policy.check_path(dest, write=True)

    def work():
        dest.mkdir(parents=True, exist_ok=True)
        made, skipped = [], []
        for p in photos:
            try:
                with Image.open(p) as img:
                    img.load()
                    small = _fit(img, longest)
                    keep_png = args.keep_format and p.suffix.lower() == ".png"
                    if keep_png:
                        out = dest / safe_file_name(p.stem, ".png")
                        small.save(out, "PNG", optimize=True)
                    else:
                        out = dest / safe_file_name(p.stem, ".jpg")
                        _flatten(small).save(out, "JPEG", quality=args.quality, optimize=True)
                made.append((p, out))
            except Exception as exc:  # noqa: BLE001 - one bad photo must not stop the batch
                skipped.append((p.name, type(exc).__name__))
        return made, skipped

    made, skipped = await asyncio.to_thread(work)
    if not made:
        raise ToolError(f"None of the {len(photos)} pictures in {src.name} could be read.")

    # Measured from the files that are actually there, not from what was planned.
    before = sum(p.stat().st_size for p, _ in made)
    after = sum(o.stat().st_size for _, o in made if o.is_file())
    on_disk = [p for p in dest.iterdir() if p.is_file()]
    ok = len(on_disk) == len(made)
    with Image.open(made[0][1]) as sample:
        shape = f"{sample.width}x{sample.height}"

    ctx.memory.outputs.append({"path": str(dest), "kind": "folder", "verified": ok})
    saved = f"{_size(before)} down to {_size(after)}" + (
        f", {round((before - after) * 100 / before)}% smaller" if before and after < before else "")
    note = f" {len(skipped)} could not be read and were left out." if skipped else ""
    return ToolResult(
        ok,
        f"Made {len(on_disk)} smaller copy(ies) of the pictures in {src.name}, longest side "
        f"{longest}px (first one is {shape}), in the folder '{dest.name}'. {saved}."
        + note + f" The originals in {src.name} are untouched.",
        {"folder": str(dest), "count": len(on_disk), "bytes_before": before,
         "bytes_after": after, "skipped": [n for n, _ in skipped]}, verified=ok)


# ---------- the shop's name on the pictures ----------
class WatermarkArgs(ToolArgs):
    folder: str = Field(min_length=1, max_length=500)
    text: str = Field(min_length=1, max_length=60, description="e.g. your shop's name")
    position: str = Field(default="bottom right",
                          description="bottom right, bottom left, top right, top left, or centre")
    opacity: int = Field(default=55, ge=10, le=100, description="How strong, in percent")
    save_in: str | None = Field(default=None, max_length=500)


CORNERS = ("bottom right", "bottom left", "top right", "top left", "centre", "center", "middle")


async def watermark_photos(args: WatermarkArgs, ctx: ToolContext) -> ToolResult:
    where = args.position.strip().lower()
    if where not in CORNERS:
        raise ToolError("Position is one of: " + ", ".join(CORNERS[:5]) + ".")
    src = existing_folder(ctx, args.folder)
    photos = _photos_in(src)
    base = existing_folder(ctx, args.save_in, write=True) if args.save_in else src.parent
    dest = unique_path(base / safe_file_name(f"{src.name} marked", ""))
    ctx.policy.check_path(dest, write=True)
    text = args.text.strip()

    def work():
        dest.mkdir(parents=True, exist_ok=True)
        made, skipped = [], []
        for p in photos:
            try:
                with Image.open(p) as img:
                    img.load()
                    canvas = _flatten(img).convert("RGBA")
                    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
                    draw = ImageDraw.Draw(layer)
                    # Sized from the picture, so it reads the same on a small
                    # photo and a large one.
                    size = max(14, int(min(canvas.size) * 0.045))
                    font = _font(size)
                    # Pillow's box is where the glyphs land when drawn AT
                    # (0, 0), and its left and top are usually not zero. Using
                    # only the width to right-align puts the text that much
                    # too far over - enough to sit on the edge of the picture,
                    # which is what the first version did.
                    box = draw.textbbox((0, 0), text, font=font)
                    left, top, right, bottom = box
                    tw, th = right - left, bottom - top
                    pad = max(10, int(min(canvas.size) * 0.025))
                    far_x = canvas.width - pad - right
                    far_y = canvas.height - pad - bottom
                    spots = {
                        "bottom right": (far_x, far_y),
                        "bottom left": (pad - left, far_y),
                        "top right": (far_x, pad - top),
                        "top left": (pad - left, pad - top),
                        "centre": ((canvas.width - tw) // 2 - left, (canvas.height - th) // 2 - top),
                    }
                    spots["center"] = spots["middle"] = spots["centre"]
                    x, y = spots[where]
                    alpha = int(255 * args.opacity / 100)
                    # A dark edge behind the letters so the name stays
                    # readable over a pale photograph as well as a dark one.
                    draw.text((x + 2, y + 2), text, font=font, fill=(0, 0, 0, int(alpha * 0.5)))
                    draw.text((x, y), text, font=font, fill=(255, 255, 255, alpha))
                    out = dest / safe_file_name(p.stem, ".jpg")
                    Image.alpha_composite(canvas, layer).convert("RGB").save(
                        out, "JPEG", quality=90, optimize=True)
                made.append(out)
            except Exception as exc:  # noqa: BLE001
                skipped.append(p.name)
        return made, skipped

    made, skipped = await asyncio.to_thread(work)
    if not made:
        raise ToolError(f"None of the {len(photos)} pictures in {src.name} could be read.")
    on_disk = [p for p in dest.iterdir() if p.is_file()]
    ok = len(on_disk) == len(made)
    ctx.memory.outputs.append({"path": str(dest), "kind": "folder", "verified": ok})
    note = f" {len(skipped)} could not be read and were left out." if skipped else ""
    return ToolResult(
        ok,
        f"Put '{text}' on {len(on_disk)} picture(s) from {src.name} ({where}), in the folder "
        f"'{dest.name}'. Counted them afterwards.{note} The originals are untouched.",
        {"folder": str(dest), "count": len(on_disk), "text": text}, verified=ok)


def _font(size: int):
    """A real font if one is installed, Pillow's built-in if not.

    The built-in font does not scale, so a watermark drawn with it is small.
    Saying which was used matters more than pretending they are the same.
    """
    for name in ("DejaVuSans-Bold.ttf", "DejaVuSans.ttf", "Arial.ttf", "arial.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


# ---------- QR codes ----------
class QrArgs(ToolArgs):
    content: str = Field(min_length=1, max_length=900,
                         description="A link, phone number, or any text")
    label: str = Field(default="", max_length=60, description="Words printed under the code")
    file_name: str = Field(default="", max_length=120)
    folder: str | None = Field(default=None, max_length=500)
    size: int = Field(default=600, ge=200, le=2000, description="Picture size in pixels")


async def make_qr_code(args: QrArgs, ctx: ToolContext) -> ToolResult:
    import segno  # noqa: PLC0415

    content = args.content.strip()
    folder = existing_folder(ctx, args.folder, write=True) if args.folder else existing_folder(ctx, None, write=True)
    out = unique_path(folder / safe_file_name(args.file_name or "qr code", ".png"))
    ctx.policy.check_path(out, write=True)

    def work():
        # High error correction: a printed code gets creased, smudged and
        # photographed badly, and h recovers from about a third of it being
        # unreadable.
        code = segno.make(content, error="h")
        tmp = out.with_suffix(".tmp.png")
        scale = max(4, args.size // (code.symbol_size(scale=1)[0] or 25))
        code.save(str(tmp), scale=scale, border=4)
        img = Image.open(tmp).convert("RGB")
        if args.label:
            font = _font(max(16, img.width // 18))
            draw = ImageDraw.Draw(img)
            box = draw.textbbox((0, 0), args.label, font=font)
            th = box[3] - box[1]
            tall = Image.new("RGB", (img.width, img.height + th + 24), (255, 255, 255))
            tall.paste(img, (0, 0))
            d2 = ImageDraw.Draw(tall)
            d2.text(((img.width - (box[2] - box[0])) // 2, img.height + 8), args.label,
                    font=font, fill=(0, 0, 0))
            img = tall
        img.save(out, "PNG", optimize=True)
        tmp.unlink(missing_ok=True)
        return img.size

    size = await asyncio.to_thread(work)
    decoded = await asyncio.to_thread(_read_back, out)
    ok = decoded == content
    ctx.memory.outputs.append({"path": str(out), "kind": "image", "verified": ok})
    if decoded is None:
        check = ("Claw could not read it back to check (no QR reader installed), so scan it once "
                 "before printing it on anything.")
    elif ok:
        check = "Read it back from the saved picture and it matches."
    else:
        check = f"WARNING: reading it back gave something else ({decoded[:40]!r})."
    return ToolResult(
        ok or decoded is None,
        f"Made a QR code for {content[:60]}{'...' if len(content) > 60 else ''} as {out.name} "
        f"({size[0]}x{size[1]}). {check}",
        {"path": str(out), "content": content, "checked": decoded is not None}, verified=ok)


def _read_back(path: Path) -> str | None:
    """Scan the saved picture, so the code is known to work, not assumed to.

    Returns None when no reader is installed - that is "not checked", which
    is said out loud rather than counted as a pass.
    """
    try:
        import zxingcpp  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        pass
    else:
        try:
            found = zxingcpp.read_barcode(Image.open(path))
            return found.text if found else ""
        except Exception:  # noqa: BLE001
            return None
    try:
        from pyzbar.pyzbar import decode  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        pass
    else:
        try:
            found = decode(Image.open(path))
            return found[0].data.decode("utf-8") if found else ""
        except Exception:  # noqa: BLE001
            return None
    try:
        import cv2  # noqa: PLC0415
        import numpy  # noqa: PLC0415
        text, _, _ = cv2.QRCodeDetector().detectAndDecode(
            numpy.array(Image.open(path).convert("RGB"))[:, :, ::-1])
        return text
    except Exception:  # noqa: BLE001
        return None


def register_batch_image_tools(reg: ToolRegistry) -> None:
    reg.register(ToolSpec(
        "resize_photos", "Make smaller copies of every picture in a folder, for WhatsApp, e-mail "
                         "or a website; says how much space was saved.",
        Capability.DESIGN, RiskLevel.LOCAL_WRITE, ResizeArgs, resize_photos))
    reg.register(ToolSpec(
        "watermark_photos", "Put your name across every picture in a folder, into a new folder.",
        Capability.DESIGN, RiskLevel.LOCAL_WRITE, WatermarkArgs, watermark_photos))
    reg.register(ToolSpec(
        "make_qr_code", "Make a QR code for a link, phone number or text, and read it back to check it.",
        Capability.DESIGN, RiskLevel.LOCAL_WRITE, QrArgs, make_qr_code))
