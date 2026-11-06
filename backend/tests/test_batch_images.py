"""A whole folder of photographs, and QR codes.

edit_image already does one picture. The job people actually have is two
hundred of them off a phone, each four or five megabytes, that will not go
through WhatsApp or e-mail.

What these tests hold the tools to:
  - the originals are untouched, every time;
  - the saving is measured from the files on disk, not estimated;
  - a photograph smaller than the target is left alone rather than blown up;
  - one unreadable file does not stop the batch;
  - a QR code is read back, and when it cannot be read back the tool says so
    instead of counting it as a pass.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from PIL import Image

from claw.tools.base import ToolError
from tests.test_phase_a import call


def folder(ctx, name="Photos"):
    d = Path(ctx.settings.permissions.authorized_folders[0]) / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def photo(path: Path, w: int, h: int, colour=(120, 90, 60)) -> None:
    """A real photograph-ish image: noise, so JPEG cannot cheat on it."""
    import random
    rng = random.Random(len(path.name))
    img = Image.new("RGB", (w, h), colour)
    px = img.load()
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            px[x, y] = (rng.randrange(256), rng.randrange(256), rng.randrange(256))
    img.save(path, "JPEG", quality=95)


def digests(d: Path) -> dict:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in d.iterdir() if p.is_file()}


# ---------- resizing ----------
async def test_a_folder_of_photos_comes_out_smaller(tool_ctx):
    d = folder(tool_ctx)
    for i in range(4):
        photo(d / f"IMG_{i}.jpg", 3000, 2000)
    before = digests(d)

    r = await call(tool_ctx, "resize_photos", folder="Photos", size="whatsapp")
    assert r.ok and r.verified and r.data["count"] == 4
    assert r.data["bytes_after"] < r.data["bytes_before"], "nothing was saved"

    out = Path(r.data["folder"])
    for p in out.iterdir():
        with Image.open(p) as img:
            assert max(img.size) == 1600, f"{p.name} is {img.size}"
    assert digests(d) == before, "the originals were changed"


async def test_a_photo_already_small_is_not_blown_up(tool_ctx):
    """Asking for 1600 when the photo is 800 wide must not make it blurry."""
    d = folder(tool_ctx)
    photo(d / "small.jpg", 800, 600)
    r = await call(tool_ctx, "resize_photos", folder="Photos", size="whatsapp")
    with Image.open(next(Path(r.data["folder"]).iterdir())) as img:
        assert img.size == (800, 600), f"it was scaled up to {img.size}"


async def test_a_size_can_be_given_as_a_number_or_a_word(tool_ctx):
    d = folder(tool_ctx)
    photo(d / "a.jpg", 2400, 1800)
    r = await call(tool_ctx, "resize_photos", folder="Photos", size="900")
    with Image.open(next(Path(r.data["folder"]).iterdir())) as img:
        assert max(img.size) == 900
    with pytest.raises(Exception, match="(?i)size is one of|pixels"):
        await call(tool_ctx, "resize_photos", folder="Photos", size="quite small please")


async def test_one_unreadable_file_does_not_stop_the_batch(tool_ctx):
    d = folder(tool_ctx)
    photo(d / "good1.jpg", 1800, 1200)
    photo(d / "good2.jpg", 1800, 1200)
    (d / "broken.jpg").write_bytes(b"not actually a jpeg")
    r = await call(tool_ctx, "resize_photos", folder="Photos", size="small")
    assert r.data["count"] == 2
    assert "broken.jpg" in r.data["skipped"]
    assert "could not be read" in r.summary


async def test_transparency_lands_on_white_not_black(tool_ctx):
    """A PNG logo turned into a JPEG: the see-through part must go white."""
    d = folder(tool_ctx)
    img = Image.new("RGBA", (1200, 900), (0, 0, 0, 0))
    img.save(d / "logo.png")
    r = await call(tool_ctx, "resize_photos", folder="Photos", size="small")
    with Image.open(next(Path(r.data["folder"]).iterdir())) as out:
        assert out.convert("RGB").getpixel((10, 10)) == (255, 255, 255)


async def test_an_empty_folder_says_so(tool_ctx):
    folder(tool_ctx, "Empty")
    with pytest.raises(ToolError, match="no pictures"):
        await call(tool_ctx, "resize_photos", folder="Empty", size="small")


# ---------- watermarking ----------
async def test_the_name_goes_on_every_picture(tool_ctx):
    d = folder(tool_ctx)
    for i in range(3):
        photo(d / f"p{i}.jpg", 1200, 900, colour=(200, 200, 200))
    before = digests(d)

    r = await call(tool_ctx, "watermark_photos", folder="Photos",
                   text="Ade Stationery", position="bottom right")
    assert r.ok and r.verified and r.data["count"] == 3
    assert digests(d) == before, "the originals were changed"

    # NOT by comparing with the original: the marked copy is re-encoded as
    # JPEG, so nearly every pixel differs by a little and a difference test
    # passes on compression noise alone. It did, in the first version of this
    # test, which is why it is written this way instead - look for the white
    # letters themselves.
    assert _white_pixels(Path(r.data["folder"]) / "p0.jpg"), "no white text anywhere"


def _white_pixels(path: Path, threshold: int = 190) -> list[tuple[int, int]]:
    img = Image.open(path).convert("L")
    px = img.load()
    return [(x, y) for y in range(img.height) for x in range(img.width) if px[x, y] > threshold]


async def test_the_name_lands_in_the_corner_asked_for_and_inside_the_edge(tool_ctx):
    """Flat grey, so white letters are unmistakable and JPEG noise is not.

    The margin matters: right-aligning with the text WIDTH rather than the
    right edge of Pillow's bounding box put the name hard against the side
    of the picture, which looks like a mistake on a product photograph.
    """
    d = folder(tool_ctx, "Flat")
    Image.new("RGB", (2000, 1400), (128, 128, 128)).save(d / "a.jpg", "JPEG", quality=95)

    r = await call(tool_ctx, "watermark_photos", folder="Flat",
                   text="Ade Stationery", position="bottom right")
    out = Path(r.data["folder"]) / "a.jpg"
    white = _white_pixels(out)
    assert len(white) > 500, f"only {len(white)} light pixels; the name is not there"

    xs, ys = [p[0] for p in white], [p[1] for p in white]
    assert 2000 - max(xs) > 10, "the name is touching the right edge"
    assert 1400 - max(ys) > 10, "the name is touching the bottom edge"
    assert min(xs) > 1000 and min(ys) > 700, "the name is not in the bottom-right quarter"


async def test_the_corner_can_be_chosen(tool_ctx):
    d = folder(tool_ctx, "Flat2")
    Image.new("RGB", (1600, 1200), (128, 128, 128)).save(d / "a.jpg", "JPEG", quality=95)
    r = await call(tool_ctx, "watermark_photos", folder="Flat2", text="Shop", position="top left")
    white = _white_pixels(Path(r.data["folder"]) / "a.jpg")
    assert white, "nothing was drawn"
    assert max(x for x, _ in white) < 800 and max(y for _, y in white) < 600, \
        "asked for top left and it went somewhere else"


async def test_an_unknown_position_is_refused(tool_ctx):
    d = folder(tool_ctx)
    photo(d / "p.jpg", 800, 600)
    with pytest.raises(ToolError, match="Position is one of"):
        await call(tool_ctx, "watermark_photos", folder="Photos", text="X", position="diagonally")


# ---------- QR codes ----------
async def test_a_qr_code_is_read_back_from_the_saved_picture(tool_ctx):
    folder(tool_ctx, "QR")
    r = await call(tool_ctx, "make_qr_code", content="https://example.com/pay/12345",
                   folder="QR", file_name="pay")
    out = Path(r.data["path"])
    assert out.is_file() and out.suffix == ".png"
    with Image.open(out) as img:
        assert min(img.size) >= 200

    # zxing-cpp is a dependency now, so the check must actually run. The
    # fallback below is kept because the tool must still behave honestly if
    # the reader is ever missing - but it is not the path we ship.
    import importlib.util
    if importlib.util.find_spec("zxingcpp") is not None:
        assert r.data["checked"], "the QR code was not read back although a reader is installed"
        assert r.verified and "matches" in r.summary
    else:
        assert "could not read it back" in r.summary
        assert "scan it once" in r.summary


async def test_a_qr_code_really_carries_what_was_asked_for(tool_ctx):
    """Decoded from the saved PNG, not from the string that went in."""
    import importlib.util
    if importlib.util.find_spec("zxingcpp") is None:
        pytest.skip("no QR reader installed")
    import zxingcpp

    folder(tool_ctx, "QR")
    wanted = "https://example.com/pay/ade-stationery?amount=9500"
    r = await call(tool_ctx, "make_qr_code", content=wanted, folder="QR")
    found = zxingcpp.read_barcode(Image.open(r.data["path"]))
    assert found is not None, "the saved picture holds no readable code"
    assert found.text == wanted


async def test_a_label_is_printed_under_the_code(tool_ctx):
    folder(tool_ctx, "QR")
    plain = await call(tool_ctx, "make_qr_code", content="tel:+2348030000000", folder="QR")
    titled = await call(tool_ctx, "make_qr_code", content="tel:+2348030000000",
                        folder="QR", label="Call Ade Stationery")
    with Image.open(plain.data["path"]) as a, Image.open(titled.data["path"]) as b:
        assert b.height > a.height, "the label added no space"
        assert b.width == a.width


async def test_a_long_link_still_makes_a_code(tool_ctx):
    folder(tool_ctx, "QR")
    link = "https://example.com/catalogue?" + "&".join(f"item{i}={i}" for i in range(40))
    r = await call(tool_ctx, "make_qr_code", content=link, folder="QR")
    assert Path(r.data["path"]).is_file()
