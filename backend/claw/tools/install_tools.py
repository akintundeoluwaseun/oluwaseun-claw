"""Installing a program, the way a person would, with them agreeing to it.

Claw could open an app that was already there and could not put one on the
machine. "Install VLC so you can convert this" was refused, which is a
strange answer from something whose whole job is to work the computer.

Three rules this is built on, and none of them bends:

  It is never silent. Installing is destructive-risk, so the person is asked
  every single time, and the card tells them the real name, publisher and
  version of what is about to arrive - not the word they typed. The
  permission policy refuses to let destructive ever mean "allow", so there
  is no setting that turns this into something that happens behind them.

  It is the official catalogue only. On Windows that is winget, which ships
  with Windows 10 and 11 and installs from Microsoft's own curated source.
  A custom source, a manifest from somewhere else, or a bare URL is refused:
  "install this .exe I found" is how people lose a machine, and Claw is not
  going to be the one holding the mouse.

  It is checked afterwards. winget reporting success is not the same as the
  program being there, so the package is looked up again after the install
  and the result says what is actually on the machine.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import sys
from pathlib import Path

from pydantic import Field, field_validator

from claw.agent.schemas import Capability
from claw.permissions.policy import RiskLevel
from claw.tools.base import ToolArgs, ToolContext, ToolError, ToolRegistry, ToolResult, ToolSpec

#: A package id is letters, digits and the separators the catalogues use.
#: Anything else - a space, a slash, a quote, a semicolon - is either not an
#: id or an attempt to add a second command, and both are refused here
#: rather than passed to a shell.
PACKAGE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,80}$")

#: Longest an install may take before Claw stops waiting. Office-sized
#: packages are slow on a home connection.
INSTALL_TIMEOUT = 20 * 60
SEARCH_TIMEOUT = 90

#: Things that are not programs in the ordinary sense, and that a person
#: almost never means when they ask Claw to install something. Refusing
#: these by name is cheap and avoids an expensive misunderstanding.
NOT_THROUGH_CLAW = {
    "windows", "windows11", "windows10", "microsoft.windows",
    "nvidia.geforceexperience.driver", "driver", "drivers", "bios",
}


def _winget() -> str | None:
    return shutil.which("winget")


def _apt() -> str | None:
    """Linux, for development and for the tests that prove this works."""
    return shutil.which("apt-get")


def manager(ctx: ToolContext) -> tuple[str, str]:
    """(program, which catalogue), or an error saying why not."""
    if sys.platform == "win32":
        found = _winget()
        if not found:
            raise ToolError(
                "This computer does not have winget, which is how Claw installs programs. It "
                "comes with Windows 10 and 11 as 'App Installer'; install that from the "
                "Microsoft Store and ask again.")
        return found, "winget"
    found = _apt()
    if not found:
        raise ToolError("Claw can install programs on Windows (with winget) and on Debian-based "
                        "Linux (with apt). This computer has neither.")
    return found, "apt"


async def _run(program: str, arguments: list[str], seconds: int) -> tuple[int, str]:
    """Run the package manager directly - no shell, so nothing is interpreted."""
    proc = await asyncio.create_subprocess_exec(
        program, *arguments,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=seconds)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise ToolError(f"{Path(program).name} was still running after {seconds // 60} minutes, "
                        "so Claw stopped waiting. It may still be installing in the background.") from None
    return proc.returncode or 0, (out or b"").decode("utf-8", "replace")


def check_id(raw: str) -> str:
    name = str(raw).strip()
    if not name:
        raise ToolError("Say which program to install.")
    if "://" in name or name.lower().endswith((".exe", ".msi", ".msix", ".appx")):
        raise ToolError(
            f"Claw installs from the official catalogue, not from a file or a link. "
            f"'{name[:60]}' is an installer, and Claw will not download and run one - that is "
            "the usual way a machine gets something it did not want. Give the program's name "
            "and Claw will look it up.")
    if not PACKAGE_ID.match(name):
        raise ToolError(
            f"'{name[:60]}' is not a package name Claw will use. A name is letters, digits, "
            "dots and dashes - spaces and punctuation are not part of one.")
    if name.lower() in NOT_THROUGH_CLAW:
        raise ToolError(f"Claw does not install {name} for you. That one is for you to do yourself.")
    return name


# ---------- find out what is actually on offer ----------
class FindArgs(ToolArgs):
    name: str = Field(min_length=1, max_length=80, description="e.g. vlc, 7zip, libreoffice")


def parse_winget_table(text: str) -> list[dict]:
    """winget prints a fixed-width table. Take Name, Id, Version from it."""
    rows: list[dict] = []
    lines = [ln.rstrip() for ln in text.splitlines()]
    header = next((i for i, ln in enumerate(lines)
                   if re.match(r"^Name\s+Id\s", ln)), None)
    if header is None:
        return rows
    for line in lines[header + 2:]:
        if not line.strip() or set(line.strip()) <= {"-"}:
            continue
        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) >= 2 and PACKAGE_ID.match(parts[1]):
            rows.append({"name": parts[0], "id": parts[1],
                         "version": parts[2] if len(parts) > 2 else ""})
    return rows


async def find_app_to_install(args: FindArgs, ctx: ToolContext) -> ToolResult:
    program, which = manager(ctx)
    name = str(args.name).strip()
    if not re.fullmatch(r"[A-Za-z0-9 ._+-]{1,80}", name):
        raise ToolError("Search for a program by its name: letters, digits, spaces and dashes.")

    if which == "winget":
        code, out = await _run(program, ["search", "--source", "winget", "--exact", name],
                               SEARCH_TIMEOUT)
        found = parse_winget_table(out)
        if not found:
            code, out = await _run(program, ["search", "--source", "winget", name], SEARCH_TIMEOUT)
            found = parse_winget_table(out)
    else:
        code, out = await _run(program, ["-s", "install", name], SEARCH_TIMEOUT)
        found = ([{"name": name, "id": name, "version": ""}]
                 if "Inst " in out or "The following NEW packages" in out else [])

    if not found:
        return ToolResult(
            True, f"Nothing called '{name}' is in the {which} catalogue. Check the spelling, or "
                  "give the exact name from the program's own website.",
            {"found": []}, verified=True)

    shown = "; ".join(f"{f['name']} (id {f['id']}{', ' + f['version'] if f['version'] else ''})"
                      for f in found[:6])
    return ToolResult(
        True,
        f"{len(found)} match(es) for '{name}' in the {which} catalogue: {shown}"
        + ("..." if len(found) > 6 else "")
        + ". Nothing was installed; say which one to install.",
        {"found": found[:20], "catalogue": which}, verified=True)


# ---------- install it ----------
class InstallArgs(ToolArgs):
    package_id: str = Field(min_length=1, max_length=80,
                            description="The exact id from find_app_to_install, e.g. VideoLAN.VLC")

    @field_validator("package_id")
    @classmethod
    def _id(cls, v: str) -> str:
        return check_id(v)


def describe_install(args: InstallArgs, ctx: ToolContext) -> str:
    """The line on the approval card.

    It names the exact package id, not the word the person typed and not
    the brain's paraphrase, because the id is what is actually going to be
    installed and the two are not always the same thing.
    """
    where = "winget" if sys.platform == "win32" else "apt"
    return (f"Install {args.package_id} from the official {where} catalogue onto this computer. "
            "Nothing is downloaded from anywhere else.")


async def install_app(args: InstallArgs, ctx: ToolContext) -> ToolResult:
    program, which = manager(ctx)
    package = args.package_id

    before = await _is_installed(program, which, package)
    if before:
        return ToolResult(
            True, f"{package} is already installed on this computer. Nothing was changed.",
            {"package": package, "already": True}, verified=True)

    if which == "winget":
        arguments = ["install", "--id", package, "--exact",
                     "--source", "winget",          # the official source, never another
                     "--accept-package-agreements", "--accept-source-agreements",
                     "--disable-interactivity"]
    else:
        arguments = ["install", "-y", package]

    code, out = await _run(program, arguments, INSTALL_TIMEOUT)
    after = await _is_installed(program, which, package)

    # winget's exit code is not the question. Whether the program is on the
    # machine is the question, and that is asked separately.
    ok = after
    tail = "\n".join(ln for ln in out.splitlines() if ln.strip())[-400:]
    if ok:
        summary = (f"Installed {package} from the {which} catalogue, and checked afterwards that "
                   f"it is on this computer.")
        if sys.platform == "win32":
            summary += " A new program sometimes needs a sign-out before Windows lists it everywhere."
    else:
        summary = (f"{package} did NOT install. {which} finished with code {code} and the program "
                   f"is still not on this computer.")
    # Deliberately NOT recorded in ctx.memory.outputs. That list is the files
    # a task produced, and the "no new files" limit is built on it; an
    # install produces a program, not a file in a folder, and an entry with
    # an empty path made the guard treat this as a file-writing tool that
    # had forgotten to declare itself. It was right to complain.
    return ToolResult(ok, summary, {"package": package, "catalogue": which,
                                    "installed": after, "exit_code": code},
                      verified=ok, untrusted_text=tail)


async def _is_installed(program: str, which: str, package: str) -> bool:
    if which == "winget":
        code, out = await _run(program, ["list", "--id", package, "--exact"], SEARCH_TIMEOUT)
        return code == 0 and package.lower() in out.lower()
    code, out = await _run("dpkg-query", ["-W", "-f=${Status}", package], SEARCH_TIMEOUT)
    return code == 0 and "install ok installed" in out


def register_install_tools(reg: ToolRegistry) -> None:
    reg.register(ToolSpec(
        "find_app_to_install", "Look up a program in the official catalogue (winget on Windows) "
                               "and report what is on offer. Installs nothing.",
        Capability.DESKTOP, RiskLevel.READ_ONLY, FindArgs, find_app_to_install))
    reg.register(ToolSpec(
        "install_app", "Install a program from the official catalogue onto this computer. Asks "
                       "first, every time, and checks afterwards that it is really there.",
        Capability.DESKTOP, RiskLevel.DESTRUCTIVE, InstallArgs, install_app,
        context_for=describe_install))
