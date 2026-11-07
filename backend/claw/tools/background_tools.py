"""Starting a program and coming back to it, instead of waiting for it.

run_command waits, and gives up after five minutes. That is right for most
things and wrong for exactly the jobs people care most about: rendering a
video in Blender, converting an hour of footage, building something, a long
export. Those take twenty minutes, and being killed at five with "it was
still running" is the worst of both - the work is thrown away and the person
is told nothing useful.

So: start it, get on with something else, look in on it. The same three
steps a person takes, and the same three I take when a build is long.

Everything that guards run_command guards this too - the same allowlist, the
same refusal of shell punctuation, the same authorised folder, the same
approval before anything runs. Starting a program in the background is not
a way around any of that, and the tests check it.

Output goes to a file as it is produced rather than being held in memory, so
a program that prints for twenty minutes cannot fill the machine, and
whatever it managed to say survives even if it is killed.
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import Field

from claw.agent.schemas import Capability
from claw.permissions.policy import RiskLevel
from claw.tools.base import ToolArgs, ToolContext, ToolError, ToolRegistry, ToolResult, ToolSpec
from claw.tools.code_tools import _looks_like_shell, check_program, program_name
from claw.tools.file_tools import existing_folder

#: Longest a background job may live before Claw stops it. Eight hours is
#: longer than any render a person waits for and short enough that a stuck
#: program does not sit there until the machine is rebooted.
MAX_LIFE_S = 8 * 60 * 60
#: How much of the output is handed to the brain at a time.
MAX_SHOWN = 4000
#: More than this running at once is a mistake, not a workflow.
MAX_JOBS = 8


@dataclass
class Job:
    id: str
    program: str
    arguments: list[str]
    folder: str
    log: Path
    started: float
    process: subprocess.Popen = field(repr=False)
    handle = None

    def running(self) -> bool:
        return self.process.poll() is None

    def seconds(self) -> float:
        return time.time() - self.started

    def output(self) -> str:
        try:
            return self.log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""


#: Jobs live for the life of the backend, not of a task: starting a render
#: in one step and checking it in another is the whole point.
_JOBS: dict[str, Job] = {}


def jobs() -> dict[str, Job]:
    return _JOBS


def _reap() -> None:
    """Stop anything that has outlived its welcome, and forget the finished."""
    for job in list(_JOBS.values()):
        if job.running() and job.seconds() > MAX_LIFE_S:
            _end(job)


def _end(job: Job) -> None:
    """Stop a job as politely as the platform allows, then firmly."""
    if not job.running():
        return
    try:
        if sys.platform == "win32":
            job.process.terminate()
        else:
            os.killpg(os.getpgid(job.process.pid), signal.SIGTERM)
    except (OSError, PermissionError):
        pass
    try:
        job.process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            if sys.platform == "win32":
                job.process.kill()
            else:
                os.killpg(os.getpgid(job.process.pid), signal.SIGKILL)
        except (OSError, PermissionError):
            pass


class StartArgs(ToolArgs):
    program: str = Field(min_length=1, max_length=120,
                         description="e.g. blender, ffmpeg - the same programs run_command allows")
    arguments: list[str] = Field(default_factory=list, max_length=60,
                                 description="Each argument separately, not one string")
    folder: str | None = Field(default=None, max_length=500,
                               description="Authorised folder to run in")
    purpose: str = Field(min_length=3, max_length=200,
                         description="What this is for, in one line")


def check_start(args: StartArgs, ctx: ToolContext) -> None:
    """Exactly the gates run_command uses. This is not a way round them."""
    bad = _looks_like_shell([str(a) for a in args.arguments])
    if bad:
        # _looks_like_shell returns the offending ARGUMENT, not a sentence.
        # Raising it raw gave the person "; rm -rf /" as the whole error,
        # which explains nothing; run_command's wording is the right one.
        raise ToolError(
            f"'{bad}' looks like shell punctuation. Claw runs the program directly, with no "
            "shell, so pipes and redirects do nothing. Give the arguments separately.")
    _reap()
    alive = [j for j in _JOBS.values() if j.running()]
    if len(alive) >= MAX_JOBS:
        raise ToolError(
            f"{len(alive)} programs are already running in the background, which is as many as "
            "Claw will start. Check on them or stop one first.")


def describe_start(args: StartArgs, ctx: ToolContext) -> str:
    joined = " ".join(str(a) for a in args.arguments)
    return (f"Start {args.program} {joined}".strip()
            + f" in the background and leave it running. For: {args.purpose}")


async def start_program(args: StartArgs, ctx: ToolContext) -> ToolResult:
    exe = check_program(args.program, ctx)          # the allowlist, unchanged
    folder = existing_folder(ctx, args.folder)
    check_start(args, ctx)
    argv = [exe, *[str(a) for a in args.arguments]]

    data = Path(getattr(ctx, "data_dir", None) or folder) / "background"
    data.mkdir(parents=True, exist_ok=True)
    job_id = f"{program_name(exe)}-{int(time.time() * 1000) % 10_000_000}"
    log = data / f"{job_id}.log"

    def work():
        handle = open(log, "wb")                    # noqa: SIM115 - closed when the job ends
        extra = {}
        if sys.platform != "win32":
            # Its own process group, so stopping it stops what it started.
            extra["start_new_session"] = True
        else:
            extra["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        process = subprocess.Popen(                 # noqa: S603 - a list, never a shell
            argv, cwd=str(folder), stdout=handle, stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"}, **extra)
        return process, handle

    try:
        process, handle = await asyncio.to_thread(work)
    except OSError as exc:
        raise ToolError(f"Could not start {program_name(exe)}: {exc}") from exc

    job = Job(id=job_id, program=program_name(exe), arguments=[str(a) for a in args.arguments],
              folder=str(folder), log=log, started=time.time(), process=process)
    job.handle = handle
    _JOBS[job_id] = job

    # A program that dies immediately is a failure to report now, not in ten
    # minutes when somebody thinks to look.
    await asyncio.sleep(0.4)
    if not job.running() and job.process.returncode != 0:
        return ToolResult(
            False,
            f"{job.program} stopped immediately with code {job.process.returncode}. It is not "
            f"running. {job.output()[:300]}",
            {"job": job_id, "running": False, "exit_code": job.process.returncode},
            verified=False, untrusted_text=job.output()[:MAX_SHOWN])

    return ToolResult(
        True,
        f"Started {job.program} in the background as '{job_id}' — {args.purpose}. It is still "
        "running; use check_program with that name to see how it is getting on.",
        {"job": job_id, "running": True, "folder": str(folder)}, verified=True)


class JobArgs(ToolArgs):
    job: str = Field(default="", max_length=80,
                     description="The name start_program gave; leave out for the most recent")


def _pick(args: JobArgs) -> Job:
    _reap()
    if not _JOBS:
        raise ToolError("No program has been started in the background.")
    if args.job:
        job = _JOBS.get(args.job)
        if job is None:
            known = ", ".join(sorted(_JOBS)) or "none"
            raise ToolError(f"There is no background program called '{args.job}'. Running: {known}.")
        return job
    return max(_JOBS.values(), key=lambda j: j.started)


async def check_program_progress(args: JobArgs, ctx: ToolContext) -> ToolResult:
    job = _pick(args)
    text = await asyncio.to_thread(job.output)
    tail = text[-MAX_SHOWN:]
    minutes = job.seconds() / 60

    if job.running():
        summary = (f"{job.program} ('{job.id}') is still running after "
                   f"{minutes:.1f} minute(s). It has printed {len(text):,} character(s) so far.")
        ok = True
    else:
        code = job.process.returncode
        ok = code == 0
        summary = (f"{job.program} ('{job.id}') finished after {minutes:.1f} minute(s) "
                   + ("without an error." if ok else f"with code {code}."))
        if job.handle is not None:
            try:
                job.handle.close()
            except OSError:
                pass
            job.handle = None

    return ToolResult(
        ok, summary,
        {"job": job.id, "running": job.running(), "seconds": round(job.seconds(), 1),
         "exit_code": None if job.running() else job.process.returncode,
         "output_chars": len(text), "log": str(job.log)},
        verified=True, untrusted_text=tail or "(it has printed nothing yet)")


async def stop_program(args: JobArgs, ctx: ToolContext) -> ToolResult:
    job = _pick(args)
    if not job.running():
        return ToolResult(True, f"{job.program} ('{job.id}') had already finished.",
                          {"job": job.id, "running": False}, verified=True)
    await asyncio.to_thread(_end, job)
    stopped = not job.running()
    return ToolResult(
        stopped,
        f"Stopped {job.program} ('{job.id}') after {job.seconds() / 60:.1f} minute(s). "
        "Anything it had already done is not undone."
        if stopped else f"{job.program} ('{job.id}') would not stop.",
        {"job": job.id, "running": job.running()}, verified=stopped)


def register_background_tools(reg: ToolRegistry) -> None:
    reg.register(ToolSpec(
        "start_program", "Start a long job - a render, a conversion, a build - and leave it "
                         "running instead of waiting for it. Asks first, like run_command.",
        Capability.CODE, RiskLevel.DESTRUCTIVE, StartArgs, start_program,
        precheck=check_start, context_for=describe_start))
    reg.register(ToolSpec(
        "check_program", "See how a background job is getting on, and what it has printed.",
        Capability.CODE, RiskLevel.READ_ONLY, JobArgs, check_program_progress))
    reg.register(ToolSpec(
        "stop_program", "Stop a background job that is still running.",
        Capability.CODE, RiskLevel.LOCAL_WRITE, JobArgs, stop_program))
