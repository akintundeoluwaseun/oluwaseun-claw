"""Starting a long job and coming back to it.

run_command waits and gives up after five minutes, which is right for most
things and wrong for the ones people care about most: a Blender render, an
hour of footage converted, a long export. Killed at five minutes with "it
was still running" throws the work away and tells the person nothing.

The thing these tests are really protecting is that running in the
background is not a way round any of the gates on run_command. Same
allowlist, same refusal of shell punctuation, same authorised folder, same
approval.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from claw.agent.schemas import Capability
from claw.permissions.policy import RiskLevel
from claw.tools.background_tools import MAX_JOBS, jobs
from claw.tools.base import ToolError
from claw.tools.registry import build_registry
from tests.test_phase_a import call


@pytest.fixture(autouse=True)
def _no_jobs_left_behind():
    """Each test starts and ends with a clean slate."""
    jobs().clear()
    yield
    from claw.tools.background_tools import _end
    for job in list(jobs().values()):
        _end(job)
    jobs().clear()


def work_folder(ctx, name="Work"):
    d = Path(ctx.settings.permissions.authorized_folders[0]) / name
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------- the gates are the same ones ----------
def test_starting_asks_first_and_checking_does_not():
    reg = build_registry()
    assert reg.get("start_program").risk is RiskLevel.DESTRUCTIVE, "it would start without asking"
    assert reg.get("check_program").risk is RiskLevel.READ_ONLY
    assert reg.get("start_program").capability is Capability.CODE


async def test_a_program_off_the_allowlist_cannot_be_started_in_the_background(tool_ctx):
    """The obvious way round the allowlist, closed."""
    work_folder(tool_ctx)
    for banned in ("rm", "curl", "powershell", "apt-get"):
        with pytest.raises(ToolError):
            await call(tool_ctx, "start_program", program=banned, arguments=["x"],
                       folder="Work", purpose="trying it on")
    assert not jobs(), "a refused program still left a job behind"


async def test_shell_punctuation_is_refused_here_too(tool_ctx):
    work_folder(tool_ctx)
    with pytest.raises(ToolError, match="(?i)shell punctuation"):
        await call(tool_ctx, "start_program", program="python3",
                   arguments=["; rm -rf /"], folder="Work", purpose="trying it on")


async def test_the_approval_card_says_what_will_run(tool_ctx):
    from claw.tools.background_tools import StartArgs
    spec = build_registry().get("start_program")
    said = spec.context_for(
        StartArgs(program="ffmpeg", arguments=["-i", "big.mov", "out.mp4"],
                  purpose="convert the advert"), tool_ctx)
    assert "ffmpeg" in said and "big.mov" in said
    assert "background" in said and "convert the advert" in said


# ---------- it really runs in the background ----------
async def test_a_long_job_keeps_running_and_is_checked_on(tool_ctx):
    """The whole point: start it, do something else, look in on it."""
    work_folder(tool_ctx)
    code = ("import time,sys\n"
            "for i in range(10):\n"
            "    print('step', i, flush=True)\n"
            "    time.sleep(0.3)\n")
    (work_folder(tool_ctx) / "slow.py").write_text(code, encoding="utf-8")

    started = await call(tool_ctx, "start_program", program="python3",
                         arguments=["slow.py"], folder="Work", purpose="a slow job")
    assert started.ok and started.data["running"] is True
    name = started.data["job"]

    # It is still going, and already saying something.
    await asyncio.sleep(0.8)
    mid = await call(tool_ctx, "check_program", job=name)
    assert mid.data["running"] is True, "it finished too fast to be a background test"
    assert "still running" in mid.summary
    assert "step" in mid.untrusted_text

    # And it finishes on its own, without anybody waiting on it.
    for _ in range(40):
        await asyncio.sleep(0.25)
        done = await call(tool_ctx, "check_program", job=name)
        if not done.data["running"]:
            break
    assert done.data["running"] is False, "it never finished"
    assert done.data["exit_code"] == 0
    assert "finished" in done.summary and "without an error" in done.summary
    assert "step 9" in done.untrusted_text, "the output from the whole run was not kept"


async def test_a_job_that_fails_reports_its_code(tool_ctx):
    work_folder(tool_ctx)
    (work_folder(tool_ctx) / "bad.py").write_text(
        "import sys\nprint('about to fail', flush=True)\nsys.exit(3)\n", encoding="utf-8")
    started = await call(tool_ctx, "start_program", program="python3", arguments=["bad.py"],
                         folder="Work", purpose="a job that fails")
    name = started.data["job"]
    for _ in range(40):
        await asyncio.sleep(0.2)
        done = await call(tool_ctx, "check_program", job=name)
        if not done.data["running"]:
            break
    assert done.data["exit_code"] == 3
    assert not done.ok and "code 3" in done.summary
    assert "about to fail" in done.untrusted_text


async def test_a_job_can_be_stopped(tool_ctx):
    work_folder(tool_ctx)
    (work_folder(tool_ctx) / "forever.py").write_text(
        "import time\nwhile True:\n    time.sleep(0.2)\n", encoding="utf-8")
    started = await call(tool_ctx, "start_program", program="python3", arguments=["forever.py"],
                         folder="Work", purpose="a job with no end")
    name = started.data["job"]
    await asyncio.sleep(0.5)
    assert (await call(tool_ctx, "check_program", job=name)).data["running"] is True

    stopped = await call(tool_ctx, "stop_program", job=name)
    assert stopped.ok and stopped.data["running"] is False
    assert "Stopped" in stopped.summary
    assert (await call(tool_ctx, "check_program", job=name)).data["running"] is False


async def test_checking_without_a_name_takes_the_most_recent(tool_ctx):
    work_folder(tool_ctx)
    (work_folder(tool_ctx) / "quick.py").write_text("print('one')\n", encoding="utf-8")
    started = await call(tool_ctx, "start_program", program="python3", arguments=["quick.py"],
                         folder="Work", purpose="a quick job")
    seen = await call(tool_ctx, "check_program")
    assert seen.data["job"] == started.data["job"]


async def test_asking_about_nothing_says_so(tool_ctx):
    with pytest.raises(ToolError, match="No program has been started"):
        await call(tool_ctx, "check_program")


async def test_an_unknown_name_lists_what_is_there(tool_ctx):
    work_folder(tool_ctx)
    (work_folder(tool_ctx) / "quick.py").write_text("print('one')\n", encoding="utf-8")
    await call(tool_ctx, "start_program", program="python3", arguments=["quick.py"],
               folder="Work", purpose="a quick job")
    with pytest.raises(ToolError, match="no background program called"):
        await call(tool_ctx, "check_program", job="not-a-job")


async def test_a_program_that_dies_at_once_is_reported_at_once(tool_ctx):
    """Not in ten minutes when somebody thinks to look."""
    work_folder(tool_ctx)
    started = await call(tool_ctx, "start_program", program="python3",
                         arguments=["no-such-file-xyz.py"], folder="Work",
                         purpose="a file that is not there")
    assert started.data["running"] is False
    assert not started.ok and "stopped immediately" in started.summary


async def test_too_many_at_once_is_refused(tool_ctx):
    work_folder(tool_ctx)
    (work_folder(tool_ctx) / "forever.py").write_text(
        "import time\nwhile True:\n    time.sleep(0.2)\n", encoding="utf-8")
    for _ in range(MAX_JOBS):
        await call(tool_ctx, "start_program", program="python3", arguments=["forever.py"],
                   folder="Work", purpose="one of many")
    with pytest.raises(ToolError, match="as many as"):
        await call(tool_ctx, "start_program", program="python3", arguments=["forever.py"],
                   folder="Work", purpose="one too many")
