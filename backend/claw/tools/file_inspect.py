"""Read-only file tools, limited to folders the user authorized."""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime
from pathlib import Path

from pydantic import Field

from claw.agent.schemas import Capability
from claw.documents.readers import read_document
from claw.permissions.policy import PathNotAuthorized, RiskLevel
from claw.tools.file_tools import existing_folder
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
    folder = existing_folder(ctx, args.folder)
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
    ctx.memory.note_file(path)
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
    not_modified_in_days: int | None = Field(
        default=None, ge=1, le=36500,
        description="Only files untouched for at least this many days, e.g. 30 for old files")
    modified_in_days: int | None = Field(
        default=None, ge=1, le=36500,
        description="Only files changed within this many days, e.g. 7 for this week's files")
    modified_from: str | None = Field(default=None, max_length=10, description="First day, YYYY-MM-DD")
    modified_to: str | None = Field(default=None, max_length=10, description="Last day, YYYY-MM-DD")


async def find_files(args: FindArgs, ctx: ToolContext) -> ToolResult:
    root = existing_folder(ctx, args.folder) if args.folder else _authorized(ctx, args.folder)
    ext = (args.extension or "").lower()
    if ext and not ext.startswith("."):
        ext = "." + ext
    needle = args.name_contains.lower()
    # One clock reading for the whole walk, so a long scan cannot move the cut-off
    # under its own feet and report a file on both sides of it.
    now = time.time()
    older_than = now - args.not_modified_in_days * 86400 if args.not_modified_in_days else None
    newer_than = now - args.modified_in_days * 86400 if args.modified_in_days else None
    # A date range ("modified in March 2026"): baseline benchmark, the brain had no way to say it.
    import datetime as _dt  # noqa: PLC0415
    try:
        lo = _dt.datetime.strptime(args.modified_from, "%Y-%m-%d").timestamp() if args.modified_from else None
        hi = (_dt.datetime.strptime(args.modified_to, "%Y-%m-%d") + _dt.timedelta(days=1)).timestamp() if args.modified_to else None
    except ValueError as exc:
        raise ToolError("Dates must look like 2026-03-01.") from exc
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
            if older_than is not None and st.st_mtime > older_than:
                continue
            if newer_than is not None and st.st_mtime < newer_than:
                continue
            if (lo is not None and st.st_mtime < lo) or (hi is not None and st.st_mtime >= hi):
                continue
            hits.append({"path": str(p), "size": st.st_size, "modified": st.st_mtime})
        if scanned > 50000:
            break
    hits.sort(key=lambda h: -h["modified"] if args.newest_first else h["path"])
    hits = hits[:100]
    for h in hits:
        h["modified"] = _when(h["modified"])
    text = "\n".join(f"- {h['path']}  {h['size']:,} bytes  {h['modified']}" for h in hits)
    window = ""
    if args.not_modified_in_days:
        window = f", not changed in {args.not_modified_in_days} day(s)"
    elif args.modified_in_days:
        window = f", changed in the last {args.modified_in_days} day(s)"
    if args.modified_from or args.modified_to:
        window += f", changed between {args.modified_from or 'the start'} and {args.modified_to or 'today'}"
    return ToolResult(True, f"Found {len(hits)} file(s) under {root}{window}.",
                      {"files": hits, "scanned": scanned}, True, text)


class DupArgs(ToolArgs):
    folder: str = Field(min_length=1, max_length=500, description="Folder name or path")
    include_subfolders: bool = True


async def find_duplicate_files(args: DupArgs, ctx: ToolContext) -> ToolResult:
    """Files with the same content (SHA-256), whatever their names. Read-only."""
    root = existing_folder(ctx, args.folder)

    def work():
        import hashlib  # noqa: PLC0415
        by_size: dict[int, list[Path]] = {}
        files = root.rglob("*") if args.include_subfolders else root.glob("*")
        for p in files:
            if p.is_file() and not p.name.startswith("."):
                by_size.setdefault(p.stat().st_size, []).append(p)
        groups: dict[str, list[Path]] = {}
        for same in (v for v in by_size.values() if len(v) > 1):   # only equal sizes can be equal
            for p in same:
                h = hashlib.sha256()
                with open(p, "rb") as fh:
                    for chunk in iter(lambda: fh.read(1 << 20), b""):
                        h.update(chunk)
                groups.setdefault(h.hexdigest(), []).append(p)
        return [sorted(g) for g in groups.values() if len(g) > 1]

    groups = await asyncio.to_thread(work)
    for g in groups:
        for p in g:
            ctx.memory.note_file(p)
    if not groups:
        return ToolResult(True, f"No duplicate files in {root}: every file's content is different.", {"groups": []}, True)
    lines = [" = ".join(str(p.relative_to(root)) for p in g) + f"  ({g[0].stat().st_size:,} bytes each)" for g in groups]
    return ToolResult(True, f"{len(groups)} set(s) of files with identical content in {root}: " + "; ".join(lines),
                      {"groups": [[str(p) for p in g] for g in groups]}, True, "\n".join(lines))


class CompareFoldersArgs(ToolArgs):
    first: str = Field(min_length=1, max_length=500, description="e.g. the old version's folder")
    second: str = Field(min_length=1, max_length=500)


async def compare_folders(args: CompareFoldersArgs, ctx: ToolContext) -> ToolResult:
    """Which files are only in one folder, and which are in both but different (by content). Read-only."""
    a, b = existing_folder(ctx, args.first), existing_folder(ctx, args.second)

    def work():
        import hashlib  # noqa: PLC0415

        def index(root: Path):
            return {str(p.relative_to(root)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in root.rglob("*") if p.is_file()}
        return index(a), index(b)

    ia, ib = await asyncio.to_thread(work)
    only_a = sorted(set(ia) - set(ib))
    only_b = sorted(set(ib) - set(ia))
    changed = sorted(k for k in set(ia) & set(ib) if ia[k] != ib[k])
    same = len(set(ia) & set(ib)) - len(changed)
    parts = [f"Missing from {b.name}: {', '.join(only_a) or 'none'}",
             f"Only in {b.name}: {', '.join(only_b) or 'none'}",
             f"Changed: {', '.join(changed) or 'none'}", f"Identical: {same}"]
    return ToolResult(True, f"Compared {a.name} with {b.name}. " + ". ".join(parts) + ".",
                      {"missing_from_second": only_a, "only_in_second": only_b, "changed": changed, "identical": same}, True)


def register_file_inspect_tools(reg: ToolRegistry) -> None:
    F, R = Capability.FILES, RiskLevel.READ_ONLY
    reg.register(ToolSpec("list_folder", "List what is in an authorized folder.", F, R, FolderArgs, list_folder))
    reg.register(ToolSpec("read_file", "Read a file: text, PDF (scanned pages are read with OCR), Word (.docx) or Excel (.xlsx).", F, R, ReadArgs, read_file))
    reg.register(ToolSpec("find_duplicate_files", "Find files with identical content in a folder, whatever their names.", F, R, DupArgs, find_duplicate_files))
    reg.register(ToolSpec("compare_folders", "List files missing, added or changed between two folders.", F, R, CompareFoldersArgs, compare_folders))
    reg.register(ToolSpec("find_files", "Find files by name, type or age inside authorized folders, newest first.", F, R, FindArgs, find_files))
