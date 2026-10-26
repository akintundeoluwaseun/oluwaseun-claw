"""Synthetic test PDFs, generated at test time (no third-party documents).

Text is drawn with Pillow's own built-in font, then saved as image-only PDF
pages to imitate scans. Text-based pages come from tests.test_documents.make_pdf.
"""

from __future__ import annotations

import io
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from pypdf import PdfReader, PdfWriter


def page_image(lines: list[str], size=(1700, 2200), font_px=44, rotate=0.0, quality="clean", seed=1) -> Image.Image:
    img = Image.new("L", size, 255)
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=font_px)
    y = 180
    for line in lines:
        draw.text((150, y), line, fill=0, font=font)
        y += int(font_px * 1.8)
    if quality == "poor":
        # Blurred, very low-resolution, speckled: imitates a bad photocopy. OCR should flag it.
        rnd = random.Random(seed)
        px = img.load()
        for _ in range(size[0] * size[1] // 200):
            px[rnd.randrange(size[0]), rnd.randrange(size[1])] = rnd.choice((0, 255))
        img = img.filter(ImageFilter.GaussianBlur(2.6))
        img = img.resize((size[0] // 5, size[1] // 5)).resize(size)
    if rotate:
        img = img.rotate(rotate, expand=True, fillcolor=255)
    return img


def scanned_pdf(path: Path, pages: list[Image.Image]) -> Path:
    rgb = [p.convert("RGB") for p in pages]
    rgb[0].save(path, "PDF", resolution=200, save_all=True, append_images=rgb[1:])
    return path


def merge(path: Path, parts: list[Path]) -> Path:
    w = PdfWriter()
    for part in parts:
        for page in PdfReader(str(part)).pages:
            w.add_page(page)
    with open(path, "wb") as fh:
        w.write(fh)
    return path


def encrypt(src: Path, dst: Path, password: str) -> Path:
    w = PdfWriter(clone_from=str(src))
    w.encrypt(password)
    with open(dst, "wb") as fh:
        w.write(fh)
    return dst
