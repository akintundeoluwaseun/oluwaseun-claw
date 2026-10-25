"""Generate Oluwaseun Claw icons (app icon + tray states). Run: python make_icons.py <out_dir>"""
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw

INK = (20, 33, 43, 255)
JADE = (60, 194, 170, 255)
AMBER = (232, 160, 54, 255)
WHITE = (255, 255, 255, 255)


def stroke(draw, pts, width, color):
    draw.line(pts, fill=color, width=width, joint="curve")
    r = width / 2
    for x, y in (pts[0], pts[-1]):
        draw.ellipse((x - r, y - r, x + r, y + r), fill=color)


def claw_marks(draw, box, color, weight):
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    for i, off in enumerate((-0.26, 0.0, 0.26)):
        pts = []
        for t in [k / 20 for k in range(21)]:
            # gentle curve from upper-right to lower-left
            x = x0 + w * (0.5 + off + 0.2 - 0.4 * t) + w * 0.06 * math.sin(t * math.pi)
            y = y0 + h * (0.12 + 0.76 * t) + (h * 0.05 if i == 1 else 0)
            pts.append((x, y))
        stroke(draw, pts, max(1, int(w * weight * (1.0 if i == 1 else 0.82))), color)


def app_icon(size):
    s = size * 4
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, s - 1, s - 1), radius=int(s * 0.23), fill=INK)
    claw_marks(d, (s * 0.2, s * 0.18, s * 0.8, s * 0.84), JADE, 0.12)
    return img.resize((size, size), Image.LANCZOS)


def tray_icon(size, dot=None):
    s = size * 4
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, s - 1, s - 1), radius=int(s * 0.26), fill=INK)
    claw_marks(d, (s * 0.12, s * 0.1, s * 0.88, s * 0.9), JADE, 0.15)
    if dot:
        r = s * 0.2
        cx, cy = s - r * 1.05, s - r * 1.05
        d.ellipse((cx - r - s * 0.05, cy - r - s * 0.05, cx + r + s * 0.05, cy + r + s * 0.05), fill=INK)
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=dot)
    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    big = app_icon(256)
    big.save(out / "icon.png")
    big.save(out / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    for name, dot in (("tray-idle", None), ("tray-busy", WHITE), ("tray-attention", AMBER)):
        tray_icon(16, dot).save(out / f"{name}.png")
        tray_icon(32, dot).save(out / f"{name}@2x.png")
    print("icons written to", out)
