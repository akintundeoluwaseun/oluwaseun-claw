"""Image tools: make a promotional flyer, edit an image, inspect an image."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Literal

from claw.integrations.pillow import Image, ImageEnhance, ImageOps
from pydantic import Field, field_validator

from claw.agent.schemas import Capability
from claw.integrations import images as im
from claw.permissions.policy import PathNotAuthorized, RiskLevel
from claw.tools.base import ToolArgs, ToolContext, ToolError, ToolRegistry, ToolResult, ToolSpec
from claw.tools.file_tools import resolve_folder, safe_file_name, unique_path

IMAGE_IN = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff"}
MAX_PIXELS = 60_000_000


def _input_image(ctx: ToolContext, raw: str) -> Path:
    try:
        p = ctx.policy.check_path(raw)
    except PathNotAuthorized as exc:
        raise ToolError(str(exc)) from exc
    if not p.is_file():
        raise ToolError(f"There is no file at {p}.")
    if p.suffix.lower() not in IMAGE_IN:
        raise ToolError(f"{p.name} is not a picture Claw can open (PNG, JPG, BMP, GIF, WebP, TIFF).")
    try:
        with Image.open(p) as probe:
            if probe.width * probe.height > MAX_PIXELS:
                raise ToolError(f"{p.name} is too large ({probe.width}×{probe.height}).")
    except (OSError, Image.DecompressionBombError) as exc:
        raise ToolError(f"{p.name} could not be opened as a picture (it may be damaged).") from exc
    ctx.memory.note_file(p)
    return p


def _output(ctx: ToolContext, folder: str | None, name: str, ext: str) -> Path:
    out = unique_path(resolve_folder(ctx, folder) / safe_file_name(name, ext))
    ctx.policy.check_path(out, write=True)
    return out


def _ocr_words(path_or_img) -> tuple[bool, str]:
    """Read the picture back with OCR (if installed). Returns (ocr ran, text)."""
    from claw.documents.ocr import TesseractEngine

    eng = TesseractEngine()
    if not eng.available("eng")[0]:
        return False, ""
    tmp = im.temp_png()
    try:
        img = path_or_img if isinstance(path_or_img, Image.Image) else Image.open(path_or_img)
        img.convert("RGB").save(tmp)
        return True, eng.recognize(tmp, "eng").text
    finally:
        tmp.unlink(missing_ok=True)


def _title_seen(title: str, text: str) -> float:
    want = [w for w in re.findall(r"[a-z0-9]+", title.lower()) if len(w) > 2]
    got = set(re.findall(r"[a-z0-9]+", text.lower()))
    return sum(w in got for w in want) / len(want) if want else 1.0


# ---------- make_flyer ----------
class FlyerArgs(ToolArgs):
    title: str = Field(min_length=2, max_length=120, description="Headline")
    subtitle: str = Field(default="", max_length=200)
    points: list[str] = Field(default_factory=list, max_length=6, description="Up to 6 short selling points")
    contact: str = Field(default="", max_length=120, description="Phone, WhatsApp, website or address line")
    size: Literal["square", "story", "a5", "a4", "landscape"] = "a5"
    background: str = Field(default="#14212b", pattern=r"^#?[0-9a-fA-F]{3}([0-9a-fA-F]{3})?$")
    accent: str = Field(default="#3cc2aa", pattern=r"^#?[0-9a-fA-F]{3}([0-9a-fA-F]{3})?$")
    images: list[str] = Field(default_factory=list, max_length=4, description="Pictures to use, from authorized folders")
    file_name: str = Field(default="flyer", max_length=80)
    format: Literal["png", "jpg", "pdf", "psd"] = "png"
    folder: str | None = Field(default=None, max_length=500)
    editor: Literal["auto", "photoshop", "builtin"] = Field(
        default="auto", description="auto: Photoshop if installed, else Claw's built-in editor; photoshop: only Photoshop")


def check_flyer(args: FlyerArgs, ctx: ToolContext) -> None:
    for p in args.images:
        _input_image(ctx, p)
    resolve_folder(ctx, args.folder)
    if args.format == "psd" and args.editor == "builtin":
        raise ToolError("PSD files can only be made with Photoshop.")
    if args.editor == "photoshop":
        ok, why = im.photoshop_available()
        if not ok:
            raise ToolError(f"{why} Claw can make the flyer with its built-in editor instead, if you agree.")


async def make_flyer(args: FlyerArgs, ctx: ToolContext) -> ToolResult:
    check_flyer(args, ctx)
    spec = im.FlyerSpec(args.title, args.subtitle, args.points, args.contact, im.PRESETS[args.size],
                        "#" + args.background.lstrip("#"), "#" + args.accent.lstrip("#"), [_input_image(ctx, p) for p in args.images])
    out = _output(ctx, args.folder, args.file_name, "." + args.format)
    use_ps = args.editor == "photoshop" or (args.editor == "auto" and im.photoshop_available()[0])
    if args.format == "psd" and not use_ps:
        raise ToolError("PSD files can only be made with Photoshop, which is not installed. Choose PNG, JPG or PDF.")
    if use_ps:
        try:
            await asyncio.to_thread(im.run_photoshop, spec, out)
        except Exception as exc:  # noqa: BLE001 — COM errors are varied
            raise ToolError(f"Photoshop could not make the flyer: {str(exc)[:200]}") from exc
        editor = "Photoshop"
        rendered = None
    else:
        rendered = await asyncio.to_thread(im.render_flyer, spec)
        await asyncio.to_thread(im.save_image, rendered, out)
        editor = "Claw's built-in image editor (Photoshop was not used)"
    info = await asyncio.to_thread(im.inspect, out) if args.format != "pdf" else {"format": "PDF", "bytes": out.stat().st_size}
    size_ok = args.format == "pdf" or (info["width"], info["height"]) == spec.size
    ran, text = await asyncio.to_thread(_ocr_words, rendered if rendered is not None else out) if args.format != "psd" else (False, "")
    seen = _title_seen(args.title, text) if ran else None
    ok = out.is_file() and size_ok and (seen is None or seen >= 0.6)
    check = (f"OCR read {round(seen * 100)}% of the headline words back from the image" if seen is not None
             else "headline not checked (OCR not available)")
    ctx.memory.outputs.append({"path": str(out), "kind": "image", "verified": ok, "note": "" if ok else check})
    dims = f"{info['width']}×{info['height']} " if "width" in info else ""
    return ToolResult(True, f"Made the flyer with {editor}: {out.name} ({dims}{info['format']}); {check}.",
                      {"path": str(out), "editor": editor, **info, "headline_seen": seen}, verified=ok)


# ---------- edit_image ----------
class EditArgs(ToolArgs):
    path: str = Field(min_length=1, max_length=500)
    resize_width: int | None = Field(default=None, ge=16, le=10000, description="Keeps proportions if height is not given")
    resize_height: int | None = Field(default=None, ge=16, le=10000)
    crop: list[int] | None = Field(default=None, min_length=4, max_length=4, description="[left, top, right, bottom] in pixels")
    rotate: Literal[0, 90, 180, 270] = 0
    brightness: float = Field(default=1.0, ge=0.2, le=3.0)
    contrast: float = Field(default=1.0, ge=0.2, le=3.0)
    grayscale: bool = False
    format: Literal["same", "png", "jpg", "webp", "pdf"] = "same"
    file_name: str | None = Field(default=None, max_length=80)
    folder: str | None = Field(default=None, max_length=500)

    @field_validator("crop")
    @classmethod
    def _box(cls, v):
        if v is not None and (v[2] <= v[0] or v[3] <= v[1]):
            raise ValueError("crop must be [left, top, right, bottom] with right > left and bottom > top")
        return v


async def edit_image(args: EditArgs, ctx: ToolContext) -> ToolResult:
    src = _input_image(ctx, args.path)

    def work():
        img = ImageOps.exif_transpose(Image.open(src))
        done = []
        if args.crop:
            l, t, r, b = args.crop
            if r > img.width or b > img.height:
                raise ToolError(f"The crop box goes outside the picture ({img.width}×{img.height}).")
            img = img.crop((l, t, r, b))
            done.append("cropped")
        if args.rotate:
            img = img.rotate(-args.rotate, expand=True)
            done.append(f"rotated {args.rotate}°")
        if args.resize_width or args.resize_height:
            w = args.resize_width or round(img.width * args.resize_height / img.height)
            h = args.resize_height or round(img.height * args.resize_width / img.width)
            img = img.resize((w, h), Image.LANCZOS)
            done.append(f"resized to {w}×{h}")
        if args.grayscale:
            img = ImageOps.grayscale(img)
            done.append("black and white")
        if args.brightness != 1.0:
            img = ImageEnhance.Brightness(img.convert("RGB")).enhance(args.brightness)
            done.append(f"brightness ×{args.brightness}")
        if args.contrast != 1.0:
            img = ImageEnhance.Contrast(img.convert("RGB")).enhance(args.contrast)
            done.append(f"contrast ×{args.contrast}")
        if not done and args.format == "same":
            raise ToolError("No change was asked for.")
        ext = src.suffix.lower() if args.format == "same" else "." + args.format
        if ext not in im.FORMATS:
            ext = ".png"
        out = _output(ctx, args.folder or str(src.parent), args.file_name or f"{src.stem} edited", ext)
        im.save_image(img, out)
        return out, img.size, done

    out, size, done = await asyncio.to_thread(work)
    info = await asyncio.to_thread(im.inspect, out) if out.suffix.lower() != ".pdf" else {"format": "PDF", "width": size[0], "height": size[1]}
    ok = (info["width"], info["height"]) == size
    ctx.memory.outputs.append({"path": str(out), "kind": "image", "verified": ok, "note": ""})
    return ToolResult(True, f"Saved {out.name} ({', '.join(done) or 'converted'}; {info['width']}×{info['height']} {info['format']}). "
                      "The original is unchanged.", {"path": str(out), **info}, verified=ok)


# ---------- inspect_image ----------
class InspectArgs(ToolArgs):
    path: str = Field(min_length=1, max_length=500)


async def inspect_image(args: InspectArgs, ctx: ToolContext) -> ToolResult:
    p = _input_image(ctx, args.path)
    info = await asyncio.to_thread(im.inspect, p)
    return ToolResult(True, f"{p.name}: {info['width']}×{info['height']} {info['format']} ({info['bytes']:,} bytes).", {"path": str(p), **info}, verified=True)


def register_image_tools(reg: ToolRegistry) -> None:
    F, W = Capability.DOCUMENTS, RiskLevel.LOCAL_WRITE
    reg.register(ToolSpec("make_flyer",
                          "Design a promotional flyer (headline, points, contact, pictures) and save it. Uses Photoshop if installed, "
                          "otherwise Claw's built-in editor, and says which.", F, W, FlyerArgs, make_flyer, precheck=check_flyer))
    reg.register(ToolSpec("edit_image", "Crop, rotate, resize, brighten, adjust contrast, make black-and-white or convert a picture; saves a new file.",
                          F, W, EditArgs, edit_image))
    reg.register(ToolSpec("inspect_image", "Check a picture's format and size.", F, RiskLevel.READ_ONLY, InspectArgs, inspect_image))
