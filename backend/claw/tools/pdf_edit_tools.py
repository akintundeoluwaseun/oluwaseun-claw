"""Changing PDFs, not just reading them.

Companion to pdf_tools.py, which reads them: that module opens, OCRs,
searches and summarises a PDF and never alters one. This one alters, and
never reads for meaning. Keeping the two apart is deliberate - reading is
safe and writing is not, and they carry different risk levels.

Claw could already read a PDF, search it, OCR it and summarise it. It could
not alter one. Everything a small business actually does to a PDF between
receiving it and sending it on was missing: joining the month's invoices into
one file, pulling three pages out of a forty-page scan, turning a sideways
page the right way up, stamping PAID on it, making a 20 MB scan small enough
to e-mail. Those are not advanced jobs. They are the ordinary ones, and
without them the answer was "open it in something else".

Every tool here writes a NEW file and never changes the one it was given: a
scan is often the only copy, and an undo button is not something Claw has.
Every result is checked by reopening the file that was written and counting
its pages, so a tool cannot report work it did not do.

Built on pypdf, which Claw already ships, so this adds no new dependency and
nothing new to install on the person's computer.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from pydantic import Field, field_validator

from claw.agent.schemas import Capability
from claw.permissions.policy import PathNotAuthorized, RiskLevel
from claw.tools.base import ToolArgs, ToolContext, ToolError, ToolRegistry, ToolResult, ToolSpec, as_str_list
from claw.tools.file_tools import existing_folder, safe_file_name, unique_path

#: A page count above this is a sign the request means something else.
MAX_PAGES = 5000
#: Stamps people actually ask for. Free text is allowed too; this is only
#: here so the common ones are spelled consistently.
COMMON_STAMPS = ("PAID", "DRAFT", "COPY", "CONFIDENTIAL", "ORIGINAL", "VOID", "SAMPLE")


def _authorized(ctx: ToolContext, raw: str) -> Path:
    return ctx.policy.check_path(raw)


def find_pdf(ctx: ToolContext, raw: str, near: str | None = None) -> Path:
    """The PDF the person meant, by path or by name inside authorized folders."""
    try:
        p = ctx.policy.check_path(raw)
        if p.is_file():
            return p
    except PathNotAuthorized:
        pass
    name = Path(str(raw).replace("\\", "/")).name.lower()
    if not name.endswith(".pdf"):
        name += ".pdf"
    bases = ([existing_folder(ctx, near)] if near
             else [Path(r) for r in ctx.settings.permissions.authorized_folders])
    hits = list(dict.fromkeys(q for b in bases if b.is_dir()
                              for q in b.rglob("*.pdf") if q.name.lower() == name))
    if len(hits) == 1:
        return _authorized(ctx, str(hits[0]))
    if len(hits) > 1:
        raise ToolError(f"There are {len(hits)} files called '{name}': "
                        + "; ".join(str(h) for h in hits[:5]) + ". Give the full path or the folder.")
    raise ToolError(f"There is no PDF called '{raw}' in the authorized folders.")


def _read(path: Path):
    from pypdf import PdfReader  # noqa: PLC0415
    try:
        reader = PdfReader(str(path))
    except Exception as exc:  # noqa: BLE001 - a damaged file must say so, not crash
        raise ToolError(f"{path.name} could not be opened as a PDF ({type(exc).__name__}).") from exc
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:  # noqa: BLE001
            pass
        if reader.is_encrypted:
            raise ToolError(f"{path.name} is password-protected. Claw cannot open it without the password.")
    if not reader.pages:
        raise ToolError(f"{path.name} has no pages.")
    return reader


def _count(path: Path) -> int:
    """Reopen a written file and count it. The check, not a guess."""
    from pypdf import PdfReader  # noqa: PLC0415
    return len(PdfReader(str(path)).pages)


def parse_pages(spec: str, total: int) -> list[int]:
    """"3", "2-5", "1,4,9-11" or "all" into zero-based page numbers.

    Page numbers are one-based here because that is what is printed on the
    page and what the person is reading off it. Off-by-one in a tool that
    deletes pages is not a small mistake.
    """
    text = (spec or "").strip().lower()
    if not text or text in ("all", "every", "*"):
        return list(range(total))
    wanted: list[int] = []
    for part in re.split(r"[,\s]+", text):
        if not part:
            continue
        m = re.fullmatch(r"(\d+)\s*(?:-|to|–)\s*(\d+)", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if a > b:
                a, b = b, a
            wanted.extend(range(a, b + 1))
        elif part.isdigit():
            wanted.append(int(part))
        elif part == "last":
            wanted.append(total)
        else:
            raise ToolError(f"'{part}' is not a page number. Write pages like \"3\", \"2-5\" or \"1,4,9-11\".")
    out, seen = [], set()
    for n in wanted:
        if n < 1 or n > total:
            raise ToolError(f"This PDF has {total} page(s), so page {n} does not exist.")
        if n not in seen:
            seen.add(n)
            out.append(n - 1)
    if not out:
        raise ToolError("No pages were given.")
    return out


# ---------- join several PDFs into one ----------
class CombineArgs(ToolArgs):
    files: list[str] = Field(default_factory=list, max_length=200,
                             description="The PDFs to join, in the order they should appear")
    folder: str | None = Field(default=None, max_length=500,
                               description="Or a folder: every PDF in it, in name order")
    file_name: str = Field(default="", max_length=120, description="The new PDF to write")
    save_in: str | None = Field(default=None, max_length=500)


async def combine_pdfs(args: CombineArgs, ctx: ToolContext) -> ToolResult:
    names = as_str_list(args.files)
    if names:
        sources = [find_pdf(ctx, n, args.folder) for n in names]
    elif args.folder:
        folder = existing_folder(ctx, args.folder)
        sources = sorted(p for p in folder.glob("*.pdf") if p.is_file() and not p.name.startswith("~"))
        if not sources:
            raise ToolError(f"There are no PDFs in {folder.name}.")
    else:
        raise ToolError("Say which PDFs to join, or which folder they are in.")
    if len(sources) < 2:
        raise ToolError("Joining needs at least two PDFs.")

    dest = existing_folder(ctx, args.save_in, write=True) if args.save_in else sources[0].parent
    out = unique_path(dest / safe_file_name(args.file_name or "combined", ".pdf"))
    ctx.policy.check_path(out, write=True)

    def work():
        from pypdf import PdfWriter  # noqa: PLC0415
        writer = PdfWriter()
        counts = []
        for src in sources:
            reader = _read(src)
            counts.append(len(reader.pages))
            for page in reader.pages:
                writer.add_page(page)
        if sum(counts) > MAX_PAGES:
            raise ToolError(f"That would make a {sum(counts)}-page PDF, which is more than Claw will write at once.")
        with open(out, "wb") as fh:
            writer.write(fh)
        return counts

    counts = await asyncio.to_thread(work)
    written = _count(out)
    ok = written == sum(counts)
    for src in sources:
        ctx.memory.note_file(src)
    ctx.memory.outputs.append({"path": str(out), "kind": "document", "verified": ok})
    detail = ", ".join(f"{s.name} ({c})" for s, c in list(zip(sources, counts))[:6])
    return ToolResult(
        ok,
        f"Joined {len(sources)} PDF(s) into {out.name}: {written} pages. From {detail}"
        + (" ..." if len(sources) > 6 else "")
        + (". Reopened and counted." if ok else f". WARNING: expected {sum(counts)} pages, the file has {written}."),
        {"path": str(out), "pages": written, "sources": [str(s) for s in sources]}, verified=ok)


# ---------- keep only some pages ----------
class ExtractArgs(ToolArgs):
    path: str = Field(min_length=1, max_length=500)
    pages: str = Field(min_length=1, max_length=200, description='e.g. "3", "2-5" or "1,4,9-11"')
    file_name: str = Field(default="", max_length=120)
    folder: str | None = Field(default=None, max_length=500)
    save_in: str | None = Field(default=None, max_length=500)


async def extract_pages(args: ExtractArgs, ctx: ToolContext) -> ToolResult:
    src = find_pdf(ctx, args.path, args.folder)
    reader = _read(src)
    total = len(reader.pages)
    wanted = parse_pages(args.pages, total)
    dest = existing_folder(ctx, args.save_in, write=True) if args.save_in else src.parent
    out = unique_path(dest / safe_file_name(args.file_name or f"{src.stem} pages {args.pages}", ".pdf"))
    ctx.policy.check_path(out, write=True)

    def work():
        from pypdf import PdfWriter  # noqa: PLC0415
        writer = PdfWriter()
        for i in wanted:
            writer.add_page(reader.pages[i])
        with open(out, "wb") as fh:
            writer.write(fh)

    await asyncio.to_thread(work)
    written = _count(out)
    ok = written == len(wanted)
    ctx.memory.note_file(src)
    ctx.memory.outputs.append({"path": str(out), "kind": "document", "verified": ok})
    return ToolResult(
        ok,
        f"Took {len(wanted)} page(s) of {total} from {src.name} into {out.name}"
        + (f" and reopened it to count {written}." if ok else f". WARNING: it has {written} pages, not {len(wanted)}.")
        + f" {src.name} is unchanged.",
        {"path": str(out), "pages": written, "taken_from": str(src)}, verified=ok)


# ---------- split into separate files ----------
class SplitArgs(ToolArgs):
    path: str = Field(min_length=1, max_length=500)
    every: int = Field(default=1, ge=1, le=500, description="Pages per file; 1 makes one file per page")
    folder: str | None = Field(default=None, max_length=500)
    save_in: str | None = Field(default=None, max_length=500)


async def split_pdf(args: SplitArgs, ctx: ToolContext) -> ToolResult:
    src = find_pdf(ctx, args.path, args.folder)
    reader = _read(src)
    total = len(reader.pages)
    if total < 2:
        raise ToolError(f"{src.name} has one page, so there is nothing to split.")
    groups = [list(range(i, min(i + args.every, total))) for i in range(0, total, args.every)]
    base = existing_folder(ctx, args.save_in, write=True) if args.save_in else src.parent
    dest = unique_path(base / safe_file_name(f"{src.stem} split", ""))
    ctx.policy.check_path(dest, write=True)

    def work():
        from pypdf import PdfWriter  # noqa: PLC0415
        dest.mkdir(parents=True, exist_ok=True)
        made = []
        width = len(str(len(groups)))
        for n, group in enumerate(groups, 1):
            writer = PdfWriter()
            for i in group:
                writer.add_page(reader.pages[i])
            part = dest / safe_file_name(f"{src.stem} {str(n).zfill(width)}", ".pdf")
            with open(part, "wb") as fh:
                writer.write(fh)
            made.append(part)
        return made

    made = await asyncio.to_thread(work)
    counted = [_count(p) for p in made]
    ok = len(made) == len(groups) and sum(counted) == total
    ctx.memory.note_file(src)
    for p in made[:20]:
        ctx.memory.outputs.append({"path": str(p), "kind": "document", "verified": ok})
    return ToolResult(
        ok,
        f"Split {src.name} ({total} pages) into {len(made)} file(s) in '{dest.name}'"
        + (f", {args.every} pages each" if args.every > 1 else ", one page each")
        + (f". Reopened all {len(made)} and counted {sum(counted)} pages in total."
           if ok else f". WARNING: the parts hold {sum(counted)} pages, not {total}.")
        + f" {src.name} is unchanged.",
        {"folder": str(dest), "files": [str(p) for p in made], "pages": total}, verified=ok)


# ---------- turn pages the right way up ----------
class RotateArgs(ToolArgs):
    path: str = Field(min_length=1, max_length=500)
    degrees: int = Field(default=90, description="90, 180 or 270, clockwise")
    pages: str = Field(default="all", max_length=200, description='Which pages, e.g. "1" or "2-5"')
    file_name: str = Field(default="", max_length=120)
    folder: str | None = Field(default=None, max_length=500)
    save_in: str | None = Field(default=None, max_length=500)

    @field_validator("degrees")
    @classmethod
    def _quarter_turns(cls, v: int) -> int:
        turn = v % 360
        if turn not in (90, 180, 270):
            raise ValueError("A PDF page turns in quarters: 90, 180 or 270 degrees.")
        return turn


async def rotate_pdf(args: RotateArgs, ctx: ToolContext) -> ToolResult:
    src = find_pdf(ctx, args.path, args.folder)
    reader = _read(src)
    total = len(reader.pages)
    wanted = set(parse_pages(args.pages, total))
    dest = existing_folder(ctx, args.save_in, write=True) if args.save_in else src.parent
    out = unique_path(dest / safe_file_name(args.file_name or f"{src.stem} turned", ".pdf"))
    ctx.policy.check_path(out, write=True)

    def work():
        from pypdf import PdfWriter  # noqa: PLC0415
        writer = PdfWriter()
        before = []
        for i, page in enumerate(reader.pages):
            before.append(int(page.rotation or 0))
            if i in wanted:
                page.rotate(args.degrees)
            writer.add_page(page)
        with open(out, "wb") as fh:
            writer.write(fh)
        return before

    before = await asyncio.to_thread(work)

    def check():
        from pypdf import PdfReader  # noqa: PLC0415
        return [int(p.rotation or 0) for p in PdfReader(str(out)).pages]

    after = await asyncio.to_thread(check)
    ok = len(after) == total and all(
        after[i] % 360 == (before[i] + args.degrees) % 360 if i in wanted else after[i] % 360 == before[i] % 360
        for i in range(total))
    ctx.memory.note_file(src)
    ctx.memory.outputs.append({"path": str(out), "kind": "document", "verified": ok})
    which = "every page" if len(wanted) == total else f"{len(wanted)} page(s)"
    return ToolResult(
        ok,
        f"Turned {which} of {src.name} by {args.degrees} degrees into {out.name}"
        + (". Reopened and checked each page's rotation." if ok else ". WARNING: the saved rotations are not what was asked for.")
        + f" {src.name} is unchanged.",
        {"path": str(out), "pages": total, "degrees": args.degrees}, verified=ok)


# ---------- stamp a word across the pages ----------
class StampArgs(ToolArgs):
    path: str = Field(min_length=1, max_length=500)
    text: str = Field(default="PAID", min_length=1, max_length=40,
                      description="e.g. PAID, DRAFT, COPY, CONFIDENTIAL")
    pages: str = Field(default="all", max_length=200)
    file_name: str = Field(default="", max_length=120)
    folder: str | None = Field(default=None, max_length=500)
    save_in: str | None = Field(default=None, max_length=500)


async def stamp_pdf(args: StampArgs, ctx: ToolContext) -> ToolResult:
    src = find_pdf(ctx, args.path, args.folder)
    reader = _read(src)
    total = len(reader.pages)
    wanted = parse_pages(args.pages, total)
    text = args.text.strip()
    dest = existing_folder(ctx, args.save_in, write=True) if args.save_in else src.parent
    out = unique_path(dest / safe_file_name(args.file_name or f"{src.stem} {text.lower()}", ".pdf"))
    ctx.policy.check_path(out, write=True)

    def work():
        from pypdf import PdfWriter  # noqa: PLC0415
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        for i in wanted:
            _draw_stamp(writer.pages[i], text)
        with open(out, "wb") as fh:
            writer.write(fh)

    await asyncio.to_thread(work)

    def check():
        """Read the stamp back off the page itself.

        The text is drawn into the page's content, not hung on it as an
        annotation, so extract_text finds it - and so does every viewer and
        every printer. An annotation can be switched off, not printed, or
        dropped by whatever the person opens it in next, which is no use on
        a document whose point is that it says PAID.
        """
        from pypdf import PdfReader  # noqa: PLC0415
        pages = PdfReader(str(out)).pages
        stamped = sum(1 for i in wanted if text.lower() in (pages[i].extract_text() or "").lower())
        return len(pages), stamped

    written, stamped = await asyncio.to_thread(check)
    ok = written == total and stamped == len(wanted)
    ctx.memory.note_file(src)
    ctx.memory.outputs.append({"path": str(out), "kind": "document", "verified": ok})
    return ToolResult(
        ok,
        f"Stamped '{text}' on {len(wanted)} page(s) of {src.name} into {out.name}"
        + (f". Reopened and found the stamp on all {stamped}." if ok
           else f". WARNING: the stamp was found on {stamped} of {len(wanted)} pages.")
        + f" {src.name} is unchanged.",
        {"path": str(out), "pages": written, "stamped": stamped, "text": text}, verified=ok)


def _draw_stamp(page: object, text: str) -> None:
    """Draw the word across the page, big, pale red and on the diagonal.

    Written as page content rather than as an annotation. The first version
    used a FreeText annotation, which rendered as small left-aligned text
    instead of a stamp, and annotations can be hidden, left out of a printout
    or stripped by the next program that touches the file. A stamp that only
    shows in some viewers is worse than none, because the person believes the
    document is marked.

    Pale and behind-looking rather than solid, so the writing underneath
    stays readable: this marks a document, it does not censor it.
    """
    from pypdf.generic import (  # noqa: PLC0415
        ArrayObject, DecodedStreamObject, DictionaryObject, FloatObject, NameObject,
    )
    box = page.mediabox
    w, h = float(box.width), float(box.height)
    # Big enough to read across the page, small enough that a long word fits.
    size = max(18.0, min(w * 1.15 / max(len(text), 4), h / 4))
    # Helvetica-Bold is about 0.72 em per character on average.
    half = size * 0.72 * len(text) / 2
    cos = sin = 0.70710678          # 45 degrees
    body = (
        "q\n"
        "/ClawStampGS gs\n"
        "0.80 0.16 0.16 rg\n"
        f"{cos:.8f} {sin:.8f} {-sin:.8f} {cos:.8f} {w / 2:.2f} {h / 2:.2f} cm\n"
        f"BT /ClawStampFont {size:.2f} Tf {-half:.2f} {-size * 0.35:.2f} Td "
        f"({_escape(text)}) Tj ET\n"
        "Q\n"
    ).encode("latin-1", "replace")

    stream = DecodedStreamObject()
    stream.set_data(body)

    resources = page.get("/Resources")
    if resources is None:
        resources = DictionaryObject()
        page[NameObject("/Resources")] = resources
    resources = resources.get_object()

    fonts = resources.get("/Font")
    if fonts is None:
        fonts = DictionaryObject()
        resources[NameObject("/Font")] = fonts
    fonts.get_object()[NameObject("/ClawStampFont")] = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica-Bold"),
    })

    states = resources.get("/ExtGState")
    if states is None:
        states = DictionaryObject()
        resources[NameObject("/ExtGState")] = states
    states.get_object()[NameObject("/ClawStampGS")] = DictionaryObject({
        NameObject("/Type"): NameObject("/ExtGState"),
        NameObject("/ca"): FloatObject(0.30),      # fill transparency
        NameObject("/CA"): FloatObject(0.30),
    })

    existing = page.get("/Contents")
    if existing is None:
        page[NameObject("/Contents")] = stream
    elif isinstance(existing.get_object(), ArrayObject):
        existing.get_object().append(stream)
    else:
        page[NameObject("/Contents")] = ArrayObject([existing, stream])


def _escape(text: str) -> str:
    """A PDF string: backslash, brackets."""
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


# ---------- make it smaller to send ----------
class ShrinkArgs(ToolArgs):
    path: str = Field(min_length=1, max_length=500)
    file_name: str = Field(default="", max_length=120)
    folder: str | None = Field(default=None, max_length=500)
    save_in: str | None = Field(default=None, max_length=500)


async def shrink_pdf(args: ShrinkArgs, ctx: ToolContext) -> ToolResult:
    src = find_pdf(ctx, args.path, args.folder)
    reader = _read(src)
    before = src.stat().st_size
    dest = existing_folder(ctx, args.save_in, write=True) if args.save_in else src.parent
    out = unique_path(dest / safe_file_name(args.file_name or f"{src.stem} smaller", ".pdf"))
    ctx.policy.check_path(out, write=True)

    def work():
        from pypdf import PdfWriter  # noqa: PLC0415
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        for page in writer.pages:
            try:
                page.compress_content_streams()
            except Exception:  # noqa: BLE001 - a page that will not compress is not a failure
                pass
        with open(out, "wb") as fh:
            writer.write(fh)

    await asyncio.to_thread(work)
    written = _count(out)
    after = out.stat().st_size
    ok = written == len(reader.pages)
    saved = before - after
    ctx.memory.note_file(src)
    ctx.memory.outputs.append({"path": str(out), "kind": "document", "verified": ok})
    if not ok:
        note = f"WARNING: the smaller copy has {written} pages, not {len(reader.pages)}."
    elif saved > 0:
        note = f"{_size(before)} down to {_size(after)}, {round(saved * 100 / before)}% smaller."
    else:
        # Saying so is the honest answer; an already-tight PDF cannot be
        # squeezed by recompressing what is already compressed.
        note = (f"It is already as small as Claw can make it ({_size(before)}); the copy is "
                f"{_size(after)}. Scanned pictures need a different kind of shrinking.")
    return ToolResult(
        ok, f"{src.name}: {note} Saved as {out.name}, {written} pages, and {src.name} is unchanged.",
        {"path": str(out), "pages": written, "bytes_before": before, "bytes_after": after}, verified=ok)


def _size(n: int) -> str:
    for unit in ("bytes", "KB", "MB"):
        if n < 1024 or unit == "MB":
            return f"{n:,.0f} {unit}" if unit == "bytes" else f"{n:,.1f} {unit}"
        n /= 1024.0
    return f"{n} bytes"


def register_pdf_edit_tools(reg: ToolRegistry) -> None:
    reg.register(ToolSpec(
        "combine_pdfs", "Join several PDFs into one new PDF, in order; the originals are untouched.",
        Capability.DOCUMENTS, RiskLevel.LOCAL_WRITE, CombineArgs, combine_pdfs))
    reg.register(ToolSpec(
        "extract_pages", 'Save chosen pages of a PDF as a new PDF (e.g. "2-5"); the original is untouched.',
        Capability.DOCUMENTS, RiskLevel.LOCAL_WRITE, ExtractArgs, extract_pages))
    reg.register(ToolSpec(
        "split_pdf", "Split a PDF into separate files, one page each or every N pages, in a new folder.",
        Capability.DOCUMENTS, RiskLevel.LOCAL_WRITE, SplitArgs, split_pdf))
    reg.register(ToolSpec(
        "rotate_pdf", "Turn sideways or upside-down pages the right way up, into a new PDF.",
        Capability.DOCUMENTS, RiskLevel.LOCAL_WRITE, RotateArgs, rotate_pdf))
    reg.register(ToolSpec(
        "stamp_pdf", "Stamp a word such as PAID, DRAFT or COPY across the pages of a PDF, into a new PDF.",
        Capability.DOCUMENTS, RiskLevel.LOCAL_WRITE, StampArgs, stamp_pdf))
    reg.register(ToolSpec(
        "shrink_pdf", "Make a PDF smaller so it can be e-mailed, and say how much smaller it got.",
        Capability.DOCUMENTS, RiskLevel.LOCAL_WRITE, ShrinkArgs, shrink_pdf))
