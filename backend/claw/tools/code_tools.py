"""Running a program, and writing one to run.

What makes a coding agent general is not a tool per job. It is three things:
run something, read what came back, and decide what to do next. S-CLAW has the
third already - the executor is that loop - and a hundred specialist tools
standing in for the first two. This is the first two.

It is also the most dangerous thing in the registry, so every edge is blunted
deliberately:

- No shell. Arguments are a list handed to the program directly, so there are
  no pipes, no redirects, no globbing and no `rm -rf $(...)`. A request cannot
  smuggle a second command inside the first.
- An allowlist of programs, not a denylist. A denylist is a guess about what is
  dangerous; an allowlist is a statement about what is wanted. The person can
  add to it in settings.
- It runs in a folder they authorised, and nowhere else.
- DESTRUCTIVE risk, so under the ordinary policy it asks every single time and
  the person sees the exact command before it runs.
- A timeout, an output cap, and the whole thing in the audit trail.

What it is NOT: a way around the permission model. Everything above still
applies when the brain writes the program itself.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import sys

from pydantic import Field, field_validator

from claw.agent.schemas import Capability
from claw.permissions.policy import RiskLevel
from claw.tools.base import ToolArgs, ToolContext, ToolError, ToolRegistry, ToolResult, ToolSpec, as_str_list
from claw.tools.file_tools import existing_folder, safe_file_name, unique_path

WIN = sys.platform == "win32"

#: Programs Claw will run without being told to. Chosen because they do a job
#: and report a result, not because they are harmless: python can delete a
#: disk. The protection is the approval prompt and the working folder, not this
#: list - the list is here so a brain cannot reach for something nobody
#: expected, like a package manager or a disk tool.
DEFAULT_PROGRAMS = frozenset({
    # Interpreters and version control
    "python", "python3", "py", "node", "git",
    # Media and documents
    "ffmpeg", "ffprobe", "magick", "convert", "tesseract", "pandoc",
    "blender", "openscad", "soffice", "libreoffice", "inkscape", "gimp",
    "pdftoppm", "pdfinfo", "qpdf", "7z", "tar", "unzip",
    # Checking the person's own project, all of it local
    "pytest", "ruff", "mypy", "eslint", "prettier", "tsc", "make",
})

#: npm and npx are NOT here, and that is the point of this note.
#:
#: The line everywhere else in this file is "does it fetch code from the
#: internet and run it?" - which is why curl, wget and ssh are refused outright
#: and apt, brew, choco and winget with them. npx does exactly that, in one
#: step, by design: `npx anything` downloads a package and executes it. npm
#: install runs a package's own postinstall script. Allowing those while
#: banning curl was not a considered trade-off, it was an oversight, and the
#: approval prompt is no defence - nobody reads "npm install" as "run code
#: somebody published an hour ago".
#:
#: They are a reasonable thing to want. Add them under Settings > Limits, which
#: is a decision the person makes once, knowingly, rather than one Claw makes
#: for them silently.
FETCHES_AND_RUNS = frozenset({"npm", "npx", "pnpm", "yarn", "pip", "pip3", "pipx", "uv", "gem", "cargo", "go"})

#: Never, whatever the settings say. Each one either destroys things wholesale,
#: changes the machine outside any folder, or hands over administrator rights -
#: and none of them is how a task gets done.
NEVER = frozenset({
    "rm", "rmdir", "del", "erase", "format", "mkfs", "diskpart", "fdisk",
    "shutdown", "reboot", "halt", "poweroff", "taskkill", "killall",
    "sudo", "su", "runas", "doas", "chown", "chmod", "icacls", "takeown",
    "reg", "regedit", "regedt32", "bcdedit", "netsh", "sc", "wmic",
    "apt", "apt-get", "yum", "dnf", "pacman", "brew", "choco", "winget", "msiexec",
    "curl", "wget", "ssh", "scp", "nc", "ncat", "telnet",
    "powershell", "pwsh", "cmd", "bash", "sh", "zsh", "osascript", "wscript", "cscript",
})

#: Interpreters run_script may use, and the extension each one expects.
INTERPRETERS = {"python": ".py", "node": ".js"}

MAX_OUTPUT_CHARS = 8000
MAX_SECONDS = 300
MAX_SCRIPT_CHARS = 20000


def allowed_programs(ctx: ToolContext) -> frozenset[str]:
    """The default list plus anything the person added in settings."""
    extra = getattr(getattr(ctx.settings, "agent", None), "extra_programs", None) or []
    return DEFAULT_PROGRAMS | {str(x).strip().lower() for x in extra if str(x).strip()}


def program_name(command: str) -> str:
    """Just the program, lower-case, without a path or an .exe.

    Splits on BOTH separators by hand. Path() follows the rules of the machine
    it is running on, so on Linux `Path(r"C:\\Windows\\System32\\cmd.exe").name`
    is the whole string - and "cmd" never gets compared against the never-list.
    A refusal that depends on which operating system is checking is not a
    refusal.
    """
    raw = str(command).strip().strip('"').replace("\\", "/")
    return raw.rsplit("/", 1)[-1].lower().removesuffix(".exe")


def check_program(name: str, ctx: ToolContext) -> str:
    """The program to run, or a refusal that says why."""
    short = program_name(name)
    if not short:
        raise ToolError("Say which program to run.")
    if short in NEVER:
        raise ToolError(
            f"Claw will not run {short}. It deletes things wholesale, changes the computer "
            "outside any folder, or asks for administrator rights, and no task needs it. "
            "Do the job with a tool, or run it yourself.")
    if short not in allowed_programs(ctx):
        allowed = ", ".join(sorted(allowed_programs(ctx))[:12])
        raise ToolError(
            f"{short} is not a program Claw may run. The ones it may: {allowed}… "
            "Add it under Settings > Limits if you want it.")
    found = shutil.which(short)
    if not found:
        raise ToolError(f"{short} is not installed on this computer.")
    return found


#: An argument that BEGINS with shell punctuation: a pipe, a redirect, or a
#: second command. Only the beginning, because the punctuation itself is
#: harmless here - there is no shell to interpret it - and checking anywhere in
#: the argument refused `python -c "import os; print(os.getcwd())"`, which is
#: ordinary Python with a semicolon in it. What is worth catching is a brain
#: writing a shell line and expecting a shell: `program x > out.txt` quietly
#: passes ">" and "out.txt" to the program instead of redirecting, and the
#: brain is better told than left wondering.
_SHELL_START = re.compile(r"^\s*(?:\|\|?|&&?|;|>>?|<|`|\$\()")


def _looks_like_shell(parts: list[str]) -> str | None:
    """An argument that starts like a shell operator, which cannot do what it looks like."""
    for p in parts:
        if _SHELL_START.match(str(p)):
            return p
    return None


class RunArgs(ToolArgs):
    program: str = Field(min_length=1, max_length=100, description="e.g. python, git, ffmpeg")
    arguments: list[str] = Field(default_factory=list, max_length=40,
                                 description="Each argument separately, not one string")
    folder: str | None = Field(default=None, max_length=500, description="Authorized folder to run in")
    seconds: int = Field(default=60, ge=1, le=MAX_SECONDS, description="Give up after this long")

    @field_validator("arguments", mode="before")
    @classmethod
    def _list(cls, v):
        return as_str_list(v, limit=40)


def check_run(args: RunArgs, ctx: ToolContext) -> None:
    check_program(args.program, ctx)
    existing_folder(ctx, args.folder)
    bad = _looks_like_shell(list(args.arguments))
    if bad:
        raise ToolError(
            f"'{bad}' looks like shell punctuation. Claw runs the program directly, with no shell, "
            "so pipes and redirects do nothing. Give the arguments separately.")


def _describe(exe: str, args: list[str], code: int, out: str, err: str) -> str:
    head = f"{program_name(exe)} {' '.join(args)}".strip()
    if code == 0:
        return f"Ran {head}. It finished without an error."
    return f"Ran {head}. It stopped with code {code}" + (f": {err.strip().splitlines()[-1][:160]}" if err.strip() else ".")


async def run_command(args: RunArgs, ctx: ToolContext) -> ToolResult:
    """Run one program in an authorised folder and report exactly what it said."""
    exe = check_program(args.program, ctx)
    folder = existing_folder(ctx, args.folder)
    check_run(args, ctx)
    argv = [exe, *[str(a) for a in args.arguments]]

    def work():
        return subprocess.run(                      # noqa: S603 - a list, never a shell
            argv, cwd=str(folder), capture_output=True, text=True, timeout=args.seconds,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    try:
        done = await asyncio.to_thread(work)
    except subprocess.TimeoutExpired:
        raise ToolError(f"{program_name(exe)} was still running after {args.seconds} seconds "
                        "and was stopped. Nothing it had done is undone.") from None
    except OSError as exc:
        raise ToolError(f"Could not run {program_name(exe)}: {exc}") from exc

    out, err = (done.stdout or "")[:MAX_OUTPUT_CHARS], (done.stderr or "")[:MAX_OUTPUT_CHARS]
    both = (out + ("\n" + err if err.strip() else "")).strip()
    return ToolResult(
        done.returncode == 0, _describe(exe, [str(a) for a in args.arguments], done.returncode, out, err),
        {"program": program_name(exe), "exit_code": done.returncode,
         "folder": str(folder), "output_chars": len(both)},
        verified=done.returncode == 0, untrusted_text=both or "(it printed nothing)")


class ScriptArgs(ToolArgs):
    language: str = Field(default="python", description="python or node")
    code: str = Field(min_length=1, max_length=MAX_SCRIPT_CHARS, description="The whole program")
    purpose: str = Field(min_length=3, max_length=200, description="What this program is for, in one line")
    arguments: list[str] = Field(default_factory=list, max_length=20)
    folder: str | None = Field(default=None, max_length=500)
    seconds: int = Field(default=60, ge=1, le=MAX_SECONDS)
    keep: bool = Field(default=True, description="Leave the script file behind so the person can read it")

    @field_validator("language")
    @classmethod
    def _known(cls, v):
        lang = (v or "python").strip().lower()
        lang = {"py": "python", "python3": "python", "js": "node", "javascript": "node"}.get(lang, lang)
        if lang not in INTERPRETERS:
            raise ValueError(f"language must be one of: {', '.join(INTERPRETERS)}")
        return lang

    @field_validator("arguments", mode="before")
    @classmethod
    def _list(cls, v):
        return as_str_list(v, limit=20)


def check_script(args: ScriptArgs, ctx: ToolContext) -> None:
    check_program(args.language, ctx)
    existing_folder(ctx, args.folder)


async def run_script(args: ScriptArgs, ctx: ToolContext) -> ToolResult:
    """Write a small program into an authorised folder and run it.

    The script is saved, not piped in, so the person can read exactly what ran
    before they approve it and afterwards.
    """
    exe = check_program(args.language, ctx)
    folder = existing_folder(ctx, args.folder)
    stem = re.sub(r"[^A-Za-z0-9]+", "-", args.purpose.lower()).strip("-")[:40] or "script"
    script = unique_path(folder / safe_file_name(stem, INTERPRETERS[args.language]))
    ctx.policy.check_path(script, write=True)
    await asyncio.to_thread(script.write_text, args.code, "utf-8")

    def work():
        return subprocess.run(                      # noqa: S603 - a list, never a shell
            [exe, str(script), *[str(a) for a in args.arguments]],
            cwd=str(folder), capture_output=True, text=True, timeout=args.seconds,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    try:
        done = await asyncio.to_thread(work)
    except subprocess.TimeoutExpired:
        raise ToolError(f"The program was still running after {args.seconds} seconds and was stopped. "
                        f"It is saved at {script} if you want to look at it.") from None
    finally:
        if not args.keep:
            script.unlink(missing_ok=True)

    out, err = (done.stdout or "")[:MAX_OUTPUT_CHARS], (done.stderr or "")[:MAX_OUTPUT_CHARS]
    both = (out + ("\n" + err if err.strip() else "")).strip()
    ok = done.returncode == 0
    if args.keep:
        ctx.memory.outputs.append({"path": str(script), "kind": "script", "verified": ok,
                                   "note": "" if ok else f"exit code {done.returncode}"})
    where = f" The program is saved at {script}." if args.keep else ""
    summary = (f"Wrote and ran a {args.language} program to {args.purpose}. "
               + ("It finished without an error." if ok else f"It stopped with code {done.returncode}.")
               + where)
    return ToolResult(ok, summary,
                      {"path": str(script) if args.keep else None, "language": args.language,
                       "exit_code": done.returncode, "output_chars": len(both)},
                      verified=ok, untrusted_text=both or "(it printed nothing)")


def register_code_tools(reg: ToolRegistry) -> None:
    C, D = Capability.CODE, RiskLevel.DESTRUCTIVE
    reg.register(ToolSpec(
        "run_command", "Run a program on this computer (python, git, ffmpeg and the like) in an "
                       "authorized folder and report what it printed. Asks first, every time.",
        C, D, RunArgs, run_command, precheck=check_run))
    reg.register(ToolSpec(
        "run_script", "Write a small Python or Node program and run it in an authorized folder, "
                      "for a job no other tool does. Asks first, and the program is saved to read.",
        C, D, ScriptArgs, run_script, precheck=check_script))
