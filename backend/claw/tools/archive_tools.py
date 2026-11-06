"""Opening an archive somebody sent you.

Claw could pack a folder into a .zip and could not open one. A supplier
sends a zip of photos, a bank sends statements in one, a designer sends the
artwork that way, and the answer was to go and do it by hand.

An archive is UNTRUSTED. It was made somewhere else, by someone else, and
the names inside it are data, not instructions. Two things go wrong when a
program forgets that, and both are guarded here:

  Path traversal ("zip slip"). An entry named "../../../.ssh/authorized_keys"
  or "C:\\Windows\\System32\\x.dll" writes outside the folder being extracted
  into - outside every folder the person authorized - if the name is joined
  to the destination without checking where it lands. Every entry here is
  resolved and must end up inside the destination, and a symlink entry is
  refused outright, because a link can point anywhere and the file written
  through it afterwards lands there.

  Decompression bombs. A few hundred kilobytes can expand to many gigabytes
  and fill the disk. The declared total is checked before anything is
  written, and the running total is checked again while writing, because the
  declared size is also just data from the file.

Nothing here overwrites: everything goes into a NEW folder.
"""

from __future__ import annotations

import asyncio
import tarfile
import zipfile
from pathlib import Path

from pydantic import Field

from claw.agent.schemas import Capability
from claw.permissions.policy import PathNotAuthorized, RiskLevel
from claw.tools.base import ToolArgs, ToolContext, ToolError, ToolRegistry, ToolResult, ToolSpec
from claw.tools.file_tools import existing_folder, safe_file_name, unique_path

#: Formats Python can open without anything extra installed. .rar and .7z are
#: deliberately absent: they need a separate program, and saying so is better
#: than failing in the middle.
ZIP_SUFFIXES = (".zip",)
TAR_SUFFIXES = (".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz")
NEEDS_ANOTHER_PROGRAM = (".rar", ".7z", ".iso", ".dmg")

#: Total unpacked size Claw will write from one archive.
MAX_UNPACKED_BYTES = 2 * 1024**3        # 2 GB
#: How much bigger than the archive the contents may be before it looks like
#: a bomb rather than a folder of documents. Text compresses about 5:1, so 200
#: is far past anything honest.
MAX_RATIO = 200
MAX_ENTRIES = 20_000


def _kind(path: Path) -> str:
    name = path.name.lower()
    # The name is checked first only to give a better message for the formats
    # Claw cannot open. What it IS is decided by the bytes: a file called
    # .zip that is not one must say so plainly, not fail somewhere inside
    # zipfile with "File is not a zip file".
    if name.endswith(NEEDS_ANOTHER_PROGRAM):
        raise ToolError(
            f"{path.name} is a {path.suffix.lstrip('.').upper()} archive. Claw can open .zip and "
            ".tar files; this one needs a separate program such as 7-Zip, which is not installed.")
    if zipfile.is_zipfile(path):
        return "zip"
    try:
        if tarfile.is_tarfile(path):
            return "tar"
    except (OSError, tarfile.TarError):
        pass
    looks_like = " It is named like one, but the file itself is not." if (
        name.endswith(ZIP_SUFFIXES) or name.endswith(TAR_SUFFIXES)) else ""
    raise ToolError(f"{path.name} is not an archive Claw can open.{looks_like}")


def find_archive(ctx: ToolContext, raw: str, near: str | None = None) -> Path:
    try:
        p = ctx.policy.check_path(raw)
        if p.is_file():
            return p
    except PathNotAuthorized:
        pass
    name = Path(str(raw).replace("\\", "/")).name.lower()
    bases = ([existing_folder(ctx, near)] if near
             else [Path(r) for r in ctx.settings.permissions.authorized_folders])
    hits = list(dict.fromkeys(q for b in bases if b.is_dir() for q in b.rglob("*")
                              if q.is_file() and q.name.lower() == name))
    if len(hits) == 1:
        return ctx.policy.check_path(str(hits[0]))
    if len(hits) > 1:
        raise ToolError(f"There are {len(hits)} files called '{name}'. Give the full path or the folder.")
    raise ToolError(f"There is no file '{raw}' in the authorized folders.")


class Entry:
    """One thing inside an archive, as the archive describes it."""

    __slots__ = ("name", "size", "is_dir", "is_link")

    def __init__(self, name: str, size: int, is_dir: bool, is_link: bool = False):
        self.name, self.size, self.is_dir, self.is_link = name, size, is_dir, is_link


def _entries(path: Path, kind: str) -> list[Entry]:
    out: list[Entry] = []
    if kind == "zip":
        with zipfile.ZipFile(path) as z:
            for info in z.infolist():
                # The high bits of external_attr hold the Unix mode; 0xA000 is
                # a symlink. zipfile will happily write its target as content,
                # but we refuse the entry rather than reason about it.
                mode = info.external_attr >> 16
                out.append(Entry(info.filename, info.file_size, info.is_dir(),
                                 (mode & 0o170000) == 0o120000))
    else:
        with tarfile.open(path) as t:
            for info in t.getmembers():
                if not (info.isfile() or info.isdir() or info.issym() or info.islnk()):
                    continue        # devices, fifos: not something a person sent on purpose
                out.append(Entry(info.name, info.size, info.isdir(), info.issym() or info.islnk()))
    if len(out) > MAX_ENTRIES:
        raise ToolError(f"{path.name} holds {len(out):,} items, which is more than Claw will unpack at once.")
    return out


def safe_target(destination: Path, name: str) -> Path:
    """Where this entry is allowed to land, or an error.

    The name inside an archive is written by whoever made it. Joining it to a
    folder and trusting the result is how a zip writes over files it was
    never given access to.
    """
    cleaned = name.replace("\\", "/")
    if cleaned.startswith("/") or (len(cleaned) > 1 and cleaned[1] == ":"):
        raise ToolError(f"The archive contains an absolute path ('{name[:60]}'), which Claw will not unpack.")
    target = (destination / cleaned).resolve()
    root = destination.resolve()
    if target != root and root not in target.parents:
        raise ToolError(f"The archive contains a path that points outside the folder ('{name[:60]}'), "
                        "which Claw will not unpack.")
    return target


def _check_sizes(path: Path, entries: list[Entry]) -> int:
    declared = sum(e.size for e in entries if not e.is_dir)
    packed = max(path.stat().st_size, 1)
    if declared > MAX_UNPACKED_BYTES:
        raise ToolError(f"{path.name} unpacks to about {declared / 2**30:,.1f} GB, which is more than "
                        "Claw will write at once.")
    if declared / packed > MAX_RATIO and declared > 50 * 1024**2:
        raise ToolError(f"{path.name} is {packed / 2**20:,.1f} MB but claims to unpack to "
                        f"{declared / 2**30:,.1f} GB. That is not a normal archive, so Claw has not opened it.")
    return declared


# ---------- look inside without unpacking ----------
class PeekArgs(ToolArgs):
    path: str = Field(min_length=1, max_length=500)
    folder: str | None = Field(default=None, max_length=500)


async def look_inside_archive(args: PeekArgs, ctx: ToolContext) -> ToolResult:
    src = find_archive(ctx, args.path, args.folder)

    def work():
        kind = _kind(src)
        entries = _entries(src, kind)
        return kind, entries

    kind, entries = await asyncio.to_thread(work)
    files = [e for e in entries if not e.is_dir]
    total = sum(e.size for e in files)
    by_type: dict[str, int] = {}
    for e in files:
        by_type[(Path(e.name).suffix.lower() or "no extension")] = by_type.get(
            Path(e.name).suffix.lower() or "no extension", 0) + 1
    kinds = ", ".join(f"{n} {ext}" for ext, n in sorted(by_type.items(), key=lambda kv: -kv[1])[:6])
    names = "; ".join(Path(e.name).name for e in files[:8])
    risky = [e.name for e in entries if e.is_link]
    note = f" {len(risky)} entry(ies) are links and would be skipped." if risky else ""
    ctx.memory.note_file(src)
    return ToolResult(
        True,
        f"{src.name} is a {kind} holding {len(files)} file(s), {total / 2**20:,.1f} MB unpacked"
        + (f" ({kinds})" if kinds else "") + (f". First: {names}" if names else "")
        + ("..." if len(files) > 8 else "") + note + " Nothing was unpacked.",
        {"path": str(src), "kind": kind, "files": len(files), "unpacked_bytes": total,
         "names": [e.name for e in files[:200]]},
        verified=True)


# ---------- unpack ----------
class OpenArgs(ToolArgs):
    path: str = Field(min_length=1, max_length=500)
    folder: str | None = Field(default=None, max_length=500)
    into: str | None = Field(default=None, max_length=500, description="Where to put the new folder")
    only: str = Field(default="", max_length=100,
                      description='Only files matching this, e.g. "*.pdf"')


async def open_archive(args: OpenArgs, ctx: ToolContext) -> ToolResult:
    import fnmatch  # noqa: PLC0415

    src = find_archive(ctx, args.path, args.folder)
    base = existing_folder(ctx, args.into, write=True) if args.into else src.parent
    dest = unique_path(base / safe_file_name(src.name.split(".")[0] or "unpacked", ""))
    ctx.policy.check_path(dest, write=True)

    def work():
        kind = _kind(src)
        entries = _entries(src, kind)
        _check_sizes(src, entries)

        wanted = [e for e in entries if not e.is_dir and not e.is_link]
        if args.only:
            wanted = [e for e in wanted if fnmatch.fnmatch(Path(e.name).name.lower(), args.only.lower())]
            if not wanted:
                raise ToolError(f"Nothing in {src.name} matches '{args.only}'.")
        # Every destination is checked BEFORE a single byte is written, so a
        # bad entry halfway through cannot leave a half-unpacked folder.
        targets = [(e, safe_target(dest, e.name)) for e in wanted]

        dest.mkdir(parents=True, exist_ok=True)
        written, total = [], 0
        if kind == "zip":
            with zipfile.ZipFile(src) as z:
                for entry, target in targets:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(entry.name) as fh, open(target, "wb") as out:
                        total += _copy(fh, out, total)
                    written.append(target)
        else:
            with tarfile.open(src) as t:
                for entry, target in targets:
                    member = t.getmember(entry.name)
                    fh = t.extractfile(member)
                    if fh is None:
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with fh, open(target, "wb") as out:
                        total += _copy(fh, out, total)
                    written.append(target)
        skipped = len([e for e in entries if e.is_link])
        return written, total, skipped, len(entries)

    written, total, skipped, inside = await asyncio.to_thread(work)
    # The check: count what is actually on the disk now, not what was intended.
    on_disk = [p for p in dest.rglob("*") if p.is_file()]
    ok = len(on_disk) == len(written)
    ctx.memory.note_file(src)
    ctx.memory.outputs.append({"path": str(dest), "kind": "folder", "verified": ok})
    note = f" {skipped} link(s) inside were skipped." if skipped else ""
    return ToolResult(
        ok,
        f"Opened {src.name} into the folder '{dest.name}': {len(on_disk)} file(s), "
        f"{total / 2**20:,.1f} MB."
        + (f" Counted them on disk afterwards." if ok
           else f" WARNING: {len(written)} were written but {len(on_disk)} are there.")
        + note + f" {src.name} is unchanged.",
        {"folder": str(dest), "files": len(on_disk), "bytes": total,
         "skipped_links": skipped, "entries_in_archive": inside}, verified=ok)


def _copy(reader, writer, already: int) -> int:
    """Copy one entry, watching the running total.

    The size an archive declares is also written by whoever made it, so it is
    checked again here against what actually comes out.
    """
    written = 0
    while True:
        chunk = reader.read(1024 * 256)
        if not chunk:
            return written
        written += len(chunk)
        if already + written > MAX_UNPACKED_BYTES:
            raise ToolError("The archive is unpacking to far more than it said it would, so Claw stopped.")
        writer.write(chunk)


def register_archive_tools(reg: ToolRegistry) -> None:
    reg.register(ToolSpec(
        "look_inside_archive", "List what is inside a .zip or .tar without unpacking it.",
        Capability.FILES, RiskLevel.READ_ONLY, PeekArgs, look_inside_archive))
    reg.register(ToolSpec(
        "open_archive", "Unpack a .zip or .tar into a new folder, safely; the archive is untouched.",
        Capability.FILES, RiskLevel.LOCAL_WRITE, OpenArgs, open_archive))
