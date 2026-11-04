"""Milestone 8: the design jobs that do not need Photoshop.

Section 1 of the challenge list is mostly Photoshop. Part of it genuinely needs
a paid app or a far bigger brain - cutting a person out of a crowd, rebuilding
the background behind them - and stays OUT. What is left is layout and
measurable pixel work, which Pillow does on any machine.

Every assertion here is a measurement of the file that was written: its real
size reopened from disk, the brightness actually achieved, the regions actually
found. A tool returning ToolResult(True, ...) proves nothing, which is the rule
the whole project runs on.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from claw.tools.base import ToolError
from tests.test_desktop import call
from tests.test_images import folder, make_photo  # noqa: F401 - fixtures


def _photos(folder: Path, n: int) -> list[str]:
    out = []
    for i in range(n):
        p = folder / f"shot{i}.png"
        make_photo(p, color=(40 + i * 35, 90, 160 - i * 20))
        out.append(p.name)
    return out


def _reopen(result) -> Image.Image:
    return Image.open(result.data["path"])


# ---------- 1.03 poster, 1.12 thumbnail, 1.14 magazine cover ----------

@pytest.mark.asyncio
@pytest.mark.parametrize(("style", "expected"), [
    ("poster", (2480, 3508)),       # A4 at 300 dpi
    ("thumbnail", (1280, 720)),     # what YouTube asks for
    ("magazine", (2480, 3508)),
])
async def test_a_poster_is_the_size_its_job_requires(tool_ctx, folder, style, expected):
    r = await call(tool_ctx, "make_poster", title="The Long Afternoon", style=style,
                   images=_photos(folder, 5), tagline="Some stories wait",
                   subtitle="This winter", credits="Directed by someone",
                   cover_lines=["One", "Two"], file_name=f"p-{style}")
    assert r.ok and r.verified
    assert _reopen(r).size == expected
    assert (r.data["width"], r.data["height"]) == expected


@pytest.mark.asyncio
async def test_a_poster_works_with_no_pictures_at_all(tool_ctx, folder):
    """A brain that names no picture should still get a poster, not an error."""
    r = await call(tool_ctx, "make_poster", title="Quiet", images=[], file_name="bare")
    assert r.ok and _reopen(r).size == (2480, 3508)


@pytest.mark.asyncio
async def test_the_title_really_lands_on_the_poster(tool_ctx, folder):
    """Not OCR here: just that the title changed the pixels it was meant to.

    A layout bug that drew the title off-canvas would still save a file and
    still report a size, so compare the titled version with an untitled one.
    """
    plain = await call(tool_ctx, "make_poster", title="A", images=_photos(folder, 1), file_name="plain")
    titled = await call(tool_ctx, "make_poster", title="THE LONG AFTERNOON RETURNS",
                        images=_photos(folder, 1), file_name="titled")
    a, b = _reopen(plain).convert("L"), _reopen(titled).convert("L")
    from PIL import ImageChops, ImageStat
    assert ImageStat.Stat(ImageChops.difference(a, b)).mean[0] > 0.4, "the title changed almost nothing on the page"


# ---------- 1.15 collage with consistent lighting ----------

@pytest.mark.asyncio
async def test_a_collage_holds_every_picture_it_was_given(tool_ctx, folder):
    r = await call(tool_ctx, "make_collage", images=_photos(folder, 5), file_name="c5")
    assert r.ok and r.verified
    assert r.data["pictures"] == 5
    assert _reopen(r).size == (2480, 2480)


@pytest.mark.asyncio
async def test_levelling_brings_a_dim_picture_towards_the_others(tool_ctx, folder):
    """The "consistent lighting" half, measured rather than asserted."""
    from PIL import ImageStat
    bright = folder / "bright.png"
    make_photo(bright)
    dim = folder / "dim.png"
    Image.open(bright).point(lambda v: int(v * 0.35)).save(dim)

    evened = await call(tool_ctx, "make_collage", images=["bright.png", "dim.png"],
                        even_exposure=True, file_name="even")
    asis = await call(tool_ctx, "make_collage", images=["bright.png", "dim.png"],
                      even_exposure=False, file_name="asis")
    # The left half is the bright one, the right half the dim one.
    def halves(res):
        img = _reopen(res).convert("L")
        w, h = img.size
        return (ImageStat.Stat(img.crop((0, 0, w // 2, h))).mean[0],
                ImageStat.Stat(img.crop((w // 2, 0, w, h))).mean[0])

    gap_evened = abs(halves(evened)[0] - halves(evened)[1])
    gap_asis = abs(halves(asis)[0] - halves(asis)[1])
    assert gap_evened < gap_asis, f"levelling did not close the gap ({gap_evened} vs {gap_asis})"


# ---------- 1.17 improve an underexposed photograph ----------

@pytest.mark.asyncio
async def test_a_dark_photograph_is_measurably_brighter(tool_ctx, folder):
    dark = folder / "dark.png"
    make_photo(folder / "src.png")
    Image.open(folder / "src.png").point(lambda v: int(v * 0.25)).save(dark)

    r = await call(tool_ctx, "brighten_photo", path="dark.png")
    assert r.ok and r.verified
    assert r.data["brightness_after"] > r.data["brightness_before"]
    assert r.data["brightness_after"] > 70, "still too dark to call it rescued"
    assert str(r.data["brightness_before"]) in r.summary and str(r.data["brightness_after"]) in r.summary


@pytest.mark.asyncio
async def test_the_original_photograph_is_left_alone(tool_ctx, folder):
    dark = folder / "keep.png"
    make_photo(dark)
    before = dark.read_bytes()
    await call(tool_ctx, "brighten_photo", path="keep.png")
    assert dark.read_bytes() == before, "the input file was modified"


# ---------- 1.18 passport photograph ----------

@pytest.mark.asyncio
@pytest.mark.parametrize(("country", "px"), [("uk", (413, 531)), ("eu", (413, 531)), ("us", (602, 602))])
async def test_a_passport_photo_is_exactly_the_official_size(tool_ctx, folder, country, px):
    """35x45mm and 51x51mm at 300 dpi, to the pixel."""
    make_photo(folder / "face.png", size=(1600, 2000))
    r = await call(tool_ctx, "passport_photo", path="face.png", country=country, file_name=f"pp-{country}")
    assert r.ok and r.verified
    assert _reopen(r).size == px, f"{country} came out {_reopen(r).size}, wanted {px}"


@pytest.mark.asyncio
async def test_the_passport_tool_admits_it_cannot_see_the_face(tool_ctx, folder):
    """It gets the measurements right and says the rest is the person's to check."""
    make_photo(folder / "face2.png", size=(1600, 2000))
    r = await call(tool_ctx, "passport_photo", path="face2.png")
    assert "does not find the face" in r.summary


# ---------- 1.09 shadow beneath a product ----------

@pytest.mark.asyncio
async def test_a_cut_out_product_gets_a_shadow_under_it(tool_ctx, folder):
    from PIL import ImageStat
    p = folder / "product.png"
    img = Image.new("RGBA", (900, 900), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle([300, 180, 600, 700], radius=40, fill=(40, 110, 190, 255))
    img.save(p)

    r = await call(tool_ctx, "product_shadow", path="product.png")
    assert r.ok and r.verified and r.data["subject_found"] is True
    out = _reopen(r).convert("L")
    # Just under the product should be darker than the far corner, which is bare background.
    under = ImageStat.Stat(out.crop((380, 700, 520, 760))).mean[0]
    corner = ImageStat.Stat(out.crop((0, 0, 120, 120))).mean[0]
    assert under < corner - 8, f"no shadow under the product (under {under}, background {corner})"


@pytest.mark.asyncio
async def test_a_picture_with_no_separable_subject_says_so(tool_ctx, folder):
    """A flat photograph has no subject to lift. It must not invent one."""
    flat = folder / "flat.png"
    Image.new("RGB", (600, 600), (128, 128, 128)).save(flat)
    r = await call(tool_ctx, "product_shadow", path="flat.png")
    assert r.data["subject_found"] is False
    assert "no subject" in r.summary


# ---------- 1.25 compare two design versions ----------

@pytest.mark.asyncio
async def test_the_two_changes_are_found_and_nothing_else(tool_ctx, folder):
    base = folder / "v1.png"
    make_photo(base, size=(1200, 1600))
    changed = folder / "v2.png"
    img = Image.open(base).copy()
    d = ImageDraw.Draw(img)
    d.rectangle([120, 160, 420, 360], fill=(255, 40, 40))
    d.ellipse([700, 1000, 1050, 1350], fill=(20, 230, 150))
    img.save(changed)

    r = await call(tool_ctx, "compare_designs", before="v1.png", after="v2.png")
    assert r.ok and r.verified
    assert len(r.data["regions"]) == 2, f"found {len(r.data['regions'])} regions, expected 2"
    assert 2 < r.data["changed_percent"] < 40
    # each reported region must actually contain the change it claims
    xs = sorted(x0 for x0, _, _, _ in r.data["regions"])
    assert xs[0] < 300 and xs[1] > 600


@pytest.mark.asyncio
async def test_two_identical_designs_report_no_difference(tool_ctx, folder):
    make_photo(folder / "same1.png")
    make_photo(folder / "same2.png")
    r = await call(tool_ctx, "compare_designs", before="same1.png", after="same2.png")
    assert r.data["regions"] == []
    assert "No visible difference" in r.summary


@pytest.mark.asyncio
async def test_different_sizes_are_compared_not_refused(tool_ctx, folder):
    make_photo(folder / "big.png", size=(1200, 900))
    make_photo(folder / "small.png", size=(600, 450))
    r = await call(tool_ctx, "compare_designs", before="big.png", after="small.png")
    assert r.ok


# ---------- the rule that applies to all of them ----------

@pytest.mark.asyncio
async def test_none_of_them_will_write_outside_an_authorized_folder(tool_ctx, folder):
    make_photo(folder / "x.png")
    with pytest.raises((ToolError, Exception)):
        await call(tool_ctx, "make_collage", images=["x.png"], folder="C:\\Windows\\System32", file_name="nope")
