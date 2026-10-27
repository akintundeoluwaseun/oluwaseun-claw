"""What the machine itself can answer: the clock, free disk space, and whether a
program is actually running.

These read the real system. "Is Notepad running" asks the operating system for
its process list rather than guessing from a window title, so the answer is no
when the program has been closed, even if a window of it was open a moment ago.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from pydantic import Field

from claw.agent.schemas import Capability
from claw.permissions.policy import PathNotAuthorized, RiskLevel
from claw.tools.base import ToolArgs, ToolContext, ToolError, ToolRegistry, ToolResult, ToolSpec

PROCESS_TIMEOUT_S = 15
# Friendly names people use for Windows programs, and the executable each one is.
KNOWN_PROGRAMS = {
    "notepad": "notepad.exe", "calculator": "calculatorapp.exe", "calc": "calculatorapp.exe",
    "word": "winword.exe", "excel": "excel.exe", "powerpoint": "powerpnt.exe",
    "outlook": "outlook.exe", "edge": "msedge.exe", "chrome": "chrome.exe",
    "firefox": "firefox.exe", "explorer": "explorer.exe", "paint": "mspaint.exe",
    "file explorer": "explorer.exe", "task manager": "taskmgr.exe", "cmd": "cmd.exe",
    "powershell": "powershell.exe", "terminal": "windowsterminal.exe", "vlc": "vlc.exe",
    "spotify": "spotify.exe", "whatsapp": "whatsapp.exe", "teams": "ms-teams.exe",
    "claw": "oluwaseun claw.exe", "oluwaseun claw": "oluwaseun claw.exe",
}


# ---------- current_time ----------
class TimeArgs(ToolArgs):
    pass


async def current_time(args: TimeArgs, ctx: ToolContext) -> ToolResult:
    now = datetime.now().astimezone()
    data = {
        "iso": now.isoformat(timespec="seconds"),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "day_of_week": now.strftime("%A"),
        "timezone": now.tzname() or "",
        "utc_offset_minutes": int((now.utcoffset() or datetime.now(timezone.utc).utcoffset()).total_seconds() // 60)
        if now.utcoffset() is not None else 0,
        "unix_seconds": int(now.timestamp()),
    }
    return ToolResult(True, f"It is {now.strftime('%A, %d %B %Y, %H:%M')} ({data['timezone']}).",
                      data, verified=True)


# ---------- disk_space ----------
class DiskArgs(ToolArgs):
    path: str | None = Field(default=None, max_length=500,
                             description="A folder or drive to check; the system drive by default")


async def disk_space(args: DiskArgs, ctx: ToolContext) -> ToolResult:
    if args.path:
        # A drive letter or folder the user named still has to be one Claw may look at.
        try:
            target = ctx.policy.check_path(args.path)
        except PathNotAuthorized as exc:
            raise ToolError(str(exc)) from exc
    else:
        target = Path(os.environ.get("SystemDrive", "C:") + "\\") if sys.platform == "win32" else Path("/")
    probe = target
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        usage = await asyncio.to_thread(shutil.disk_usage, probe)
    except OSError as exc:
        raise ToolError(f"The free space on '{target}' could not be read: {exc.strerror}") from exc
    gb = 1024 ** 3
    free_gb, total_gb = usage.free / gb, usage.total / gb
    percent = round(usage.free / usage.total * 100, 1) if usage.total else 0.0
    return ToolResult(
        True,
        f"{free_gb:,.1f} GB free of {total_gb:,.1f} GB on {probe} ({percent}% free).",
        {"path": str(probe), "free_gb": round(free_gb, 2), "total_gb": round(total_gb, 2),
         "used_gb": round(usage.used / gb, 2), "percent_free": percent,
         "free_bytes": usage.free, "total_bytes": usage.total},
        verified=True,
    )


# ---------- is_program_running ----------
class ProgramArgs(ToolArgs):
    program: str = Field(min_length=1, max_length=100,
                         description='A program name, e.g. "Notepad" or "msedge.exe"')


def _process_names() -> list[str]:
    """Every running process's executable name, lower-cased.

    Fixed arguments, no shell, and nothing the user typed reaches the command line:
    the name is matched in Python afterwards.
    """
    if sys.platform == "win32":
        cmd = ["tasklist.exe", "/fo", "csv", "/nh"]
    elif sys.platform == "darwin":
        cmd = ["/bin/ps", "-axco", "command"]
    else:
        cmd = ["/bin/ps", "-eo", "comm="]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=PROCESS_TIMEOUT_S,
                             check=False, shell=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ToolError(f"The list of running programs could not be read: {exc}") from exc
    if out.returncode != 0 and not out.stdout.strip():
        raise ToolError("The list of running programs could not be read.")
    names = []
    for line in out.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        if sys.platform == "win32":
            # tasklist CSV: "name.exe","pid",...  — the first quoted field is the name.
            parts = line.split('","')
            line = parts[0].lstrip('"') if parts else line
        names.append(Path(line).name.lower())
    return names


async def is_program_running(args: ProgramArgs, ctx: ToolContext) -> ToolResult:
    names = await asyncio.to_thread(_process_names)
    wanted = args.program.strip().lower()
    exe = KNOWN_PROGRAMS.get(wanted, wanted)
    stem = Path(exe).stem.lower()
    matches = sorted({n for n in names if n == exe or Path(n).stem.lower() == stem})
    running = bool(matches)
    return ToolResult(
        True,
        f"{args.program} is running ({', '.join(matches)}; {len(names)} processes checked)." if running
        else f"{args.program} is not running. {len(names)} running processes were checked.",
        {"program": args.program, "looked_for": exe, "running": running,
         "matches": matches, "processes_checked": len(names)},
        verified=True,
    )


def register_system_tools(reg: ToolRegistry) -> None:
    D, R = Capability.DESKTOP, RiskLevel.READ_ONLY
    reg.register(ToolSpec("current_time", "The current date, time and day of the week from the system clock.",
                          D, R, TimeArgs, current_time))
    reg.register(ToolSpec("disk_space", "How much disk space is free on a drive.",
                          D, R, DiskArgs, disk_space))
    reg.register(ToolSpec("is_program_running", "Check the real process list for whether a program is running.",
                          D, R, ProgramArgs, is_program_running))
