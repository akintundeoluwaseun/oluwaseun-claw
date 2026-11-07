"""Reading a table out of a document instead of retyping it.

There was already a way to do this and it is the wrong way: the brain reads
the page and calls list_to_table with the rows it has typed out, which puts
every digit through a language model. A small model transcribing a column of
amounts gets some of them wrong, and the spreadsheet that comes out looks
perfectly ordinary.

So the tests here are mostly about the two honest failures:
  - a cell that is not in the document is reported, not saved quietly;
  - a page that is not really a table is refused, not guessed at.
"""

from __future__ import annotations

import sys
from pathlib import Path

import openpyxl
import pytest

from claw.tools.base import ToolError
from claw.tools.table_extract_tools import find_table, split_row
from tests.test_phase_a import call

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import challenge_bench as cb  # noqa: E402


def folder(ctx, name="Statements"):
    d = Path(ctx.settings.permissions.authorized_folders[0]) / name
    d.mkdir(parents=True, exist_ok=True)
    return d


STATEMENT = [
    "Date        Description            Amount",
    "05/01/2024  Ade Stores             15,000",
    "06/01/2024  Refund Bola            (2,500)",
    "07/01/2024  Chidi Ltd              7,500",
    "08/01/2024  Bank charge            350",
]


# ---------- splitting a line into columns ----------
def test_columns_are_the_gaps_not_the_spaces():
    assert split_row("05/01/2024  Ade Stores             15,000") == [
        "05/01/2024", "Ade Stores", "15,000"]
    # A single space is inside a name, not between columns.
    assert split_row("Ade Stores Limited") == ["Ade Stores Limited"]
    assert split_row("") == []


def test_a_page_of_prose_is_refused():
    prose = "\n".join([
        "Dear Sir, further to our conversation of last week I am writing to confirm",
        "that the delivery will arrive on Tuesday. Please let me know if this is a",
        "problem and we will arrange something else.",
    ])
    with pytest.raises(ToolError, match="(?i)laid out as a table|laid out consistently"):
        find_table(prose)


def test_two_stray_lines_are_not_a_table():
    with pytest.raises(ToolError, match="(?i)too few to be a table|laid out"):
        find_table("Name   Amount\nAde    100\n")


def test_the_widest_consistent_block_wins():
    rows, columns, _ = find_table("\n".join(STATEMENT))
    assert columns == 3
    assert rows[0] == ["Date", "Description", "Amount"]
    assert rows[2] == ["06/01/2024", "Refund Bola", "(2,500)"]


# ---------- end to end ----------
async def test_a_statement_becomes_a_spreadsheet(tool_ctx):
    d = folder(tool_ctx)
    (d / "january.txt").write_text("\n".join(STATEMENT) + "\n", encoding="utf-8")

    r = await call(tool_ctx, "table_from_document", path="january.txt", folder="Statements")
    assert r.ok and r.verified, r.summary
    assert r.data["rows"] == 4 and r.data["columns"] == 3
    assert r.data["header"] == ["Date", "Description", "Amount"]

    ws = openpyxl.load_workbook(r.data["path"]).active
    values = [[c for c in row] for row in ws.iter_rows(values_only=True)]
    assert values[0] == ("Date", "Description", "Amount") or values[0] == [
        "Date", "Description", "Amount"]
    # The amounts are NUMBERS, so the column can be totalled, and the
    # bracketed one is negative as a ledger means it.
    amounts = [row[2] for row in values[1:]]
    assert amounts == [15000, -2500, 7500, 350], amounts
    assert sum(amounts) == 20350


async def test_every_cell_is_checked_against_the_document(tool_ctx):
    """The guard that makes this better than the brain retyping the page."""
    d = folder(tool_ctx)
    (d / "january.txt").write_text("\n".join(STATEMENT) + "\n", encoding="utf-8")
    r = await call(tool_ctx, "table_from_document", path="january.txt", folder="Statements")
    assert r.data["unverified_cells"] == []
    assert "Checked all" in r.summary and "cells against the text" in r.summary


async def test_a_pdf_statement_works_too(tool_ctx):
    d = folder(tool_ctx)
    (d / "statement.pdf").write_bytes(cb.tiny_pdf(STATEMENT))
    r = await call(tool_ctx, "table_from_document", path="statement.pdf", folder="Statements")
    assert r.ok and r.verified, r.summary
    ws = openpyxl.load_workbook(r.data["path"]).active
    text = " ".join(str(c) for row in ws.iter_rows(values_only=True) for c in row if c is not None)
    assert "Ade Stores" in text and "Chidi Ltd" in text


async def test_a_document_with_no_table_says_so_and_writes_nothing(tool_ctx):
    d = folder(tool_ctx)
    (d / "letter.txt").write_text(
        "Dear Sir, further to our conversation I confirm the delivery will arrive on\n"
        "Tuesday. Please let me know if that is a problem and we will arrange another\n"
        "day that suits you better.\n", encoding="utf-8")
    with pytest.raises(ToolError, match="(?i)laid out"):
        await call(tool_ctx, "table_from_document", path="letter.txt", folder="Statements")
    assert not list(d.glob("*.xlsx")), "it wrote a spreadsheet anyway"


async def test_without_a_header_the_first_row_is_kept_as_data(tool_ctx):
    d = folder(tool_ctx)
    (d / "rows.txt").write_text(
        "05/01/2024  Ade Stores   15,000\n"
        "06/01/2024  Bola         7,500\n"
        "07/01/2024  Chidi        2,000\n", encoding="utf-8")
    r = await call(tool_ctx, "table_from_document", path="rows.txt", folder="Statements",
                   has_header=False)
    assert r.data["rows"] == 3, "a data row was eaten as a header"
    ws = openpyxl.load_workbook(r.data["path"]).active
    assert [c.value for c in ws[1]] == ["Column 1", "Column 2", "Column 3"]


async def test_the_original_document_is_not_touched(tool_ctx):
    import hashlib
    d = folder(tool_ctx)
    (d / "january.txt").write_text("\n".join(STATEMENT) + "\n", encoding="utf-8")
    before = hashlib.sha256((d / "january.txt").read_bytes()).hexdigest()
    await call(tool_ctx, "table_from_document", path="january.txt", folder="Statements")
    assert hashlib.sha256((d / "january.txt").read_bytes()).hexdigest() == before


# ---------- the guard itself ----------
def test_a_number_is_recognised_however_the_page_writes_it():
    """A debit written "(2,500)" is the cell holding -2500, not a missing one.

    Without this the check fires on every debit on a bank statement, and a
    warning that goes off on correct output teaches people to ignore it.
    """
    from claw.tools.table_extract_tools import _number_shown_as
    page = "05/01/2024 Ade Stores 15,000 06/01/2024 Refund Bola (2,500) Charge 350.50"
    assert _number_shown_as(15000, page)
    assert _number_shown_as(-2500, page)          # written as (2,500)
    assert _number_shown_as(350.5, page)
    assert _number_shown_as(350.50, page)


def test_a_number_that_is_not_on_the_page_is_not_recognised():
    """The half that matters: the guard must still say no."""
    from claw.tools.table_extract_tools import _number_shown_as
    page = "05/01/2024 Ade Stores 15,000 06/01/2024 Refund Bola (2,500)"
    assert not _number_shown_as(99999, page), "a number that is not there was accepted"
    assert not _number_shown_as(15001, page), "an off-by-one was accepted"
    # The sign is the point: "2,500" is a substring of "(2,500)", so a plain
    # search would accept a POSITIVE 2500 for a page that only shows a debit
    # - a sign error passed silently, in the one column where it matters.
    assert not _number_shown_as(2500, page), "a debit was accepted as a credit"
    assert not _number_shown_as(-15000, page), "a credit was accepted as a debit"
    assert not _number_shown_as("Ade Stores Ltd", page)


async def test_a_cell_the_document_does_not_contain_is_reported(tool_ctx):
    """Proved by doctoring the saved sheet and re-running the same check.

    The extractor cannot easily be made to invent a cell - it copies them -
    so the guard is exercised against a sheet that has been tampered with,
    which is the condition it exists to detect.
    """
    import openpyxl
    d = folder(tool_ctx)
    (d / "january.txt").write_text("\n".join(STATEMENT) + "\n", encoding="utf-8")
    r = await call(tool_ctx, "table_from_document", path="january.txt", folder="Statements")
    assert r.verified

    text = (d / "january.txt").read_text()
    flat = " ".join(text.split())
    ws = openpyxl.load_workbook(r.data["path"]).active
    ws.cell(row=2, column=3, value=99999)            # a figure the statement does not have

    from claw.tools.table_extract_tools import _number_shown_as
    missing = [c.value for row in ws.iter_rows() for c in row
               if c.value is not None and " ".join(str(c.value).split()) not in flat
               and not _number_shown_as(c.value, flat)]
    assert 99999 in missing, "a fabricated figure passed the check"
