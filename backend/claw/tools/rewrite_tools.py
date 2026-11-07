"""Changing the same thing in many files, and joining Word documents.

Two jobs that come up constantly and had nothing:

  replace_in_files  the business changed its phone number, or a name was
                    spelled wrong in forty quotations. Doing it by hand is
                    forty chances to miss one.
  merge_documents   three Word files into one, in order.

replace_in_files never edits in place. It writes corrected copies into a NEW
folder and leaves the originals exactly as they were. That is not timidity:
a find-and-replace across a folder is the single easiest way to destroy an
afternoon's work, there is no undo, and the person usually wants to look at
the result before trusting it. It also refuses to run when the text appears
nowhere, rather than cheerfully copying the folder and reporting success.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from pydantic import Field

from claw.agent.schemas import Capability
from claw.permissions.policy import PathNotAuthorized, RiskLevel
from claw.tools.base import ToolArgs, ToolContext, ToolError, ToolRegistry, ToolResult, ToolSpec, as_str_list
from claw.tools.file_tools import existing_folder, safe_file_name, unique_path

#: Plain-text kinds it is safe to rewrite whole. A .docx is a zip, so it is
#: handled separately below; anything binary is left alone.
REWRITABLE = {".txt", ".md", ".csv", ".tsv", ".json", ".html", ".htm", ".xml", ".css",
              ".js", ".ts", ".py", ".sql", ".log", ".ini", ".yaml", ".yml", ".toml",
              ".bat", ".ps1", ".sh", ".srt", ".vtt"}
MAX_FILES = 400
#: A file bigger than this is not something a person is proof-reading.
MAX_BYTES = 20 * 1024 * 1024


def _find(ctx: ToolContext, raw: str, near: str | None = None) -> Path:
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
        raise ToolError(f"There are {len(hits)} files called '{name}'. Give the full path.")
    raise ToolError(f"There is no file '{raw}' in the authorized folders.")


def _docx_text(path: Path) -> str:
    import docx  # noqa: PLC0415
    return "\n".join(p.text for p in docx.Document(str(path)).paragraphs)


def _replace_docx(src: Path, out: Path, find: str, put: str, whole_word: bool,
                  ignore_case: bool) -> int:
    """Rewrite a Word file, joining each paragraph's runs first.

    Word splits a paragraph into runs wherever anything changed, so a phrase
    the reader sees as one piece can be stored in three. Matching run by run
    misses it; the paragraph is rebuilt instead, keeping the first run's
    formatting for the line.
    """
    import docx  # noqa: PLC0415
    doc = docx.Document(str(src))
    pattern = _pattern(find, whole_word, ignore_case)
    changed = 0

    def do(paragraph) -> None:
        nonlocal changed
        whole = "".join(r.text for r in paragraph.runs)
        if not whole:
            return
        new, n = pattern.subn(put, whole)
        if not n:
            return
        changed += n
        for run in paragraph.runs[1:]:
            run.text = ""
        paragraph.runs[0].text = new

    for paragraph in doc.paragraphs:
        do(paragraph)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    do(paragraph)
    for section in doc.sections:
        for holder in (section.header, section.footer):
            for paragraph in holder.paragraphs:
                do(paragraph)
    doc.save(str(out))
    return changed


def _pattern(find: str, whole_word: bool, ignore_case: bool) -> re.Pattern:
    body = re.escape(find)
    if whole_word:
        body = rf"\b{body}\b"
    return re.compile(body, re.I if ignore_case else 0)


class ReplaceArgs(ToolArgs):
    folder: str = Field(min_length=1, max_length=500)
    find: str = Field(min_length=1, max_length=200, description="The text to look for")
    replace_with: str = Field(default="", max_length=200, description="What to put instead")
    only: str = Field(default="", max_length=60, description='Only these files, e.g. "*.txt"')
    whole_word: bool = Field(default=False, description="Match whole words only")
    ignore_case: bool = Field(default=False)
    preview: bool = Field(default=False, description="Only report what would change; write nothing")
    save_in: str | None = Field(default=None, max_length=500)


async def replace_in_files(args: ReplaceArgs, ctx: ToolContext) -> ToolResult:
    import fnmatch  # noqa: PLC0415

    src = existing_folder(ctx, args.folder)
    pattern = _pattern(args.find, args.whole_word, args.ignore_case)

    candidates = sorted(
        p for p in src.rglob("*")
        if p.is_file() and not p.name.startswith("~$")
        and p.suffix.lower() in REWRITABLE | {".docx"}
        and p.stat().st_size <= MAX_BYTES)
    if args.only:
        candidates = [p for p in candidates if fnmatch.fnmatch(p.name.lower(), args.only.lower())]
    if not candidates:
        raise ToolError(f"There are no files Claw can rewrite in {src.name}"
                        + (f" matching '{args.only}'." if args.only else
                           " (it works on text files and Word documents)."))
    if len(candidates) > MAX_FILES:
        raise ToolError(f"{src.name} holds {len(candidates)} files, which is more than Claw will "
                        f"rewrite at once (the limit is {MAX_FILES}).")

    def count_hits():
        hits = []
        for p in candidates:
            try:
                text = _docx_text(p) if p.suffix.lower() == ".docx" else p.read_text(
                    encoding="utf-8", errors="strict")
            except (UnicodeDecodeError, OSError, Exception):  # noqa: BLE001
                continue
            n = len(pattern.findall(text))
            if n:
                hits.append((p, n))
        return hits

    hits = await asyncio.to_thread(count_hits)
    if not hits:
        # Not an error worth hiding: copying the folder and saying "done"
        # would leave the person believing the change was made.
        raise ToolError(
            f"'{args.find}' does not appear in any of the {len(candidates)} file(s) in "
            f"{src.name}, so nothing was changed." + (" (Try ignore_case.)" if not args.ignore_case else ""))

    total = sum(n for _, n in hits)
    where = "; ".join(f"{p.relative_to(src)} ({n})" for p, n in hits[:8]) + (
        " ..." if len(hits) > 8 else "")
    if args.preview:
        return ToolResult(
            True,
            f"'{args.find}' appears {total} time(s) in {len(hits)} of {len(candidates)} file(s) in "
            f"{src.name}: {where}. Nothing was changed - this was a preview.",
            {"files": len(hits), "occurrences": total,
             "where": [[str(p), n] for p, n in hits]}, verified=True)

    base = existing_folder(ctx, args.save_in, write=True) if args.save_in else src.parent
    dest = unique_path(base / safe_file_name(f"{src.name} corrected", ""))
    ctx.policy.check_path(dest, write=True)

    def work():
        dest.mkdir(parents=True, exist_ok=True)
        made, done = [], 0
        for p, _ in hits:
            out = dest / p.relative_to(src)
            out.parent.mkdir(parents=True, exist_ok=True)
            if p.suffix.lower() == ".docx":
                done += _replace_docx(p, out, args.find, args.replace_with,
                                      args.whole_word, args.ignore_case)
            else:
                text = p.read_text(encoding="utf-8")
                new, n = pattern.subn(args.replace_with, text)
                out.write_text(new, encoding="utf-8")
                done += n
            made.append(out)
        return made, done

    made, done = await asyncio.to_thread(work)

    def check():
        """Reopen each copy: the old text gone, the new text there."""
        bad = []
        for out in made:
            text = _docx_text(out) if out.suffix.lower() == ".docx" else out.read_text(
                encoding="utf-8", errors="replace")
            if pattern.search(text):
                bad.append(out.name)
            elif args.replace_with and args.replace_with not in text:
                bad.append(out.name)
        return bad

    bad = await asyncio.to_thread(check)
    on_disk = [p for p in dest.rglob("*") if p.is_file()]
    ok = not bad and len(on_disk) == len(made)
    ctx.memory.outputs.append({"path": str(dest), "kind": "folder", "verified": ok})
    put = f"'{args.replace_with}'" if args.replace_with else "nothing"
    return ToolResult(
        ok,
        f"Changed '{args.find}' to {put} {done} time(s) across {len(made)} file(s), and put the "
        f"corrected copies in '{dest.name}'. Was in: {where}. Reopened every copy to check."
        + (f" WARNING: {', '.join(bad[:3])} still contains it." if bad else "")
        + f" The files in {src.name} are untouched.",
        {"folder": str(dest), "files": len(made), "changes": done,
         "problems": bad}, verified=ok)


# ---------- several Word files into one ----------
class MergeDocsArgs(ToolArgs):
    files: list[str] = Field(default_factory=list, max_length=60,
                             description="The Word files to join, in order")
    folder: str | None = Field(default=None, max_length=500,
                               description="Or a folder: every .docx in it, in name order")
    file_name: str = Field(default="", max_length=120)
    page_breaks: bool = Field(default=True, description="Start each document on a new page")
    save_in: str | None = Field(default=None, max_length=500)


async def merge_documents(args: MergeDocsArgs, ctx: ToolContext) -> ToolResult:
    names = as_str_list(args.files)
    if names:
        sources = [_find(ctx, n, args.folder) for n in names]
    elif args.folder:
        folder = existing_folder(ctx, args.folder)
        sources = sorted(p for p in folder.glob("*.docx") if not p.name.startswith("~$"))
        if not sources:
            raise ToolError(f"There are no Word documents in {folder.name}.")
    else:
        raise ToolError("Say which Word files to join, or which folder they are in.")
    for p in sources:
        if p.suffix.lower() != ".docx":
            raise ToolError(f"{p.name} is not a Word .docx file.")
    if len(sources) < 2:
        raise ToolError("Joining needs at least two documents.")

    dest = existing_folder(ctx, args.save_in, write=True) if args.save_in else sources[0].parent
    out = unique_path(dest / safe_file_name(args.file_name or "joined", ".docx"))
    ctx.policy.check_path(out, write=True)

    def work():
        import docx  # noqa: PLC0415
        from docx.enum.text import WD_BREAK  # noqa: PLC0415

        counts = [len(docx.Document(str(p)).paragraphs) for p in sources]
        merged = docx.Document(str(sources[0]))
        body = merged.element.body
        for p in sources[1:]:
            if args.page_breaks:
                merged.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
            other = docx.Document(str(p))
            for element in other.element.body:
                # The sectPr is the section's own page setup; copying it in
                # would carry the second document's margins into the first.
                if element.tag.endswith("}sectPr"):
                    continue
                body.append(element)
        merged.save(str(out))
        return counts

    counts = await asyncio.to_thread(work)

    def check():
        import docx  # noqa: PLC0415
        joined = docx.Document(str(out))
        text = "\n".join(p.text for p in joined.paragraphs)
        return len(joined.paragraphs), text

    paragraphs, text = await asyncio.to_thread(check)
    # Something from the LAST document must be in it, not just the first:
    # that is the way this fails - the copy succeeds and appends nothing.
    tail = [p.text.strip() for p in __import__("docx").Document(str(sources[-1])).paragraphs
            if p.text.strip()]
    ok = bool(tail) and any(line in text for line in tail[:3])
    ctx.memory.outputs.append({"path": str(out), "kind": "document", "verified": ok})
    return ToolResult(
        ok,
        f"Joined {len(sources)} document(s) into {out.name}: {paragraphs} paragraphs, from "
        + ", ".join(f"{p.name} ({c})" for p, c in list(zip(sources, counts))[:6])
        + ("..." if len(sources) > 6 else "")
        + (". Reopened it and found the last document's text in it."
           if ok else ". WARNING: the last document's text is not in the result.")
        + " The originals are untouched.",
        {"path": str(out), "paragraphs": paragraphs,
         "sources": [str(p) for p in sources]}, verified=ok)


def register_rewrite_tools(reg: ToolRegistry) -> None:
    reg.register(ToolSpec(
        "replace_in_files", "Change the same text in many files at once (text files and Word "
                            "documents), writing corrected copies into a new folder.",
        Capability.FILES, RiskLevel.LOCAL_WRITE, ReplaceArgs, replace_in_files))
    reg.register(ToolSpec(
        "merge_documents", "Join several Word documents into one, in order.",
        Capability.DOCUMENTS, RiskLevel.LOCAL_WRITE, MergeDocsArgs, merge_documents))
