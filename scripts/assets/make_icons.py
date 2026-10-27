"""Build S-CLAW's Windows icons from the brand SVGs.

    backend/.venv/bin/python scripts/assets/make_icons.py [out_dir]

The icons are *rendered from the real mark* rather than redrawn by hand, so the
taskbar, the tray and the installer cannot drift away from what the brand files
say. The full mark is used at 32 px and above; below that its folded facets turn
to mud, so the simplified mark is used instead - which is why that file exists.

Rendering is done by the Chromium that is already here for the browser tools: no
extra dependency, and it is the same renderer the app itself draws the mark with.
The tray icons are flat single-colour silhouettes, because Windows draws the tray
small and monochrome-ish and a gradient there reads as a smudge.
"""

from __future__ import annotations

import asyncio
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BRAND = ROOT / "desktop" / "src" / "assets" / "brand"
DEFAULT_OUT = ROOT / "desktop" / "src" / "assets"

#: Windows asks for all of these inside one .ico.
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]
#: Below this the full mark is unreadable, so the simplified one is used.
SIMPLIFY_BELOW = 32

TRAY = {
    "tray-idle": "#C9D4E6",      # resting: quiet, light enough for a dark taskbar
    "tray-busy": "#7E9BFF",      # working
    "tray-attention": "#E3B36A",  # waiting for the person
}


def chromium() -> str | None:
    for c in ("/opt/pw-browsers/chromium-1243/chrome-linux64/chrome",
              shutil.which("chromium"), shutil.which("google-chrome")):
        if c and Path(c).exists():
            return c
    return None


async def render(jobs: list[tuple[Path, int, Path]]) -> None:
    """Draw each (svg, size, destination) to a transparent PNG."""
    from playwright.async_api import async_playwright

    exe = chromium()
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=exe) if exe else await p.chromium.launch()
        page = await browser.new_page()
        for svg, size, dest in jobs:
            html = (f'<!doctype html><meta charset="utf-8">'
                    f'<style>html,body{{margin:0;background:transparent}}'
                    f'svg{{display:block;width:{size}px;height:{size}px}}</style>'
                    f'{svg.read_text(encoding="utf-8")}')
            tmp = Path(tempfile.mkdtemp()) / "icon.html"
            tmp.write_text(html, encoding="utf-8")
            await page.set_viewport_size({"width": size, "height": size})
            await page.goto(tmp.as_uri())
            await page.wait_for_timeout(60)
            dest.parent.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(dest), omit_background=True)
            shutil.rmtree(tmp.parent, ignore_errors=True)
        await browser.close()


def tray_svg(colour: str) -> str:
    mark = (BRAND / "s-claw-mark-mono.svg").read_text(encoding="utf-8")
    return mark.replace("currentColor", colour)


def main(out_dir: Path) -> int:
    full, small = BRAND / "s-claw-mark.svg", BRAND / "s-claw-mark-small.svg"
    for f in (full, small, BRAND / "s-claw-mark-mono.svg"):
        if not f.is_file():
            print(f"missing brand file: {f}", file=sys.stderr)
            return 1

    work = Path(tempfile.mkdtemp(prefix="claw-icons-"))
    jobs: list[tuple[Path, int, Path]] = []
    layers = {}
    for size in ICO_SIZES:
        png = work / f"icon-{size}.png"
        layers[size] = png
        jobs.append((small if size < SIMPLIFY_BELOW else full, size, png))

    tray_files = {}
    for name, colour in TRAY.items():
        svg = work / f"{name}.svg"
        svg.write_text(tray_svg(colour), encoding="utf-8")
        for scale, suffix in ((16, ""), (32, "@2x")):
            dest = out_dir / f"{name}{suffix}.png"
            tray_files[dest] = (svg, scale)
            jobs.append((svg, scale, dest))

    asyncio.run(render(jobs))

    from PIL import Image

    images = [Image.open(layers[s]).convert("RGBA") for s in ICO_SIZES]
    images[-1].save(out_dir / "icon.ico", format="ICO",
                    sizes=[(s, s) for s in ICO_SIZES], append_images=images[:-1])
    images[-1].save(out_dir / "icon.png", format="PNG")
    shutil.rmtree(work, ignore_errors=True)

    print(f"icon.ico  {', '.join(str(s) for s in ICO_SIZES)} px")
    print(f"icon.png  {ICO_SIZES[-1]} px")
    for dest in tray_files:
        print(f"{dest.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT))
