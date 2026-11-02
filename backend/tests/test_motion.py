"""Motion graphics: the built-in maker end to end (render, reopen, OCR), and the After Effects script it would run.

After Effects itself is NOT run here (none in the build workspace or on GitHub's machines)."""

import json
import re
from pathlib import Path

import pytest

from claw.agent.executor import fitting_tools
from claw.agent import skills
from claw.integrations import motion as mo
from claw.tools.registry import build_registry
from tests.test_phase_a import call


def test_scenes_cover_the_whole_video():
    spec = mo.MotionSpec("TechDesk", "Repair shop manager", ["Track repairs", "Print receipts", "Works offline"], "0807 000 0000", seconds=12)
    sc = spec.scenes()
    assert [s[0] for s in sc] == ["title", "point0", "point1", "point2", "contact"]
    assert sc[0][1] == 0 and abs(sc[-1][2] - 12) < 1e-9
    assert sc[0][1] < spec.title_moment() < sc[0][2]


async def test_builtin_video_is_made_reopened_and_checked(tool_ctx):
    folder = Path(tool_ctx.settings.permissions.authorized_folders[0])
    r = await call(tool_ctx, "make_motion_video", title="TechDesk", subtitle="Run your repair shop", seconds=5,
                   points=["Track repairs", "Print receipts"], contact="techdesk.ng", size="square", style="pop",
                   background="navy", accent="gold", folder=str(folder), editor="builtin")
    out = folder / "promo video.mp4"
    assert r.ok and out.is_file(), r.summary
    assert "built-in video maker" in r.summary and "1080×1080" in r.summary
    assert r.data["frames"] == 150 and abs(r.data["seconds"] - 5) <= 1
    if r.data["headline_seen"] is not None:   # OCR is installed here; on a computer without it this is skipped
        assert r.data["headline_seen"] >= 0.6 and r.verified


async def test_points_as_one_string_and_never_overwrites(tool_ctx):
    folder = Path(tool_ctx.settings.permissions.authorized_folders[0])
    (folder / "promo video.mp4").write_bytes(b"old")
    r = await call(tool_ctx, "make_motion_video", title="Sale", points="Big discounts, Free delivery", seconds=4,
                   folder=str(folder), editor="builtin")
    assert r.ok and (folder / "promo video (2).mp4").is_file() and (folder / "promo video.mp4").read_bytes() == b"old"


async def test_after_effects_is_refused_honestly_when_missing(tool_ctx):
    from claw.tools.base import ToolError
    with pytest.raises(ToolError, match="built-in maker instead"):
        await call(tool_ctx, "make_motion_video", title="X", editor="aftereffects")


def test_after_effects_script_keeps_user_text_inside_the_data(tmp_path):
    evil = 'Sale"; app.quit(); var x="'
    spec = mo.MotionSpec(evil, points=["a", "b"], contact="call 080", seconds=8)
    js = mo.after_effects_script(spec, tmp_path / "o.mp4", tmp_path / "o.aep", tmp_path / "done.txt")
    data = json.loads(re.search(r"var d = (\{.*?\});\n", js, re.S).group(1))
    assert data["title"] == evil and data["seconds"] == 8
    assert "app.quit()" not in js.replace(json.dumps(evil)[1:-1], "")
    for needed in ("addComp", "addText", "setTemporalEaseAtKey", "renderQueue", "project.save", "finish("):
        assert needed in js


def test_a_video_request_gets_the_video_tool_and_recipe():
    t = "Make a promotional video for my software TechDesk in After Effects and save it in Documents"
    assert fitting_tools(t, build_registry())[0] == "make_motion_video"
    assert skills.pick(t, skills.load(skills.BUILTIN)).name == "make-a-promo-video"
    flyer = "Make a promotional flyer for my software TechDesk and save it in Documents."
    assert fitting_tools(flyer, build_registry())[0] == "make_flyer"
    assert skills.pick(flyer, skills.load(skills.BUILTIN)).name == "make-a-flyer"
