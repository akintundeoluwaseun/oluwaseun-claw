"""Read-only file tools, limited to folders the user authorized."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime
from pathlib import Path

from pydantic import Field

from claw.agent.schemas import Capability
from claw.documents.readers import read_document
from claw.permissions.policy import PathNotAuthorized, RiskLevel
from claw.tools.base import ToolArgs, ToolContext, ToolError, ToolRegistry, ToolResult, ToolSpec

SKIP_DIRS = {"node_modules", ".git", "__pycache__", "$recycle.bin", "system volume information", "appdata"}


def _authorized(ctx: ToolContext, path: str | None) -> Path:
    roots = ctx.settings.permissions.authorized_folders
    if path is None and not roots:
        raise ToolError("No folders are authorized. Add one in Settings → Folders Claw may use.")
    try:
        return ctx.policy.check_path(path or roots[0])
    except PathNotAuthorized as exc:
        raise ToolError(str(exc)) from exc


def _when(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


class FolderArgs(ToolArgs):
    folder: str | None = Field(default=None, max_length=500, description="An authorized folder or a folder inside one")


async def list_folder(args: FolderArgs, ctx: ToolContext) -> ToolResult:
    folder = _authorized(ctx, args.folder)
    if not folder.is_dir():
        raise ToolError(f"'{folder}' is not a folder.")
    entries = []
    with os.scandir(folder) as it:
        for e in it:
            if e.name.startswith(".") or len(entries) >= 300:
                continue
            try:
                st = e.stat()
            except OSError:
                continue
            entries.append({"name": e.name, "folder": e.is_dir(), "size": st.st_size if e.is_file() else None, "modified": _when(st.st_mtime)})
    entries.sort(key=lambda x: (not x["folder"], x["name"].lower()))
    text = "\n".join(
        f"- {x['name']}{'/' if x['folder'] else ''}" + ("" if x["folder"] else f"  {x['size']:,} bytes") + f"  {x['modified']}"
        for x in entries
    )
    return ToolResult(True, f"{len(entries)} item(s) in {folder}.", {"folder": str(folder), "entries": entries}, True, text)


class ReadArgs(ToolArgs):
    path: str = Field(min_length=1, max_length=500)
    max_chars: int = Field(default=20000, ge=100, le=100000)


async def read_file(args: ReadArgs, ctx: ToolContext) -> ToolResult:
    path = _authorized(ctx, args.path)
    if not path.is_file():
        raise ToolError(f"'{path}' is not a file.")
    ctx.memory.seen_files.add(str(path))
    if path.suffix.lower() == ".pdf":
        from claw.tools.pdf_tools import read_pdf_overview

        return await read_pdf_overview(path, ctx, args.max_chars)
    text = await asyncio.to_thread(read_document, path)
    cut = len(text) > args.max_chars
    return ToolResult(True, f"Read {path.name} ({len(text):,} characters{', first part only' if cut else ''}).",
                      {"path": str(path), "chars": len(text), "truncated": cut}, True, untrusted_text=text[: args.max_chars])


class FindArgs(ToolArgs):
    name_contains: str = Field(default="", max_length=100, description="Part of the file name")
    extension: str | None = Field(default=None, max_length=10, description="e.g. .pdf")
    folder: str | None = Field(default=None, max_length=500)
    newest_first: bool = True


async def find_files(args: FindArgs, ctx: ToolContext) -> ToolResult:
    root = _authorized(ctx, args.folder)
    ext = (args.extension or "").lower()
    if ext and not ext.startswith("."):
        ext = "." + ext
    needle = args.name_contains.lower()
    hits, scanned = [], 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIRS and not d.startswith(".")]
        if Path(dirpath).relative_to(root).parts.__len__() > 8:
            dirnames[:] = []
        for f in filenames:
            scanned += 1
            if needle and needle not in f.lower():
                continue
            if ext and not f.lower().endswith(ext):
                continue
            p = Path(dirpath) / f
            try:
                st = p.stat()
            except OSError:
                continue
            hits.append({"path": str(p), "size": st.st_size, "modified": st.st_mtime})
        if scanned > 50000:
            break
    hits.sort(key=lambda h: -h["modified"] if args.newest_first else h["path"])
    hits = hits[:100]
    for h in hits:
        h["modified"] = _when(h["modified"])
    text = "\n".join(f"- {h['path']}  {h['size']:,} bytes  {h['modified']}" for h in hits)
    return ToolResult(True, f"Found {len(hits)} file(s) under {root}.", {"files": hits, "scanned": scanned}, True, text)


def register_file_inspect_tools(reg: ToolRegistry) -> None:
    F, R = Capability.FILES, RiskLevel.READ_ONLY
    reg.register(ToolSpec("list_folder", "List what is in an authorized folder.", F, R, FolderArgs, list_folder))
    reg.register(ToolSpec("read_file", "Read a file: text, PDF (scanned pages are read with OCR), Word (.docx) or Excel (.xlsx).", F, R, ReadArgs, read_file))
    reg.register(ToolSpec("find_files", "Find files by name or type inside authorized folders, newest first.", F, R, FindArgs, find_files))
