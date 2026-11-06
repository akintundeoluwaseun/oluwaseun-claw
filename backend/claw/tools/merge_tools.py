"""One letter, fifty customers: a template and a table of names.

The job is ordinary and the manual version is miserable - open the letter,
change the name, save as a new file, do it again forty-nine times - and it is
exactly the kind of work a computer should take off somebody.

A template is a Word file or a text file with {Name} style placeholders in
it. A table is a CSV or spreadsheet whose column headings match. Each row
becomes its own document in a new folder.

Two failure modes this is built around, because both produce output that
LOOKS finished:

  A letter that goes out saying "Dear {Name}". If a placeholder has no
  column to fill it, nothing is written at all and the tool says which
  placeholder and which columns it did find. Half a mail merge is worse than
  none, because the broken ones are only found by the customer.

  A placeholder Word has split up. Typing "Dear {Name}," and correcting a
  typo in the middle leaves Word storing it as several runs - "{Na", "m",
  "e}" - and a naive replacement misses every one of them while appearing to
  work on a template typed in one go. Paragraphs are joined before matching
  here, and there is a test with a deliberately split placeholder.

Every document written is reopened, and checked to be sure no placeholder is
left in it and the row's own values are there.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from pydantic import Field

from claw.agent.schemas import Capability
from claw.permissions.policy import PathNotAuthorized, RiskLevel
from claw.tools.base import ToolArgs, ToolContext, ToolError, ToolRegistry, ToolResult, ToolSpec
from claw.tools.file_tools import existing_folder, safe_file_name, unique_path
from claw.tools.table_tools import find_table, norm_header, read_table

#: {Name}, {Amount Due}, {phone_number}. Deliberately not matching across a
#: line break, so stray braces in a document cannot swallow a paragraph.
PLACEHOLDER = re.compile(r"\{([A-Za-z0-9][A-Za-z0-9 _.-]{0,58})\}")

TEMPLATE_EXT = {".docx", ".txt", ".md", ".html"}
#: Beyond this it is a mailing list, and should be done in batches the person
#: can check before they go out.
MAX_ROWS = 500


def find_template(ctx: ToolContext, raw: str, near: str | None = None) -> Path:
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
    raise ToolError(f"There is no template called '{raw}' in the authorized folders.")


def placeholders_in(text: str) -> list[str]:
    seen, out = set(), []
    for m in PLACEHOLDER.finditer(text):
        key = norm_header(m.group(1))
        if key not in seen:
            seen.add(key)
            out.append(m.group(1))
    return out


def template_text(path: Path) -> str:
    """Everything a reader would see, for finding the placeholders."""
    if path.suffix.lower() == ".docx":
        import docx  # noqa: PLC0415
        doc = docx.Document(str(path))
        parts = [p.text for p in doc.paragraphs]
        for table in doc.tables:
            for row in table.rows:
                parts.extend(cell.text for cell in row.cells)
        for section in doc.sections:
            for holder in (section.header, section.footer):
                parts.extend(p.text for p in holder.paragraphs)
        return "\n".join(parts)
    return path.read_text(encoding="utf-8", errors="replace")


def _fill(text: str, values: dict[str, str]) -> str:
    def swap(m: re.Match) -> str:
        key = norm_header(m.group(1))
        return values[key] if key in values else m.group(0)
    return PLACEHOLDER.sub(swap, text)


def _fill_paragraph(paragraph, values: dict[str, str]) -> None:
    """Replace in a Word paragraph, across runs.

    Word stores a paragraph as runs, and an edit splits them, so "{Name}" can
    be held as "{Na" + "m" + "e}". Replacing run by run misses it entirely.
    The whole paragraph's text is rebuilt instead, and the formatting of the
    first run is kept for the lot - which is right for a letter, where a
    placeholder sits in ordinary body text.
    """
    whole = "".join(run.text for run in paragraph.runs)
    if not whole or "{" not in whole:
        return
    filled = _fill(whole, values)
    if filled == whole:
        return
    for run in paragraph.runs[1:]:
        run.text = ""
    if paragraph.runs:
        paragraph.runs[0].text = filled


def _write_docx(template: Path, out: Path, values: dict[str, str]) -> None:
    import docx  # noqa: PLC0415
    doc = docx.Document(str(template))
    for paragraph in doc.paragraphs:
        _fill_paragraph(paragraph, values)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    _fill_paragraph(paragraph, values)
    for section in doc.sections:
        for holder in (section.header, section.footer):
            for paragraph in holder.paragraphs:
                _fill_paragraph(paragraph, values)
    doc.save(str(out))


def _read_back(path: Path) -> str:
    if path.suffix.lower() == ".docx":
        return template_text(path)
    return path.read_text(encoding="utf-8", errors="replace")


class MergeArgs(ToolArgs):
    template: str = Field(min_length=1, max_length=500,
                          description="A Word or text file with {Name} style placeholders")
    table: str = Field(min_length=1, max_length=500,
                       description="A CSV or spreadsheet; its headings match the placeholders")
    name_from: str = Field(default="", max_length=60,
                           description="Column to name each file after; default is the first")
    folder: str | None = Field(default=None, max_length=500)
    save_in: str | None = Field(default=None, max_length=500)
    limit: int = Field(default=0, ge=0, le=MAX_ROWS,
                       description="Only the first N rows, to check before doing them all")


async def mail_merge(args: MergeArgs, ctx: ToolContext) -> ToolResult:
    template = find_template(ctx, args.template, args.folder)
    if template.suffix.lower() not in TEMPLATE_EXT:
        raise ToolError(f"{template.name} is not a template Claw can fill in "
                        "(Word .docx, or .txt, .md, .html).")
    table = find_table(ctx, args.table, args.folder)

    text = await asyncio.to_thread(template_text, template)
    wanted = placeholders_in(text)
    if not wanted:
        raise ToolError(f"{template.name} has no placeholders in it. Put the column names in "
                        "curly brackets where the details should go, like 'Dear {Name},'.")

    header, rows = await asyncio.to_thread(read_table, table)
    columns = {norm_header(h): i for i, h in enumerate(header)}
    missing = [p for p in wanted if norm_header(p) not in columns]
    if missing:
        # Nothing is written. A half-done merge is found by the customer.
        raise ToolError(
            f"{template.name} asks for {', '.join('{' + m + '}' for m in missing)}, and "
            f"{table.name} has no such column. Its columns are: {', '.join(str(h) for h in header)}.")
    if not rows:
        raise ToolError(f"{table.name} has headings but no rows.")
    rows = rows[:args.limit] if args.limit else rows
    if len(rows) > MAX_ROWS:
        raise ToolError(f"{table.name} has {len(rows)} rows, which is more than Claw will do at "
                        f"once (the limit is {MAX_ROWS}). Use 'limit' to do them in batches.")

    name_col = columns.get(norm_header(args.name_from), 0) if args.name_from else 0
    if args.name_from and norm_header(args.name_from) not in columns:
        raise ToolError(f"There is no column called '{args.name_from}' in {table.name}.")

    base = existing_folder(ctx, args.save_in, write=True) if args.save_in else template.parent
    dest = unique_path(base / safe_file_name(f"{template.stem} filled in", ""))
    ctx.policy.check_path(dest, write=True)

    def work():
        dest.mkdir(parents=True, exist_ok=True)
        made, blank = [], []
        for n, row in enumerate(rows, 1):
            values = {key: ("" if row[i] is None else str(row[i]))
                      for key, i in columns.items() if i < len(row)}
            label = str(row[name_col]).strip() if name_col < len(row) and row[name_col] else ""
            out = dest / safe_file_name(label or f"row {n}", template.suffix.lower())
            if out.exists():                       # two customers with the same name
                out = unique_path(out)
            if template.suffix.lower() == ".docx":
                _write_docx(template, out, values)
            else:
                out.write_text(_fill(text, values), encoding="utf-8")
            made.append((out, values))
            if not label:
                blank.append(n)
        return made, blank

    made, blank = await asyncio.to_thread(work)

    def check():
        """Reopen each one: no placeholder left, and the row's own values in it."""
        bad = []
        for out, values in made:
            body = _read_back(out)
            left = [p for p in placeholders_in(body) if norm_header(p) in columns]
            if left:
                bad.append((out.name, f"still says {{{left[0]}}}"))
                continue
            # At least one non-empty value from this row must appear, or the
            # document is not actually this customer's.
            expected = [v for v in values.values() if v and len(v) > 1]
            if expected and not any(v in body for v in expected):
                bad.append((out.name, "none of the row's details are in it"))
        return bad

    bad = await asyncio.to_thread(check)
    on_disk = [p for p in dest.iterdir() if p.is_file()]
    ok = not bad and len(on_disk) == len(made)

    ctx.memory.note_file(template)
    ctx.memory.note_file(table)
    ctx.memory.outputs.append({"path": str(dest), "kind": "folder", "verified": ok})
    filled = ", ".join("{" + p + "}" for p in wanted[:6]) + (" ..." if len(wanted) > 6 else "")
    note = ""
    if blank:
        note += f" {len(blank)} row(s) had no name, so those files are numbered."
    if bad:
        note += " WARNING: " + "; ".join(f"{n} {why}" for n, why in bad[:3])
    return ToolResult(
        ok,
        f"Made {len(on_disk)} document(s) from {template.name}, one for each row of {table.name}, "
        f"in the folder '{dest.name}'. Filled in {filled}. Reopened every one and checked no "
        f"placeholder was left behind.{note}",
        {"folder": str(dest), "count": len(on_disk), "placeholders": wanted,
         "problems": [n for n, _ in bad]}, verified=ok)


def register_merge_tools(reg: ToolRegistry) -> None:
    reg.register(ToolSpec(
        "mail_merge", "Make one document per row of a table from a Word or text template with "
                      "{Name} style placeholders - letters, invoices, certificates.",
        Capability.DOCUMENTS, RiskLevel.LOCAL_WRITE, MergeArgs, mail_merge))
