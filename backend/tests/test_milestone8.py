"""Milestone 8: one design in many sizes (campaign), a logo reveal, and a see-through lower third.

All made by Claw's built-in makers and reopened here. Photoshop and After Effects are NOT run
(neither is in the build workspace or on GitHub's machines)."""

from pathlib import Path

import pytest

from claw.integrations import images as im
from claw.integrations import motion as mo
from claw.tools.base import ToolError
from claw.tools.image_tools import CampaignArgs
from tests.test_phase_a import call


async def test_campaign_makes_every_size_in_its_own_folder(tool_ctx):
    folder = Path(tool_ctx.settings.permissions.authorized_folders[0])
    r = await call(tool_ctx, "make_campaign", title="Weekend Jollof Special", subtitle="Order before Friday",
                   points=["Free delivery in Ikeja"], contact="WhatsApp 0803 000 0000",
                   sizes=["square", "story", "banner", "cover"], file_name="jollof", folder=str(folder), editor="builtin")
    assert r.ok, r.summary
    out = folder / "jollof"
    files = sorted(p.name for p in out.iterdir())
    assert files == ["jollof banner 1500x500.png", "jollof cover 1640x624.png",
                     "jollof square 1080x1080.png", "jollof story 1080x1920.png"]
    for f in r.data["files"]:
        assert im.inspect(Path(f["path"]))[("width")] == f["width"]
        if f["headline_seen"] is not None:
            assert f["headline_seen"] >= 0.6
    assert "built-in image editor" in r.summary


def test_campaign_sizes_understand_everyday_words():
    a = CampaignArgs(title="Sale", sizes="instagram post, instagram story, facebook cover, twitter header, poster")
    assert a.sizes == ["square", "story", "cover", "banner", "a4"]


async def test_campaign_never_overwrites_an_existing_folder(tool_ctx):
    folder = Path(tool_ctx.settings.permissions.authorized_folders[0])
    (folder / "campaign").mkdir()
    (folder / "campaign" / "keep.txt").write_text("mine")
    r = await call(tool_ctx, "make_campaign", title="Sale today", sizes=["square"], folder=str(folder), editor="builtin")
    assert r.ok and (folder / "campaign (2)").is_dir() and (folder / "campaign" / "keep.txt").read_text() == "mine"


def test_wide_banner_keeps_the_contact_inside_the_picture():
    spec = im.FlyerSpec("Weekend Jollof Special", contact="WhatsApp 0803 000 0000", size=im.PRESETS["banner"])
    img = im.render_flyer(spec)
    bottom = img.crop((0, img.height - 4, img.width, img.height)).getcolors(1 << 16)
    assert img.size == (1500, 500) and bottom  # the contact band reaches the bottom edge


def test_logo_shows_the_whole_name_never_cut():
    spec = mo.MotionSpec("Mama Tee's Kitchen", "Fresh food, fast", size=mo.SIZES["square"], seconds=5, style="logo")
    assert spec.title_moment() == pytest.approx(2.75)
    frame = mo.render_frame(spec, 2.75)
    assert frame.size == (1080, 1080) and frame.mode == "RGB"


async def test_logo_reveal_video(tool_ctx):
    folder = Path(tool_ctx.settings.permissions.authorized_folders[0])
    r = await call(tool_ctx, "make_motion_video", title="TechDesk", subtitle="Repairs, sorted", style="logo",
                   seconds=4, size="square", folder=str(folder), file_name="logo", editor="builtin")
    assert r.ok and (folder / "logo.mp4").is_file(), r.summary
    assert r.data["frames"] == 120
    if r.data["headline_seen"] is not None:
        assert r.data["headline_seen"] >= 0.6 and r.verified


async def test_lower_third_is_see_through_mov(tool_ctx):
    folder = Path(tool_ctx.settings.permissions.authorized_folders[0])
    r = await call(tool_ctx, "make_motion_video", title="Adaeze Okafor", subtitle="Head of Sales", style="lower_third",
                   seconds=4, folder=str(folder), file_name="name bar", editor="builtin")
    assert r.ok and (folder / "name bar.mov").is_file(), r.summary
    assert r.data["alpha"] is True and "see-through" in r.summary
    first = mo.lower_third_frame(mo.MotionSpec("A", size=(640, 360), seconds=4, style="lower_third", transparent=True), 2)
    assert first.getpixel((320, 20))[3] == 0  # the top of the picture is empty, so the video shows through


async def test_after_effects_template_is_not_claimed_for_logo(tool_ctx):
    with pytest.raises(ToolError, match="built-in maker"):
        await call(tool_ctx, "make_motion_video", title="X", style="logo", editor="aftereffects")


def test_requests_reach_the_right_tool():
    from claw.agent.executor import fitting_tools
    from claw.tools.registry import build_registry
    reg = build_registry()
    assert fitting_tools("Animate our logo", reg) == ["make_motion_video"]
    assert fitting_tools("Make a lower third for Adaeze, Head of Sales", reg) == ["make_motion_video"]
    assert "make_campaign" in fitting_tools("Make our sale poster in all the social media sizes", reg)
