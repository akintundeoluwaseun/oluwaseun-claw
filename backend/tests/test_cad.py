"""A dimensioned part, made in real CAD and measured afterwards (section 12).

Most of section 12 is MATLAB, Simulink, Minitab, AnyLogic and Microsoft
Project: paid software this cannot run. OpenSCAD is free, scriptable and
headless, so it is the one CAD package that can be driven AND proved on any
machine - including the Linux container these tests run in.

The point is the measurement. Every assertion below reads the size back out of
the exported STL rather than trusting the script that produced it, so a part
that comes out the wrong size fails instead of being reported as made.
"""

from pathlib import Path

import pytest

from claw.integrations import openscad as scad
from claw.tools.base import ToolError
from claw.tools.cad_tools import PartArgs, script_for
from tests.test_phase_a import call

HAVE = bool(scad.binary())
needs_openscad = pytest.mark.skipif(not HAVE, reason="OpenSCAD is not installed here")


# ---------- the script is built from numbers ----------
def test_the_script_contains_no_text_from_the_request():
    # file_name is the only free text, and it never reaches the script.
    src = script_for(PartArgs(shape="plate", width=60, depth=40, height=8,
                              file_name='evil"); system("rm -rf /"); //'))
    assert "system(" not in src and "rm -rf" not in src
    assert "cube([60.0, 40.0, 8.0]);" in src


def test_a_hole_that_cannot_fit_is_refused_with_the_numbers():
    with pytest.raises(ToolError) as exc:
        script_for(PartArgs(shape="plate", width=20, depth=20, height=5,
                            hole_diameter=10, hole_inset=8))
    assert "does not fit" in str(exc.value) and "20" in str(exc.value)


def test_a_shape_claw_cannot_make_is_refused_by_name():
    with pytest.raises(ValueError) as exc:
        PartArgs(shape="gearbox")
    assert "plate" in str(exc.value)


# ---------- measured from the STL ----------
@needs_openscad
async def test_a_plate_comes_out_the_size_that_was_asked_for(tool_ctx):
    r = await call(tool_ctx, "make_part", shape="plate", width=60, depth=40, height=8)
    assert r.ok and r.verified, r.summary
    assert r.data["measured_mm"] == [60.0, 40.0, 8.0]
    assert Path(r.data["path"]).stat().st_size > 0


@needs_openscad
async def test_bolt_holes_do_not_change_the_outside_dimensions(tool_ctx):
    plain = await call(tool_ctx, "make_part", shape="plate", width=60, depth=40, height=8)
    holed = await call(tool_ctx, "make_part", shape="plate", width=60, depth=40, height=8,
                       hole_diameter=6, hole_inset=10)
    assert holed.verified
    assert holed.data["measured_mm"] == plain.data["measured_mm"] == [60.0, 40.0, 8.0]
    # the holes are really there: a drilled plate uses less material, so fewer
    # bytes is not a safe check - the script is, and it is returned to the person
    assert "cylinder" in holed.untrusted_text and "difference()" in holed.untrusted_text


@needs_openscad
async def test_a_cylinder_is_round_to_its_diameter(tool_ctx):
    r = await call(tool_ctx, "make_part", shape="cylinder", diameter=25, height=12)
    assert r.verified, r.summary
    x, y, z = r.data["measured_mm"]
    assert abs(x - 25) <= 0.05 and abs(y - 25) <= 0.05 and z == 12.0


@needs_openscad
async def test_a_tube_is_hollow_but_the_same_size_outside(tool_ctx):
    solid = await call(tool_ctx, "make_part", shape="cylinder", diameter=30, height=10)
    tube = await call(tool_ctx, "make_part", shape="tube", diameter=30, bore=18, height=10)
    assert tube.verified
    assert tube.data["measured_mm"] == solid.data["measured_mm"]
    assert "difference()" in tube.untrusted_text


@needs_openscad
async def test_a_bracket_stands_up(tool_ctx):
    r = await call(tool_ctx, "make_part", shape="bracket", width=50, depth=30, height=5)
    assert r.verified, r.summary
    # the upstand makes it as tall as its shorter footprint edge
    assert r.data["measured_mm"][2] == 30.0


@needs_openscad
async def test_nothing_is_overwritten(tool_ctx):
    for _ in range(2):
        await call(tool_ctx, "make_part", shape="plate", width=20, depth=20, height=3)
    folder = Path(tool_ctx.settings.permissions.authorized_folders[0])
    assert len(list(folder.glob("plate*.stl"))) == 2


@needs_openscad
async def test_the_measurement_is_of_the_file_not_of_the_request(tool_ctx):
    """The property that makes the rest of these worth anything."""
    r = await call(tool_ctx, "make_part", shape="plate", width=33, depth=17, height=4)
    measured = scad.bounding_box(Path(r.data["path"]))
    assert list(measured) == r.data["measured_mm"] == [33.0, 17.0, 4.0]


async def test_without_openscad_it_says_so(tool_ctx, monkeypatch):
    monkeypatch.setattr(scad, "binary", lambda: None)
    monkeypatch.delenv("CLAW_OPENSCAD", raising=False)
    with pytest.raises(ToolError, match="needs OpenSCAD, which is not installed"):
        await call(tool_ctx, "make_part", shape="plate")
