"""Phase D — image editing. Real: Pillow rendering, files, OCR read-back (Tesseract), permissions.
Photoshop is not installed here, so the Photoshop path is only checked for refusal and script safety (Test D in
Photoshop is BLOCKED — docs/WINDOWS_ACCEPTANCE.md)."""

import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from claw.integrations import images as im
from claw.tools.base import ToolError
from tests.test_desktop import call
from tests.test_ocr import needs_ocr


def make_photo(path: Path, color=(200, 80, 40), size=(1200, 800)) -> Path:
    img = Image.new("RGB", size, color)
    d = ImageDraw.Draw(img)
    for i in range(0, size[0], 60):  # deterministic stripes so cropping/resizing is visible
        d.rectangle([i, 0, i + 30, size[1]], fill=(color[0] // 2, color[1], 255 - color[2]))
    img.save(path)
    return path


@pytest.fixture
def folder(tool_ctx):
    return Path(tool_ctx.settings.permissions.authorized_folders[0])


@needs_ocr
async def test_d_flyer_builtin_verified(tool_ctx, folder):
    photo = make_photo(folder / "shop.jpg")
    r = await call(tool_ctx, "make_flyer", title="TechDesk Shop Manager", subtitle="Run your repair shop from one app",
                   points=["Sales and receipts", "Repair tickets", "Works offline"], contact="WhatsApp 0807 000 0000",
                   size="square", images=[str(photo)], file_name="techdesk flyer")
    assert r.ok and r.verified, r.summary
    assert "built-in image editor (Photoshop was not used)" in r.summary
    out = Path(r.data["path"])
    info = im.inspect(out)
    assert (info["format"], info["width"], info["height"]) == ("PNG", 1080, 1080)
    assert r.data["headline_seen"] >= 0.6
    with Image.open(out) as img:  # the photo is really on the flyer: the hero area is not plain background
        hero = img.crop((100, 100, 900, 400)).convert("RGB")
        assert len(set(hero.getdata())) > 2
    again = await call(tool_ctx, "make_flyer", title="TechDesk Shop Manager", size="square", file_name="techdesk flyer")
    assert again.data["path"] != str(out)  # never overwrites


async def test_flyer_formats_and_sizes(tool_ctx, folder):
    for size, fmt in (("a5", "jpg"), ("story", "pdf")):
        r = await call(tool_ctx, "make_flyer", title="Ado Ekiti Phone Repairs", size=size, format=fmt, file_name=f"f-{size}")
        assert r.ok and Path(r.data["path"]).suffix == f".{fmt}"
        if fmt == "jpg":
            assert (r.data["width"], r.data["height"]) == im.PRESETS["a5"]
        else:
            assert Path(r.data["path"]).read_bytes()[:5] == b"%PDF-"


async def test_photoshop_is_never_faked(tool_ctx):
    with pytest.raises(ToolError, match="Photoshop automation works on Windows only|not installed"):
        await call(tool_ctx, "make_flyer", title="Promo", editor="photoshop")
    with pytest.raises(ToolError, match="PSD"):
        await call(tool_ctx, "make_flyer", title="Promo", format="psd", editor="builtin")
    with pytest.raises(ToolError, match="PSD files can only be made with Photoshop"):
        await call(tool_ctx, "make_flyer", title="Promo", format="psd")


def test_photoshop_script_keeps_user_text_inside_data():
    spec = im.FlyerSpec('Sale"; app.system("del C:\\\\*"); "', points=["a\nb"], images=[])
    script = im.photoshop_script(spec, Path("C:/out/flyer.png"))
    first = script.strip().splitlines()[0]
    assert first.startswith("var d = ") and first.endswith(";")
    data = json.loads(first[len("var d = "):-1])
    assert data["title"] == spec.title  # the hostile text is only a JSON string value
    assert "app.system" not in script.replace(first, "")


async def test_edit_image_operations(tool_ctx, folder):
    src = make_photo(folder / "photo.png")
    r = await call(tool_ctx, "edit_image", path=str(src), crop=[0, 0, 600, 400], rotate=90, resize_width=200, format="jpg")
    assert r.verified and (r.data["width"], r.data["height"], r.data["format"]) == (200, 300, "JPEG")
    assert im.inspect(src)["width"] == 1200  # original unchanged
    g = await call(tool_ctx, "edit_image", path=str(src), grayscale=True, brightness=1.3)
    with Image.open(g.data["path"]) as img:
        assert img.size == (1200, 800)
    with pytest.raises(ToolError, match="outside the picture"):
        await call(tool_ctx, "edit_image", path=str(src), crop=[0, 0, 5000, 10])
    with pytest.raises(ToolError, match="No change"):
        await call(tool_ctx, "edit_image", path=str(src))
    (folder / "broken.png").write_bytes(b"not an image")
    with pytest.raises(ToolError, match="damaged"):
        await call(tool_ctx, "inspect_image", path=str(folder / "broken.png"))
    with pytest.raises(ToolError):
        await call(tool_ctx, "inspect_image", path="/etc/hostname")
    i = await call(tool_ctx, "inspect_image", path=str(src))
    assert i.data["width"] == 1200 and i.data["format"] == "PNG"
