"""Milestone 8: Blender renders. Runs with a REAL Blender when one is available (CLAW_TEST_BPY = a Python with
Blender's bpy module, or Blender on PATH); otherwise only the refusal is tested."""

import os
import stat
from pathlib import Path

import pytest

from claw.integrations import blender as bl
from claw.tools.base import ToolError
from tests.test_phase_a import call

BPY = os.environ.get("CLAW_TEST_BPY", "")   # a Python with Blender's bpy module (pip install bpy); the real run takes minutes
HAVE = bool(BPY) and Path(BPY).is_file()


@pytest.fixture
def blender(tmp_path, monkeypatch):
    if not HAVE:
        pytest.skip("no Blender (bpy) in this environment")
    wrapper = tmp_path / "blender"
    wrapper.write_text(f'#!/bin/sh\nfor a; do last="$a"; done\nexec "{BPY}" -c "exec(open(\'$last\').read())"\n')
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("CLAW_BLENDER", str(wrapper))


async def test_without_blender_it_says_so(tool_ctx, monkeypatch):
    monkeypatch.delenv("CLAW_BLENDER", raising=False)
    monkeypatch.setattr(bl.shutil, "which", lambda n: None)
    with pytest.raises(ToolError, match="need Blender, which is not installed"):
        await call(tool_ctx, "make_3d_render", kind="text", label="X")


def test_user_text_stays_inside_the_data():
    evil = 'Hi"); import os; os.remove("x'
    s = bl.script_for({"label": evil})
    assert "import os; os.remove" not in s.replace(repr(evil)[1:-1], "").split("json.loads(")[0]
    compile(s, "scene.py", "exec")


@pytest.mark.skipif(not HAVE, reason="no Blender here")
async def test_real_blender_turntable_and_text(tool_ctx, blender):
    r = await call(tool_ctx, "make_3d_render", kind="turntable", label="TechDesk", colour="orange", seconds=1)
    assert r.verified and r.data["frames"] == 24 and (r.data["width"], r.data["height"]) == (960, 540), r.summary
    r = await call(tool_ctx, "make_3d_render", kind="text", label="S-CLAW", colour="blue")
    assert r.verified and r.summary.startswith("Rendered S-CLAW text.png")
