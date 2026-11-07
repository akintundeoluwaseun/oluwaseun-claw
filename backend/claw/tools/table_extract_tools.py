"""Getting a table out of a PDF or a Word file and into a spreadsheet.

A bank statement, a supplier's invoice, a price list: the numbers are right
there on the page and retyping forty rows is an afternoon and a dozen typos.

There was a way to do this already and it is the wrong way: the brain reads
the document, then calls list_to_table with the rows it has typed out. That
puts every digit through a language model. A 2B model transcribing a column
of amounts will get some of them wrong, and nothing downstream can tell -
the spreadsheet looks perfectly ordinary. This tool reads the file itself,
so no number passes through the model at all.

The check that makes it safe: every cell written is looked for in the
document's own text. A cell that is not there did not come from the
document, and the tool says so instead of saving it. That cannot catch a
column split in the wrong place - the text would still match - so the tool
also refuses a page whose lines do not agree on how many columns there are,
rather than guessing and producing a tidy, wrong sheet.
"""

from __future__ import annotations

import asyncio
import re
from collections import Counter
from pathlib import Path

from pydantic import Field

from claw.agent.schemas import Capability
from claw.documents.readers import read_document
from claw.permissions.policy import PathNotAuthorized, RiskLevel
from claw.tools.base import ToolArgs, ToolContext, ToolError, ToolRegistry, ToolResult, ToolSpec
from claw.tools.file_tools import existing_folder, safe_file_name, unique_path

#: Two or more spaces is how a PDF's text layer separates columns once the
#: layout is flattened. A single space is a space inside a word.
COLUMN_GAP = re.compile(r"\s{2,}|\t")
#: Below this a "table" is a couple of stray lines that happen to line up.
MIN_ROWS = 3
MAX_ROWS = 5000
#: The share of lines that must agree on the column count before Claw will
#: call it a table at all.
AGREEMENT = 0.6


def find_document(ctx: ToolContext, raw: str, near: str | None = None) -> Path:
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


def split_row(line: str) -> list[str]:
    return [c.strip() for c in COLUMN_GAP.split(line.strip()) if c.strip() != ""]


def find_table(text: str) -> tuple[list[list[str]], int, str]:
    """The rows of the widest consistent block of columns in the text.

    Returns (rows, columns, note). Raises when nothing in the document looks
    like a table, which is a real answer and better than a tidy wrong one.
    """
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise ToolError("There is no text in that document to read a table from.")

    counted = [(ln, len(split_row(ln))) for ln in lines]
    widths = Counter(n for _, n in counted if n >= 2)
    if not widths:
        raise ToolError(
            "Nothing in that document is laid out as a table. Columns are recognised by the "
            "gaps between them, and this page has none - a scan with no text layer, or a "
            "document written as sentences, will look like this.")

    # The most common width wins; a tie goes to the wider one, because a
    # two-column reading of a four-column table is the usual wrong answer.
    best = max(widths.items(), key=lambda kv: (kv[1], kv[0]))[0]
    rows = [split_row(ln) for ln, n in counted if n == best]
    share = len(rows) / max(len(lines), 1)
    if len(rows) < MIN_ROWS:
        raise ToolError(
            f"Only {len(rows)} line(s) in that document line up into {best} columns, which is "
            "too few to be a table. Say which pages the table is on, if it is a long document.")
    if share < AGREEMENT and len(rows) < 10:
        raise ToolError(
            f"That document is not laid out consistently enough to read as a table: only "
            f"{len(rows)} of {len(lines)} lines have the same {best} columns.")
    if len(rows) > MAX_ROWS:
        raise ToolError(f"That is {len(rows)} rows, which is more than Claw will write at once.")
    note = ("" if share >= AGREEMENT else
            f" Only {len(rows)} of {len(lines)} lines matched, so check it against the original.")
    return rows, best, note


def _number_shown_as(value: object, flat: str) -> bool:
    """Is this cell's number on the page, written the way the page writes it?

    A cell holding -2500 is not missing because the statement says
    "(2,500)" - brackets are how a ledger writes a negative, and to_number
    reads them that way on the way in. Checking only the digits as stored
    would warn on every debit, which is most of a bank statement, and a
    warning that fires on correct output teaches people to ignore warnings.

    The sign is part of the match, not an afterthought. "2,500" is a
    substring of "(2,500)", so a plain search accepts a POSITIVE 2500 for a
    page that only shows a debit - a sign error, silently passed, on the one
    column where a sign error matters most. The digits must therefore be
    found without a bracket or a minus in front when the cell is positive,
    and with one when it is negative.
    """
    try:
        n = float(str(value))
    except (TypeError, ValueError):
        return False
    whole = abs(n)
    # Both the trimmed and untrimmed forms: a page writing 350.50 and a cell
    # holding 350.5 are the same money, and the lookahead below would
    # otherwise reject the trailing zero as "different digits".
    bodies = {f"{whole:,.2f}", f"{whole:,.2f}".rstrip("0").rstrip("."),
              f"{whole:,.0f}", f"{whole:.2f}", f"{whole:.2f}".rstrip("0").rstrip("."),
              str(int(whole)) if float(whole).is_integer() else str(whole)}
    for body in bodies:
        if not body:
            continue
        digits = re.escape(body)
        if n < 0:
            found = re.search(rf"\(\s*{digits}\s*\)|-\s*{digits}\b|{digits}\s*-", flat)
        else:
            # Not preceded by ( or -, and not followed by a trailing minus.
            found = re.search(rf"(?<![(\-\d.,]){digits}(?![\d.,]|\s*[)\-])", flat)
        if found:
            return True
    return False


class ExtractArgs(ToolArgs):
    path: str = Field(min_length=1, max_length=500, description="A PDF, Word file or text file")
    folder: str | None = Field(default=None, max_length=500)
    has_header: bool = Field(default=True, description="Treat the first row as column names")
    file_name: str = Field(default="", max_length=120)
    save_in: str | None = Field(default=None, max_length=500)


async def table_from_document(args: ExtractArgs, ctx: ToolContext) -> ToolResult:
    src = find_document(ctx, args.path, args.folder)
    text = await asyncio.to_thread(read_document, src)
    rows, columns, note = await asyncio.to_thread(find_table, text)

    dest = existing_folder(ctx, args.save_in, write=True) if args.save_in else src.parent
    out = unique_path(dest / safe_file_name(args.file_name or f"{src.stem} table", ".xlsx"))
    ctx.policy.check_path(out, write=True)

    header = rows[0] if args.has_header else [f"Column {i + 1}" for i in range(columns)]
    body = rows[1:] if args.has_header else rows

    def work():
        import openpyxl  # noqa: PLC0415
        from openpyxl.styles import Font  # noqa: PLC0415
        from claw.tools.table_tools import fit_to_page, to_number  # noqa: PLC0415

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "From the document"[:31]
        ws.append(header)
        for cell in ws[1]:
            cell.font = Font(bold=True)
        for row in body:
            # A number stays a number, so the sheet can be totalled. The text
            # is kept when it is not one, rather than forced to zero.
            ws.append([(to_number(c) if to_number(c) is not None else c) for c in row])
        ws.freeze_panes = "A2"
        for i, name in enumerate(header, 1):
            widest = max([len(str(name))] + [len(str(r[i - 1])) for r in body[:300] if i - 1 < len(r)])
            ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = min(48, max(9, widest + 2))
        fit_to_page(ws, openpyxl.utils.get_column_letter(len(header)), len(body) + 1)
        wb.save(out)

    await asyncio.to_thread(work)

    def check():
        """Every cell must be findable in the document's own text.

        This is the whole reason to prefer this over the brain retyping the
        page: a cell that is not in the source did not come from the source.
        Whitespace is flattened on both sides, because the text layer's idea
        of spacing is not the page's.
        """
        import openpyxl  # noqa: PLC0415
        flat = " ".join(text.split())
        ws = openpyxl.load_workbook(out).active
        missing, cells = [], 0
        for row in ws.iter_rows(values_only=True):
            for value in row:
                if value is None or str(value).strip() == "":
                    continue
                cells += 1
                if args.has_header is False and str(value).startswith("Column "):
                    continue
                shown = " ".join(str(value).split())
                # Flagged only when the text is not on the page AND it is not
                # a number the page writes differently ("(2,500)" for -2500).
                if shown not in flat and not _number_shown_as(value, flat):
                    missing.append(shown)
        return ws.max_row, ws.max_column, cells, missing

    written_rows, written_cols, cells, missing = await asyncio.to_thread(check)
    ok = not missing
    ctx.memory.note_file(src)
    ctx.memory.outputs.append({"path": str(out), "kind": "spreadsheet", "verified": ok})
    if not ok:
        # Said plainly rather than hidden: the sheet exists, and it has
        # something in it that the document does not.
        warning = (f" WARNING: {len(missing)} cell(s) are not in {src.name} as written, "
                   f"for example {missing[0][:40]!r}. Check it against the original.")
    else:
        warning = f" Checked all {cells} cells against the text of {src.name}."
    return ToolResult(
        ok,
        f"Read a {written_cols}-column table out of {src.name} into {out.name}: "
        f"{written_rows - 1} row(s) under {', '.join(str(h) for h in header[:4])}"
        + ("..." if len(header) > 4 else "") + "." + warning + note,
        {"path": str(out), "rows": written_rows - 1, "columns": written_cols,
         "header": header, "unverified_cells": missing[:20]}, verified=ok)


def register_table_extract_tools(reg: ToolRegistry) -> None:
    reg.register(ToolSpec(
        "table_from_document", "Read a table out of a PDF, Word or text file into a spreadsheet - "
                               "a bank statement, an invoice, a price list - without retyping it.",
        Capability.DOCUMENTS, RiskLevel.LOCAL_WRITE, ExtractArgs, table_from_document))
