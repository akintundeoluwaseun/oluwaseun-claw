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
from claw.tools.base import (ToolArgs, ToolContext, ToolError, ToolRegistry, ToolResult, ToolSpec,
                             as_int_list, as_str_list)
from claw.tools.file_tools import resolve_folder, safe_file_name, unique_path

IMAGE_IN = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff"}
MAX_PIXELS = 60_000_000


def _beside(pics: list[Path]) -> str | None:
    """The folder the pictures came from, when they all came from one.

    "Make a flyer with the pictures in this folder" ends with the flyer in the
    first authorized folder, which is usually not the folder being talked
    about: the person said "do everything there" and Claw put the result
    somewhere else. The single-picture tools already save beside their input -
    brighten_photo, passport_photo, product_shadow all do - so this is that
    rule applied where several pictures agree on an answer, not a new one.

    None when they disagree or there are none, and an explicit folder always
    wins.
    """
    parents = {p.parent for p in pics}
    return str(parents.pop()) if len(parents) == 1 else None


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


#: Enough for a collage; past this a design is a contact sheet, not a design.
MAX_FROM_FOLDER = 16


def _images_in(ctx: ToolContext, folder: Path) -> list[Path]:
    """Every picture directly inside a folder, in name order."""
    found = sorted((p for p in folder.iterdir()
                    if p.is_file() and p.suffix.lower() in IMAGE_IN), key=lambda p: p.name.lower())
    out = []
    for p in found[:MAX_FROM_FOLDER]:
        try:
            out.append(_input_image(ctx, str(p)))
        except ToolError:
            continue          # a damaged or enormous file in the folder is skipped, not fatal
    return out


def _usable_images(ctx: ToolContext, raws: list[str]) -> list[Path]:
    """Pictures for a design. Accepts files, a folder, or a pattern like Photos/*.jpg.

    "Make a flyer with the pictures in this folder" is how a person says it, and
    it used to need the brain to list the folder first and pass every name back.
    A 2B brain often does not: it passes the folder, the tool says that is not a
    file, and the flyer fails on a request that was perfectly clear. Listing a
    folder is deterministic work, so the tool does it rather than spending a
    planning step and the brain's judgement on it.

    One the brain made up ("logo.png") is still left out rather than fatal: seen
    on Windows, a whole flyer failed over an invented logo file.
    """
    out: list[Path] = []
    for raw in raws:
        text = str(raw).strip()
        if not text:
            continue
        # A pattern: let the folder it names do the matching.
        if any(ch in text for ch in "*?"):
            parent, _, pattern = text.replace("\\", "/").rpartition("/")
            try:
                base = ctx.policy.check_path(parent or ".")
            except PathNotAuthorized as exc:
                raise ToolError(str(exc)) from exc
            if base.is_dir():
                for p in sorted(base.glob(pattern))[:MAX_FROM_FOLDER]:
                    if p.is_file() and p.suffix.lower() in IMAGE_IN:
                        try:
                            out.append(_input_image(ctx, str(p)))
                        except ToolError:
                            continue
                continue
        try:
            resolved = ctx.policy.check_path(text)
        except PathNotAuthorized as exc:
            raise ToolError(str(exc)) from exc
        if resolved.is_dir():
            inside = _images_in(ctx, resolved)
            if not inside:
                raise ToolError(f"There are no pictures in {resolved.name}.")
            out.extend(inside)
            continue
        try:
            out.append(_input_image(ctx, text))
        except ToolError as exc:
            if "There is no file" not in exc.message:
                raise
    # The same picture named twice (once by itself, once inside its folder) is
    # one picture.
    seen, unique = set(), []
    for p in out:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


def _title_seen(title: str, text: str) -> float:
    want = [w for w in re.findall(r"[a-z0-9]+", title.lower()) if len(w) > 2]
    got = set(re.findall(r"[a-z0-9]+", text.lower()))
    return sum(w in got for w in want) / len(want) if want else 1.0


# ---------- make_flyer ----------
_COLOURS = {
    "black": "#111111", "white": "#ffffff", "grey": "#808080", "gray": "#808080", "silver": "#c0c0c0",
    "red": "#d62828", "dark red": "#7a0c0c", "maroon": "#800000", "orange": "#f77f00", "yellow": "#fcbf49",
    "gold": "#d4a017", "green": "#2a9d8f", "dark green": "#1b4332", "lime": "#80b918", "teal": "#14857a",
    "blue": "#1d4ed8", "dark blue": "#14213d", "navy": "#14213d", "navy blue": "#14213d", "light blue": "#7cc6fe",
    "sky blue": "#4cc9f0", "cyan": "#00b4d8", "purple": "#6a4c93", "violet": "#7b2cbf", "pink": "#ff70a6",
    "brown": "#7f4f24", "beige": "#e9d8a6", "cream": "#fff3d6",
}
class FlyerArgs(ToolArgs):
    title: str = Field(min_length=2, max_length=120, description="Headline")
    subtitle: str = Field(default="", max_length=200)
    points: list[str] = Field(default_factory=list, max_length=6, description="Up to 6 short selling points")
    contact: str = Field(default="", max_length=120, description="Phone, WhatsApp, website or address line")
    size: Literal["square", "story", "a5", "a4", "landscape"] = "a5"
    background: str = Field(default="#14212b", pattern=r"^#?[0-9a-fA-F]{3}([0-9a-fA-F]{3})?$",
                            description="A colour: #RRGGBB or a plain name like navy")
    accent: str = Field(default="#3cc2aa", pattern=r"^#?[0-9a-fA-F]{3}([0-9a-fA-F]{3})?$",
                        description="A colour: #RRGGBB or a plain name like gold")

    @field_validator("points", "images", mode="before")
    @classmethod
    def _lists(cls, v, info):
        return as_str_list(v, 6 if info.field_name == "points" else 4)

    @field_validator("background", "accent", mode="before")
    @classmethod
    def _named_colours(cls, v, info):
        # The brain wrote "dark blue" and "orange" on Windows and the flyer was refused.
        # A colour name it might reasonably use becomes its hex; anything else unknown
        # falls back to the default instead of failing the whole flyer.
        if not isinstance(v, str):
            return v
        t = v.strip().lower().replace("-", " ")
        if re.fullmatch(r"#?[0-9a-f]{3}([0-9a-f]{3})?", t):
            return t
        hexed = _COLOURS.get(t) or _COLOURS.get(t.split()[-1] if t else "")
        return hexed or ("#14212b" if info.field_name == "background" else "#3cc2aa")
    images: list[str] = Field(default_factory=list, max_length=4, description="Files, a folder, or Photos/*.jpg")
    file_name: str = Field(default="flyer", max_length=80)
    format: Literal["png", "jpg", "pdf", "psd"] = "png"
    folder: str | None = Field(default=None, max_length=500)
    editor: Literal["auto", "photoshop", "builtin"] = Field(
        default="auto", description="auto: Photoshop if installed, else Claw's built-in editor; photoshop: only Photoshop")


def check_flyer(args: FlyerArgs, ctx: ToolContext) -> None:
    _usable_images(ctx, args.images)  # a made-up picture is skipped here too, not fatal
    resolve_folder(ctx, args.folder)
    if args.format == "psd" and args.editor == "builtin":
        raise ToolError("PSD files can only be made with Photoshop.")
    if args.editor == "photoshop":
        ok, why = im.photoshop_available()
        if not ok:
            raise ToolError(f"{why} Claw can make the flyer with its built-in editor instead, if you agree.")


async def make_flyer(args: FlyerArgs, ctx: ToolContext) -> ToolResult:
    check_flyer(args, ctx)
    pics = _usable_images(ctx, args.images)
    spec = im.FlyerSpec(args.title, args.subtitle, args.points, args.contact, im.PRESETS[args.size],
                        "#" + args.background.lstrip("#"), "#" + args.accent.lstrip("#"), pics)
    out = _output(ctx, args.folder or _beside(pics), args.file_name, "." + args.format)
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


# ---------- make_campaign (one design, every size) ----------
CAMPAIGN_SIZES = ("square", "portrait", "story", "landscape", "banner", "cover", "a5", "a4")


class CampaignArgs(FlyerArgs):
    sizes: list[Literal["square", "portrait", "story", "landscape", "banner", "cover", "a5", "a4"]] = Field(
        default_factory=lambda: ["square", "story", "landscape", "a5"], min_length=1, max_length=8,
        description="square post, portrait post, story, landscape, banner (X header), cover (Facebook), a5, a4")
    file_name: str = Field(default="campaign", max_length=80)
    format: Literal["png", "jpg", "pdf", "psd"] = "png"

    @field_validator("sizes", mode="before")
    @classmethod
    def _size_words(cls, v):
        if isinstance(v, str):
            v = [x for x in re.split(r"[,\s]+", v) if x]
        if isinstance(v, list):  # "instagram story" / "facebook cover" / "twitter header" -> the size names
            alias = {"post": "square", "instagram": "square", "status": "story", "reel": "story", "header": "banner",
                     "twitter": "banner", "x": "banner", "facebook": "cover", "youtube": "landscape", "poster": "a4",
                     "flyer": "a5", "print": "a5"}
            out = []
            for x in v:
                t = str(x).strip().lower()
                t = t if t in CAMPAIGN_SIZES else next((alias[w] for w in reversed(t.split()) if w in alias), t)
                if t not in out:
                    out.append(t)
            return out
        return v


async def make_campaign(args: CampaignArgs, ctx: ToolContext) -> ToolResult:
    check_flyer(args, ctx)
    base = resolve_folder(ctx, args.folder)
    folder = unique_path(base / safe_file_name(args.file_name, ""))
    ctx.policy.check_path(folder, write=True)
    folder.mkdir(parents=True)
    pictures = _usable_images(ctx, args.images)
    use_ps = args.editor == "photoshop" or (args.editor == "auto" and im.photoshop_available()[0])
    if args.format == "psd" and not use_ps:
        raise ToolError("PSD files can only be made with Photoshop, which is not installed. Choose PNG, JPG or PDF.")
    made, problems = [], []
    for size in args.sizes:
        spec = im.FlyerSpec(args.title, args.subtitle, args.points, args.contact, im.PRESETS[size],
                            "#" + args.background.lstrip("#"), "#" + args.accent.lstrip("#"), pictures)
        out = folder / safe_file_name(f"{args.file_name} {size} {spec.size[0]}x{spec.size[1]}", "." + args.format)
        rendered = None
        try:
            if use_ps:
                await asyncio.to_thread(im.run_photoshop, spec, out)
            else:
                rendered = await asyncio.to_thread(im.render_flyer, spec)
                await asyncio.to_thread(im.save_image, rendered, out)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{size}: {str(exc)[:120]}")
            continue
        info = await asyncio.to_thread(im.inspect, out) if args.format != "pdf" else {"format": "PDF"}
        size_ok = args.format == "pdf" or (info.get("width"), info.get("height")) == spec.size
        ran, text = await asyncio.to_thread(_ocr_words, rendered if rendered is not None else out) if args.format != "psd" else (False, "")
        seen = _title_seen(args.title, text) if ran else None
        ok = out.is_file() and size_ok and (seen is None or seen >= 0.6)
        if not ok:
            problems.append(f"{size}: " + ("wrong size" if not size_ok else f"headline only {round((seen or 0) * 100)}% readable"))
        made.append({"size": size, "path": str(out), "width": spec.size[0], "height": spec.size[1], "verified": ok,
                     "headline_seen": seen})
        ctx.memory.outputs.append({"path": str(out), "kind": "image", "verified": ok, "note": ""})
    if not made:
        raise ToolError("None of the sizes could be made: " + "; ".join(problems))
    editor = "Photoshop" if use_ps else "Claw's built-in image editor (Photoshop was not used)"
    ok = not problems and len(made) == len(args.sizes)
    checked = sum(1 for m in made if m["headline_seen"] is not None)
    listing = ", ".join(f"{m['size']} {m['width']}×{m['height']}" for m in made)
    return ToolResult(True, f"Made the campaign with {editor} in {len(made)} size(s) in the folder {folder.name}: {listing}. "
                            f"Each file reopened and its size checked; headline read back with OCR on {checked}."
                            + (f" Problems: {'; '.join(problems)}." if problems else ""),
                      {"folder": str(folder), "files": made, "editor": editor}, verified=ok)


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

    @field_validator("crop", mode="before")
    @classmethod
    def _as_box(cls, v):
        return as_int_list(v, 4)



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


# ---------- Milestone 8: the design jobs that do not need Photoshop ----------
# Each of these saves a new file, reopens it and reports its real size, exactly
# as make_flyer does. None of them claims a Photoshop path it does not have.

class PosterArgs(ToolArgs):
    title: str = Field(min_length=1, max_length=120)
    style: Literal["poster", "thumbnail", "magazine"] = "poster"
    images: list[str] = Field(default_factory=list, max_length=5, description="Files, a folder, or a pattern; first is the background")
    subtitle: str = Field(default="", max_length=160)
    tagline: str = Field(default="", max_length=160)
    credits: str = Field(default="", max_length=400)
    cover_lines: list[str] = Field(default_factory=list, max_length=5)
    background: str = Field(default="#0d0f14", pattern=r"^#?[0-9a-fA-F]{3}([0-9a-fA-F]{3})?$")
    accent: str = Field(default="#e4b43c", pattern=r"^#?[0-9a-fA-F]{3}([0-9a-fA-F]{3})?$")
    file_name: str = Field(default="poster", max_length=80)

    @field_validator("images", "cover_lines", mode="before")
    @classmethod
    def _lists(cls, v, info):
        return as_str_list(v, 5)

    format: Literal["png", "jpg", "pdf"] = "png"
    folder: str | None = Field(default=None, max_length=500)


def check_poster(args: PosterArgs, ctx: ToolContext) -> None:
    """Same checks as a flyer minus the Photoshop ones: these layouts are the
    built-in editor's only, so there is no editor to choose."""
    _usable_images(ctx, args.images)
    resolve_folder(ctx, args.folder)


async def make_poster(args: PosterArgs, ctx: ToolContext) -> ToolResult:
    pics = _usable_images(ctx, args.images)
    out = _output(ctx, args.folder or _beside(pics), args.file_name, "." + args.format)

    def work():
        img = im.render_poster(im.PosterSpec(
            title=args.title, images=pics, style=args.style, subtitle=args.subtitle,
            tagline=args.tagline, credits=args.credits, cover_lines=args.cover_lines,
            background=args.background, accent=args.accent))
        im.save_image(img, out)
        return img.size

    size = await asyncio.to_thread(work)
    info = await asyncio.to_thread(im.inspect, out) if out.suffix.lower() != ".pdf" else {"format": "PDF", "width": size[0], "height": size[1]}
    ok = (info["width"], info["height"]) == size
    ctx.memory.outputs.append({"path": str(out), "kind": "image", "verified": ok, "note": args.style})
    return ToolResult(True, f"Saved {out.name}: a {args.style} at {info['width']}×{info['height']}, "
                      f"made with Claw's built-in editor from {len(pics)} picture(s).",
                      {"path": str(out), "style": args.style, **info}, verified=ok)


class CollageArgs(ToolArgs):
    images: list[str] = Field(min_length=1, max_length=16, description="Files, a folder, or a pattern")
    size: Literal["square", "a4", "landscape", "story"] = "square"
    even_exposure: bool = True
    background: str = Field(default="#101317", pattern=r"^#?[0-9a-fA-F]{3}([0-9a-fA-F]{3})?$")
    file_name: str = Field(default="collage", max_length=80)

    @field_validator("images", mode="before")
    @classmethod
    def _lists(cls, v):
        return as_str_list(v, 16)

    format: Literal["png", "jpg", "pdf"] = "png"
    folder: str | None = Field(default=None, max_length=500)


async def make_collage(args: CollageArgs, ctx: ToolContext) -> ToolResult:
    pics = _usable_images(ctx, args.images)
    if not pics:
        raise ToolError("None of those pictures could be found in an authorized folder.")
    out = _output(ctx, args.folder or _beside(pics), args.file_name, "." + args.format)
    box = {"square": (2480, 2480), "a4": (2480, 3508), "landscape": (3508, 2480), "story": (1080, 1920)}[args.size]

    def work():
        sheet, n = im.render_collage(pics, box, args.background, even_exposure=args.even_exposure)
        im.save_image(sheet, out)
        return sheet.size, n

    (size, n) = await asyncio.to_thread(work)
    info = await asyncio.to_thread(im.inspect, out) if out.suffix.lower() != ".pdf" else {"format": "PDF", "width": size[0], "height": size[1]}
    ok = (info["width"], info["height"]) == size and n == len(pics)
    ctx.memory.outputs.append({"path": str(out), "kind": "image", "verified": ok, "note": f"{n} pictures"})
    return ToolResult(True, f"Saved {out.name}: {n} picture(s) at {info['width']}×{info['height']}"
                      + (", each levelled so the set matches." if args.even_exposure else "."),
                      {"path": str(out), "pictures": n, **info}, verified=ok)


class BrightenArgs(ToolArgs):
    path: str = Field(min_length=1, max_length=500)
    file_name: str | None = Field(default=None, max_length=80)
    folder: str | None = Field(default=None, max_length=500)


async def brighten_photo(args: BrightenArgs, ctx: ToolContext) -> ToolResult:
    src = _input_image(ctx, args.path)
    out = _output(ctx, args.folder or str(src.parent), args.file_name or f"{src.stem} brightened", src.suffix.lower() or ".png")

    def work():
        img, before, after = im.brighten(src)
        im.save_image(img, out)
        return img.size, before, after

    size, before, after = await asyncio.to_thread(work)
    info = await asyncio.to_thread(im.inspect, out)
    # The claim is a measurement: mean brightness before and after, out of 255.
    ok = (info["width"], info["height"]) == size and after > before
    ctx.memory.outputs.append({"path": str(out), "kind": "image", "verified": ok, "note": f"{before}->{after}"})
    return ToolResult(True, f"Saved {out.name}. Mean brightness {before} → {after} out of 255. The original is unchanged.",
                      {"path": str(out), "brightness_before": before, "brightness_after": after, **info}, verified=ok)


class PassportArgs(ToolArgs):
    path: str = Field(min_length=1, max_length=500)
    country: Literal["uk", "eu", "schengen", "ng", "us", "india"] = "uk"
    dpi: int = Field(default=300, ge=150, le=600)
    background: str | None = Field(default=None, pattern=r"^#?[0-9a-fA-F]{3}([0-9a-fA-F]{3})?$")
    file_name: str | None = Field(default=None, max_length=80)
    folder: str | None = Field(default=None, max_length=500)


async def passport_photo(args: PassportArgs, ctx: ToolContext) -> ToolResult:
    src = _input_image(ctx, args.path)
    out = _output(ctx, args.folder or str(src.parent), args.file_name or f"{src.stem} passport", ".png")

    def work():
        img, px, note = im.passport_crop(src, args.country, args.dpi, args.background)
        im.save_image(img, out)
        return px, note

    px, note = await asyncio.to_thread(work)
    info = await asyncio.to_thread(im.inspect, out)
    ok = (info["width"], info["height"]) == px
    ctx.memory.outputs.append({"path": str(out), "kind": "image", "verified": ok, "note": note})
    return ToolResult(True, f"Saved {out.name}: {info['width']}×{info['height']} pixels, {note}. "
                      "The crop is positional - Claw does not find the face - so check the head sits correctly before using it.",
                      {"path": str(out), "spec": note, **info}, verified=ok)


class ShadowArgs(ToolArgs):
    path: str = Field(min_length=1, max_length=500, description="Cut out, or on a plain background")
    background: str = Field(default="#ffffff", pattern=r"^#?[0-9a-fA-F]{3}([0-9a-fA-F]{3})?$")
    file_name: str | None = Field(default=None, max_length=80)
    folder: str | None = Field(default=None, max_length=500)


async def product_shadow(args: ShadowArgs, ctx: ToolContext) -> ToolResult:
    src = _input_image(ctx, args.path)
    out = _output(ctx, args.folder or str(src.parent), args.file_name or f"{src.stem} on shadow", ".png")

    def work():
        img, found = im.add_product_shadow(src, args.background)
        im.save_image(img, out)
        return img.size, found

    size, found = await asyncio.to_thread(work)
    info = await asyncio.to_thread(im.inspect, out)
    ok = (info["width"], info["height"]) == size and found
    note = ("a soft contact shadow under it" if found
            else "no subject could be separated from the background, so no shadow was added")
    ctx.memory.outputs.append({"path": str(out), "kind": "image", "verified": ok, "note": note})
    return ToolResult(True, f"Saved {out.name}: the product on {args.background} with {note}.",
                      {"path": str(out), "subject_found": found, **info}, verified=ok)


class CompareArgs(ToolArgs):
    before: str = Field(min_length=1, max_length=500)
    after: str = Field(min_length=1, max_length=500)
    file_name: str | None = Field(default=None, max_length=80)
    folder: str | None = Field(default=None, max_length=500)


async def compare_designs(args: CompareArgs, ctx: ToolContext) -> ToolResult:
    a, b = _input_image(ctx, args.before), _input_image(ctx, args.after)
    out = _output(ctx, args.folder or str(b.parent), args.file_name or f"{b.stem} differences", ".png")

    def work():
        marked, boxes, pct = im.compare_images(a, b)
        im.save_image(marked, out)
        return marked.size, boxes, pct

    size, boxes, pct = await asyncio.to_thread(work)
    info = await asyncio.to_thread(im.inspect, out)
    ok = (info["width"], info["height"]) == size
    where = "; ".join(f"({x0},{y0})-({x1},{y1})" for x0, y0, x1, y1 in boxes[:8])
    ctx.memory.outputs.append({"path": str(out), "kind": "image", "verified": ok, "note": f"{len(boxes)} regions"})
    msg = (f"{len(boxes)} region(s) differ, {pct}% of the picture. Marked in {out.name}: {where}"
           if boxes else f"No visible difference: the two are the same to within the threshold ({pct}% changed).")
    return ToolResult(True, msg, {"path": str(out), "regions": [list(x) for x in boxes],
                                  "changed_percent": pct, **info}, verified=ok)


def register_image_tools(reg: ToolRegistry) -> None:
    F, W = Capability.DOCUMENTS, RiskLevel.LOCAL_WRITE
    # Milestone 8's design tools go in their own capability rather than on top of
    # "documents", which was already at 1835 of its 2000-token budget: six more
    # there put it over, and that budget is what keeps a small brain able to see
    # its own tools. Nothing already measured moves - make_flyer, make_campaign,
    # edit_image and inspect_image stay exactly where the benchmark found them.
    D = Capability.DESIGN
    reg.register(ToolSpec("make_flyer",
                          "Design a promotional flyer (headline, points, contact, pictures) and save it. Uses Photoshop if installed, "
                          "otherwise Claw's built-in editor, and says which.", F, W, FlyerArgs, make_flyer, precheck=check_flyer))
    reg.register(ToolSpec("make_campaign", "One design in several sizes at once (post, story, banner, cover, print), "
                          "each saved and checked; Photoshop if installed.", F, W, CampaignArgs, make_campaign, precheck=check_flyer))
    reg.register(ToolSpec("edit_image", "Crop, rotate, resize, brighten, adjust contrast, make black-and-white or convert a picture; saves a new file.",
                          F, W, EditArgs, edit_image))
    reg.register(ToolSpec("inspect_image", "Check a picture's format and size.", F, RiskLevel.READ_ONLY, InspectArgs, inspect_image))
    # Milestone 8. Short descriptions on purpose: every tool in a capability is
    # carried in the prompt of any task that uses it, so each new one is paid
    # for by every image task.
    reg.register(ToolSpec("make_poster", "A film/event poster, a 1280x720 video thumbnail or a magazine cover, from pictures and a title.", D, W, PosterArgs, make_poster, precheck=check_poster))
    reg.register(ToolSpec("make_collage", "Several pictures in one sheet, each levelled so the set matches.",
                          D, W, CollageArgs, make_collage))
    reg.register(ToolSpec("brighten_photo", "Rescue an underexposed photograph; reports the brightness before and after.",
                          D, W, BrightenArgs, brighten_photo))
    reg.register(ToolSpec("passport_photo", "Crop a portrait to a passport size (UK/EU 35x45mm, US 51x51mm) at print resolution.",
                          D, W, PassportArgs, passport_photo))
    reg.register(ToolSpec("product_shadow", "Put a product on a plain background with a soft shadow under it.",
                          D, W, ShadowArgs, product_shadow))
    reg.register(ToolSpec("compare_designs", "Show what changed between two versions of a design, as marked regions.",
                          D, W, CompareArgs, compare_designs))
