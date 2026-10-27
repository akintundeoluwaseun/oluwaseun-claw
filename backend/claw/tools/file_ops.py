"""File operations: copy and organise files, and check a file's exact contents.

Copies never move, rename or delete originals, never overwrite (new names get
" (2)" etc.), stay inside authorized folders, and are checked byte-for-byte.
"""

from __future__ import annotations

import asyncio
import fnmatch
import hashlib
import os
import re
import shutil
from pathlib import Path, PureWindowsPath

from pydantic import Field, field_validator

from claw.agent.schemas import Capability
from claw.documents.readers import read_document
from claw.permissions.policy import PathNotAuthorized, RiskLevel
from claw.tools.base import ToolArgs, ToolContext, ToolError, ToolRegistry, ToolResult, ToolSpec
from claw.tools.file_tools import unique_path

MAX_COPY_FILES = 500
# Renaming a document into one of these would turn it into something Windows runs.
RISKY_EXTS = {".exe", ".bat", ".cmd", ".com", ".scr", ".ps1", ".psm1", ".vbs", ".vbe",
              ".js", ".jse", ".wsf", ".wsh", ".msi", ".msp", ".hta", ".cpl", ".jar",
              ".reg", ".lnk", ".pif", ".dll", ".sys"}

MAX_COPY_BYTES = 2 * 1024**3
# Common names Windows gives screenshots, in English Windows and the Snipping Tool.
SCREENSHOT_HINTS = ("screenshot", "screen shot", "capture", "snip")
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}


def _check(ctx: ToolContext, raw: str, write: bool = False) -> Path:
    try:
        return ctx.policy.check_path(raw, write=write)
    except PathNotAuthorized as exc:
        raise ToolError(str(exc)) from exc


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# ---------- copy_files ----------
class CopyArgs(ToolArgs):
    source_folder: str = Field(min_length=1, max_length=500)
    pattern: str = Field(default="*", max_length=100, description='File name pattern, e.g. "*.png" or "*invoice*"')
    only_screenshots: bool = Field(default=False, description="Only image files named like screenshots")
    destination_folder: str = Field(min_length=1, max_length=500,
                                    description="Folder to copy into (created if missing); a plain name means a new folder inside the source folder")
    include_subfolders: bool = False

    @field_validator("pattern")
    @classmethod
    def _no_paths(cls, v: str) -> str:
        if any(c in v for c in "/\\") or ".." in v:
            raise ValueError("the pattern must be a file name pattern, not a path")
        return v


def _select(args: CopyArgs, src: Path, dest: Path) -> list[Path]:
    files: list[Path] = []
    walker = os.walk(src) if args.include_subfolders else [(str(src), [], os.listdir(src))]
    for dirpath, dirnames, names in walker:
        if Path(dirpath).resolve() == dest.resolve() or dest.resolve() in Path(dirpath).resolve().parents:
            dirnames[:] = []
            continue
        for n in sorted(names):
            p = Path(dirpath) / n
            if not p.is_file() or not fnmatch.fnmatch(n.lower(), args.pattern.lower()):
                continue
            if args.only_screenshots and not (p.suffix.lower() in IMAGE_EXT and any(h in n.lower() for h in SCREENSHOT_HINTS)):
                continue
            files.append(p)
    return files


def _dest(args: CopyArgs, ctx: ToolContext, src: Path) -> Path:
    raw = args.destination_folder
    if not (Path(raw).is_absolute() or PureWindowsPath(raw).is_absolute()):
        raw = str(src / raw)
    return _check(ctx, raw, write=True)


def check_copy(args: CopyArgs, ctx: ToolContext) -> None:
    src = _check(ctx, args.source_folder)
    if not src.is_dir():
        raise ToolError(f"'{src}' is not a folder.")
    _dest(args, ctx, src)


async def copy_files(args: CopyArgs, ctx: ToolContext) -> ToolResult:
    src = _check(ctx, args.source_folder)
    dest = _dest(args, ctx, src)
    files = await asyncio.to_thread(_select, args, src, dest)
    if not files:
        return ToolResult(True, f"No files in {src} match '{args.pattern}'" + (" and look like screenshots" if args.only_screenshots else "") + ". Nothing copied.",
                          {"copied": []}, verified=True)
    if len(files) > MAX_COPY_FILES:
        raise ToolError(f"{len(files)} files match; Claw copies at most {MAX_COPY_FILES} at a time. Narrow the pattern.")
    total = sum(f.stat().st_size for f in files)
    if total > MAX_COPY_BYTES:
        raise ToolError(f"Those files add up to {total / 1024**3:.1f} GB; Claw copies at most 2 GB at a time.")
    existing = dest
    while not existing.exists() and existing != existing.parent:
        existing = existing.parent
    free = shutil.disk_usage(existing).free
    if free < total + 50 * 1024**2:
        raise ToolError(f"Not enough free disk space: {total / 1024**2:.0f} MB needed, {free / 1024**2:.0f} MB free.")
    dest.mkdir(parents=True, exist_ok=True)

    def work():
        done, bad = [], []
        for f in files:
            target = unique_path(dest / f.name)
            _check(ctx, str(target), write=True)
            with open(f, "rb") as r, open(target, "xb") as w:  # "x": never overwrite
                shutil.copyfileobj(r, w, 1 << 20)
            shutil.copystat(f, target)
            (done if _sha(f) == _sha(target) else bad).append({"from": str(f), "to": str(target)})
        return done, bad

    done, bad = await asyncio.to_thread(work)
    for d in done:
        ctx.memory.outputs.append({"path": d["to"], "kind": "copy", "verified": True, "note": ""})
    text = "\n".join(f"- {d['from']} → {d['to']}" for d in done[:50])
    msg = f"Copied {len(done)} file(s) into {dest} and checked each copy matches its original."
    if bad:
        msg += f" {len(bad)} copy(ies) did NOT match and should not be trusted."
    return ToolResult(not bad, msg, {"copied": done, "mismatched": bad, "destination": str(dest)},
                      verified=not bad, untrusted_text=text)


# ---------- check_file ----------
class CheckFileArgs(ToolArgs):
    path: str = Field(min_length=1, max_length=500)
    expected_text: str = Field(max_length=20000, description="The exact text the file should contain")
    exact: bool = Field(default=True, description="True: the whole file must equal the text; False: it must contain it")


async def check_file(args: CheckFileArgs, ctx: ToolContext) -> ToolResult:
    path = _check(ctx, args.path)
    if not path.is_file():
        return ToolResult(False, f"There is no file at {path}.", {"path": str(path), "exists": False}, verified=True)
    text = await asyncio.to_thread(read_document, path)
    # Notepad and other editors may add a final newline or a byte-order mark; those are not content.
    body = text.lstrip("﻿").replace("\r\n", "\n")
    want = args.expected_text.replace("\r\n", "\n")
    match = body.rstrip("\n") == want.rstrip("\n") if args.exact else want in body
    ctx.memory.note_file(path)
    if match:
        return ToolResult(True, f"Checked {path.name}: its contents match exactly." if args.exact else f"Checked {path.name}: it contains the text.",
                          {"path": str(path), "match": True}, verified=True)
    preview = body[:200].replace("\n", "\\n")
    return ToolResult(False, f"{path.name} exists but its contents do not match. It starts with: \"{preview}\"",
                      {"path": str(path), "match": False, "chars": len(body)}, verified=True)


# ---------- create_folder ----------
# A name, never a path: a folder is made inside a folder the user authorised, and
# "..\\elsewhere" or "C:\\Windows" is rejected rather than quietly resolved.
_BAD_NAME = re.compile(r"[^A-Za-z0-9 ._()-]+")
_RESERVED_NAMES = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
                   *(f"lpt{i}" for i in range(1, 10))}


def clean_folder_name(raw: str) -> str:
    # Refuse a path rather than quietly stripping it: "../../escaped" would otherwise
    # become a folder called "escaped" here, which is not what was asked for even
    # though it stays inside the authorized folder.
    if any(sep in raw for sep in ("/", "\\")) or Path(raw).name != raw.strip():
        raise ToolError("Give a folder name, not a path. Claw creates it inside a folder you authorized.")
    name = _BAD_NAME.sub("", Path(raw).name).strip(" .")[:80]
    if not name:
        raise ToolError("That folder name has no usable characters in it.")
    if name.lower() in _RESERVED_NAMES:
        raise ToolError(f"'{name}' is a name Windows reserves. Choose another.")
    return name


class NewFolderArgs(ToolArgs):
    folder_name: str = Field(min_length=1, max_length=100, description='A plain name, e.g. "Claw Test"')
    inside: str | None = Field(default=None, max_length=500,
                               description="An authorized folder; defaults to the first one")


def check_new_folder(args: NewFolderArgs, ctx: ToolContext) -> None:
    clean_folder_name(args.folder_name)
    _parent(ctx, args.inside)


def _parent(ctx: ToolContext, inside: str | None) -> Path:
    roots = ctx.policy.authorized_roots
    if not roots:
        raise ToolError("No folders are authorized. Add a folder in Settings so Claw can create one.")
    parent = _check(ctx, inside or str(roots[0]), write=True)
    if not parent.is_dir():
        raise ToolError(f"The folder '{parent}' does not exist.")
    return parent


async def create_folder(args: NewFolderArgs, ctx: ToolContext) -> ToolResult:
    parent = _parent(ctx, args.inside)
    name = clean_folder_name(args.folder_name)
    target = _check(ctx, str(parent / name), write=True)  # re-check the final path
    existed = target.is_dir()
    if target.exists() and not existed:
        raise ToolError(f"'{name}' already exists here and is a file, not a folder.")
    target.mkdir(parents=True, exist_ok=True)
    made = target.is_dir()
    summary = (f"'{name}' was already there." if existed
               else f"Created the folder '{name}' in {parent}.")
    return ToolResult(made, summary, {"path": str(target), "created": made and not existed,
                                      "already_existed": existed}, verified=made)


# ---------- rename_file ----------
class RenameArgs(ToolArgs):
    path: str = Field(min_length=1, max_length=500, description="The file to rename")
    new_name: str = Field(min_length=1, max_length=100,
                          description='The new name, e.g. "hello-test.txt". Not a path.')


def _new_name(raw: str, old: Path) -> str:
    if any(sep in raw for sep in ("/", "\\")) or Path(raw).name != raw:
        raise ToolError("Give a new name, not a path. Claw renames a file where it already is.")
    name = _BAD_NAME.sub("", Path(raw).name).strip(" .")[:100]
    if not name:
        raise ToolError("That file name has no usable characters in it.")
    if Path(name).stem.lower() in _RESERVED_NAMES:
        raise ToolError(f"'{name}' is a name Windows reserves. Choose another.")
    new_ext = Path(name).suffix.lower()
    if not new_ext:
        name += old.suffix  # keep the kind of file it is rather than leaving it with none
        new_ext = old.suffix.lower()
    if new_ext in RISKY_EXTS:
        raise ToolError(f"Claw will not rename a file to '{new_ext}': that would make it a program.")
    return name


def check_rename(args: RenameArgs, ctx: ToolContext) -> None:
    path = _check(ctx, args.path, write=True)
    _new_name(args.new_name, path)


async def rename_file(args: RenameArgs, ctx: ToolContext) -> ToolResult:
    path = _check(ctx, args.path, write=True)
    if not path.is_file():
        raise ToolError(f"'{path}' is not a file.")
    name = _new_name(args.new_name, path)
    target = _check(ctx, str(path.parent / name), write=True)  # re-check the final path
    if target == path:
        return ToolResult(True, f"'{path.name}' already has that name.",
                          {"path": str(path), "renamed": False}, verified=True)
    if target.exists():
        # Never overwrite. The user can delete or choose another name themselves.
        raise ToolError(f"'{name}' already exists in that folder. Nothing was renamed.")
    before = path.read_bytes()
    path.rename(target)
    # Verify rather than trust: the new name is there, the old one is gone, and the
    # contents came through byte for byte.
    same = target.is_file() and not path.exists() and target.read_bytes() == before
    ctx.memory.note_file(target)
    return ToolResult(
        same,
        f"Renamed '{path.name}' to '{name}'. Its contents are unchanged." if same
        else f"Renamed '{path.name}' to '{name}', but the result could not be verified.",
        {"path": str(target), "previous_path": str(path), "renamed": True,
         "bytes": len(before)},
        verified=same,
    )


# ---------- move_file ----------
class MoveArgs(ToolArgs):
    path: str = Field(min_length=1, max_length=500, description="The file to move")
    destination_folder: str = Field(min_length=1, max_length=500,
                                    description="An authorized folder to move it into")


def check_move(args: MoveArgs, ctx: ToolContext) -> None:
    _check(ctx, args.path, write=True)
    _check(ctx, args.destination_folder, write=True)


async def move_file(args: MoveArgs, ctx: ToolContext) -> ToolResult:
    path = _check(ctx, args.path, write=True)
    if not path.is_file():
        raise ToolError(f"'{path}' is not a file.")
    dest_dir = _check(ctx, args.destination_folder, write=True)
    if not dest_dir.is_dir():
        raise ToolError(f"The folder '{dest_dir}' does not exist.")
    target = _check(ctx, str(dest_dir / path.name), write=True)
    if target == path:
        return ToolResult(True, f"'{path.name}' is already in that folder.",
                          {"path": str(path), "moved": False}, verified=True)
    if target.exists():
        # Never overwrite. Moving is not a reason to lose the file that is already there.
        raise ToolError(f"'{path.name}' already exists in that folder. Nothing was moved.")
    before = path.read_bytes()
    try:
        shutil.move(str(path), str(target))      # handles a move across drives too
    except OSError as exc:
        raise ToolError(f"The file could not be moved: {exc.strerror}") from exc
    same = target.is_file() and not path.exists() and target.read_bytes() == before
    ctx.memory.note_file(target)
    return ToolResult(
        same,
        f"Moved '{path.name}' into {dest_dir.name}. Its contents are unchanged." if same
        else f"Moved '{path.name}', but the result could not be verified.",
        {"path": str(target), "previous_path": str(path), "moved": True, "bytes": len(before)},
        verified=same,
    )


def register_file_ops(reg: ToolRegistry) -> None:
    F = Capability.FILES
    reg.register(ToolSpec("copy_files",
                          "Copy files (by name pattern, or only screenshots) from one folder into another; originals untouched, never overwrites.",
                          F, RiskLevel.LOCAL_WRITE, CopyArgs, copy_files, precheck=check_copy))
    reg.register(ToolSpec("check_file", "Reopen a file and check that it contains exactly the expected text.",
                          F, RiskLevel.READ_ONLY, CheckFileArgs, check_file))
    reg.register(ToolSpec("create_folder", "Create a new folder inside an authorized folder.",
                          F, RiskLevel.LOCAL_WRITE, NewFolderArgs, create_folder, precheck=check_new_folder))
    reg.register(ToolSpec("rename_file", "Rename a file where it is; never overwrites an existing file.",
                          F, RiskLevel.LOCAL_WRITE, RenameArgs, rename_file, precheck=check_rename))
    reg.register(ToolSpec("move_file", "Move a file into another authorized folder; never overwrites.",
                          F, RiskLevel.LOCAL_WRITE, MoveArgs, move_file, precheck=check_move))
