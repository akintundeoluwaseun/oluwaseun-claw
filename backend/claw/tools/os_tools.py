"""Milestone 4 (challenge section 15): startup apps, memory use, broken shortcuts, renaming many files, archiving.

Read-only where it can be: the startup list, the memory list and the shortcut check change nothing.
Renaming and archiving write, go through the person's approval like any change, never overwrite,
and are checked afterwards (every renamed file is there under its new name; the archive is reopened
and its file count and CRC checked).
"""

from __future__ import annotations

import asyncio
import csv
import io
import os
import re
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

from pydantic import Field

from claw.agent.schemas import Capability
from claw.permissions.policy import RiskLevel
from claw.tools.base import NoArgs, ToolArgs, ToolContext, ToolError, ToolRegistry, ToolResult, ToolSpec
from claw.tools.file_tools import existing_folder, safe_file_name, unique_path

WIN = sys.platform == "win32"


def _run(cmd: list[str], timeout: float = 20) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ToolError(f"Could not run {cmd[0]}: {exc}") from exc
    return r.stdout


# ---------- startup apps (15.06) ----------
def _startup_entries() -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    if WIN:
        import winreg  # noqa: PLC0415
        keys = [(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", "you"),
                (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Run", "all users"),
                (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run", "all users")]
        for hive, path, who in keys:
            try:
                with winreg.OpenKey(hive, path) as k:
                    i = 0
                    while True:
                        try:
                            name, value, _ = winreg.EnumValue(k, i)
                        except OSError:
                            break
                        out.append((name, str(value), f"registry ({who})"))
                        i += 1
            except OSError:
                continue
        folders = [Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup",
                   Path(os.environ.get("PROGRAMDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\StartUp"]
    else:
        folders = [Path.home() / ".config" / "autostart", Path.home() / "Library" / "LaunchAgents"]
    for f in folders:
        if f.is_dir():
            out += [(p.stem, str(p), "startup folder") for p in sorted(f.iterdir()) if p.is_file() and p.name != "desktop.ini"]
    return out


async def list_startup_apps(args: NoArgs, ctx: ToolContext) -> ToolResult:
    rows = await asyncio.to_thread(_startup_entries)
    text = "\n".join(f"- {n}: {cmd[:160]} [{where}]" for n, cmd, where in rows)
    return ToolResult(True, f"{len(rows)} program(s) start automatically when you sign in: "
                            + (", ".join(n for n, _, _ in rows[:15]) or "none") + ". Nothing was changed.",
                      {"entries": [{"name": n, "command": c, "where": w} for n, c, w in rows]}, True, text)


# ---------- memory use (15.08) ----------
def _processes() -> list[tuple[str, int, int]]:
    rows: list[tuple[str, int, int]] = []
    if WIN:
        for r in csv.reader(io.StringIO(_run(["tasklist", "/fo", "csv", "/nh"]))):
            if len(r) >= 5:
                kb = int(re.sub(r"\D", "", r[4]) or 0)
                rows.append((r[0], int(r[1]) if r[1].isdigit() else 0, kb * 1024))
    else:
        for line in _run(["ps", "-eo", "pid=,rss=,comm="]).splitlines():
            parts = line.split(None, 2)
            if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
                rows.append((Path(parts[2]).name, int(parts[0]), int(parts[1]) * 1024))
    return rows


async def top_memory(args: NoArgs, ctx: ToolContext) -> ToolResult:
    rows = await asyncio.to_thread(_processes)
    totals: dict[str, list[int]] = {}
    for name, _, b in rows:
        t = totals.setdefault(name, [0, 0])
        t[0] += b
        t[1] += 1
    top = sorted(totals.items(), key=lambda x: -x[1][0])[:10]
    line = "; ".join(f"{n} {v[0] / 2**20:,.0f} MB" + (f" ({v[1]} processes)" if v[1] > 1 else "") for n, v in top)
    return ToolResult(True, f"Using the most memory right now: {line}. Nothing was closed.",
                      {"top": [{"name": n, "bytes": v[0], "processes": v[1]} for n, v in top]}, True)


# ---------- broken shortcuts (15.05) ----------
class ShortcutArgs(ToolArgs):
    folder: str = Field(min_length=1, max_length=500, description="e.g. Desktop")


def _shortcut_target(p: Path) -> str | None:
    if p.suffix.lower() == ".url":
        m = re.search(r"^URL=(.+)$", p.read_text(errors="ignore"), re.M)
        return m.group(1).strip() if m else None
    if WIN:
        try:
            import win32com.client  # noqa: PLC0415
            return win32com.client.Dispatch("WScript.Shell").CreateShortCut(str(p)).Targetpath or None
        except Exception:  # noqa: BLE001
            return None
    return None


async def find_broken_shortcuts(args: ShortcutArgs, ctx: ToolContext) -> ToolResult:
    root = existing_folder(ctx, args.folder)

    def work():
        broken, ok, unknown = [], 0, 0
        for p in root.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in (".lnk", ".url"):
                continue
            if p.is_symlink():
                continue
            target = _shortcut_target(p)
            if not target:
                unknown += 1
            elif re.match(r"^[a-z]+://", target, re.I):
                ok += 1                       # a web address: not checked offline
            elif Path(os.path.expandvars(target)).exists():
                ok += 1
            else:
                broken.append((p, target))
        for p in root.rglob("*"):
            if p.is_symlink() and not p.exists():
                broken.append((p, os.readlink(p)))
        return broken, ok, unknown

    broken, ok, unknown = await asyncio.to_thread(work)
    text = "\n".join(f"- {b.name} -> {t} (missing)" for b, t in broken)
    return ToolResult(True, f"{len(broken)} broken shortcut(s) in {root.name}"
                            + (": " + ", ".join(f"{b.name} (points to {t})" for b, t in broken[:8]) if broken else "")
                            + f"; {ok} work" + (f"; {unknown} could not be read" if unknown else "") + ". Nothing was deleted.",
                      {"broken": [{"path": str(b), "target": t} for b, t in broken]}, True, text)


# ---------- bulk rename (15.13) ----------
class RenameManyArgs(ToolArgs):
    folder: str = Field(min_length=1, max_length=500)
    pattern: str = Field(default="*", max_length=100, description="Which files, e.g. *.jpg")
    new_name: str = Field(min_length=1, max_length=120,
                          description="Template: {n} number, {name} old name, {date} modified date, e.g. 'Holiday {n}'")
    start: int = Field(default=1, ge=0, le=100000)


def _plan_renames(folder: Path, args: RenameManyArgs) -> list[tuple[Path, Path]]:
    files = sorted((p for p in folder.glob(args.pattern) if p.is_file()), key=lambda p: (p.stat().st_mtime, p.name))
    if not files:
        raise ToolError(f"No files match '{args.pattern}' in {folder}.")
    if "{n}" not in args.new_name and "{name}" not in args.new_name and len(files) > 1:
        raise ToolError("With more than one file the new name needs {n} or {name}, or every file would get the same name.")
    width = len(str(args.start + len(files) - 1))
    plan, taken = [], {p.name.lower() for p in folder.iterdir()}
    for i, p in enumerate(files):
        stem = args.new_name.format(n=str(args.start + i).zfill(width), name=p.stem,
                                    date=datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d"))
        target = folder / safe_file_name(stem + p.suffix.lower(), p.suffix.lower())
        if target.name.lower() in taken and target.name.lower() != p.name.lower():
            raise ToolError(f"'{target.name}' already exists, so renaming would overwrite it. Nothing was renamed.")
        taken.add(target.name.lower())
        plan.append((p, target))
    return plan


def check_rename_many(args: RenameManyArgs, ctx: ToolContext) -> None:
    _plan_renames(existing_folder(ctx, args.folder, write=True), args)


async def rename_many(args: RenameManyArgs, ctx: ToolContext) -> ToolResult:
    folder = existing_folder(ctx, args.folder, write=True)
    plan = _plan_renames(folder, args)

    def work():
        # Two-step so "a -> b, b -> c" chains cannot collide midway.
        temps = []
        for i, (src, _) in enumerate(plan):
            tmp = src.with_name(f".claw-rename-{os.getpid()}-{i}{src.suffix}")
            src.rename(tmp)
            temps.append(tmp)
        for tmp, (_, dst) in zip(temps, plan):
            tmp.rename(dst)
        return [dst for _, dst in plan if dst.is_file()]

    done = await asyncio.to_thread(work)
    ok = len(done) == len(plan)
    sample = "; ".join(f"{s.name} -> {d.name}" for s, d in plan[:6])
    return ToolResult(ok, f"Renamed {len(done)} of {len(plan)} file(s) in {folder.name} and checked each new name exists. {sample}"
                          + (" ..." if len(plan) > 6 else ""), {"renamed": [[str(s), str(d)] for s, d in plan]}, verified=ok)


# ---------- archive a project (15.15) ----------
class ArchiveArgs(ToolArgs):
    folder: str = Field(min_length=1, max_length=500, description="The folder to pack")
    file_name: str = Field(default="", max_length=100)
    save_in: str | None = Field(default=None, max_length=500)


async def archive_folder(args: ArchiveArgs, ctx: ToolContext) -> ToolResult:
    src = existing_folder(ctx, args.folder)
    dest_dir = existing_folder(ctx, args.save_in, write=True) if args.save_in else src.parent
    out = unique_path(dest_dir / safe_file_name(args.file_name or f"{src.name} {datetime.now():%Y-%m-%d}", ".zip"))
    ctx.policy.check_path(out, write=True)
    if out.resolve().is_relative_to(src.resolve()):
        raise ToolError("Save the archive outside the folder being packed.")

    def work():
        files = [p for p in src.rglob("*") if p.is_file()]
        with zipfile.ZipFile(out, "x", zipfile.ZIP_DEFLATED) as z:
            for p in files:
                z.write(p, str(Path(src.name) / p.relative_to(src)))
        with zipfile.ZipFile(out) as z:
            bad = z.testzip()
            return len(files), len(z.namelist()), bad

    n, inside, bad = await asyncio.to_thread(work)
    ok = bad is None and inside == n
    ctx.memory.outputs.append({"path": str(out), "kind": "archive", "verified": ok, "note": ""})
    return ToolResult(ok, f"Packed {n} file(s) from {src.name} into {out.name} ({out.stat().st_size / 2**20:,.1f} MB). Reopened it: "
                          f"{inside} files, " + ("every file's checksum is right." if bad is None else f"damaged at {bad}.")
                          + " The original folder is untouched.", {"path": str(out), "files": n}, verified=ok)


def register_os_tools(reg: ToolRegistry) -> None:
    D, F, R, W = Capability.DESKTOP, Capability.FILES, RiskLevel.READ_ONLY, RiskLevel.LOCAL_WRITE
    reg.register(ToolSpec("list_startup_apps", "List programs that start automatically.", D, R, NoArgs, list_startup_apps))
    reg.register(ToolSpec("top_memory", "List the programs using the most memory.", D, R, NoArgs, top_memory))
    reg.register(ToolSpec("find_broken_shortcuts", "Find shortcuts whose target is missing.", F, R, ShortcutArgs, find_broken_shortcuts))
    reg.register(ToolSpec("rename_many", "Rename many files with a pattern; never overwrites.", F, W, RenameManyArgs, rename_many,
                          precheck=check_rename_many))
    reg.register(ToolSpec("archive_folder", "Pack a folder into a checked .zip.", F, W, ArchiveArgs, archive_folder))
