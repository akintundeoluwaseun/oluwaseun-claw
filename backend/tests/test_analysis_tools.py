"""The business questions sections 7 and 13 keep asking, answered arithmetically.

Twenty-eight challenges across Excel and accounting are four operations with
different nouns in front: group and total, keep the rows that match, line two
tables up on a key, point at the values that do not belong.

Every number asserted here is one worked out by hand in the fixture, not a
shape check. A tool that returns ok=True having summed the wrong column passes
a shape check, and the benchmark's whole complaint about false completions is
exactly that.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from claw.tools.base import ToolError
from tests.test_desktop import call
from tests.test_images import folder  # noqa: F401 - fixture


def write_csv(path: Path, header: list[str], rows: list[list]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return path


@pytest.fixture
def sales(folder: Path) -> Path:
    """Known totals: North 300, South 120, East 75. Widgets 255, Gadgets 240."""
    return write_csv(folder / "sales.csv", ["Region", "Product", "Amount", "Date"], [
        ["North", "Widgets", 100, "2026-01-05"],
        ["North", "Gadgets", 200, "2026-02-11"],
        ["South", "Widgets", 120, "2026-01-20"],
        ["East", "Gadgets", 40, "2026-03-02"],
        ["East", "Widgets", 35, "2026-03-09"],
    ])


# ---------- pivot_table (7.07, 7.09, 13.08, 13.09) ----------

@pytest.mark.asyncio
async def test_totals_by_group_are_arithmetically_right(tool_ctx, sales):
    r = await call(tool_ctx, "pivot_table", path="sales.csv", group_by="Region", value_column="Amount")
    got = {row[0]: row[1] for row in r.data["rows"]}
    assert got == {"North": 300, "South": 120, "East": 75}, got
    assert r.verified


@pytest.mark.asyncio
async def test_average_and_count_are_offered_too(tool_ctx, sales):
    avg = await call(tool_ctx, "pivot_table", path="sales.csv", group_by="Region",
                     value_column="Amount", how="average", file_name="avg")
    assert {row[0]: row[1] for row in avg.data["rows"]}["North"] == 150
    cnt = await call(tool_ctx, "pivot_table", path="sales.csv", group_by="Region",
                     how="count", file_name="cnt")
    assert {row[0]: row[1] for row in cnt.data["rows"]} == {"North": 2, "South": 1, "East": 2}


@pytest.mark.asyncio
async def test_a_second_dimension_becomes_columns_with_a_total(tool_ctx, sales):
    """Region down the side, Product across: a pivot, as asked for in 7.07."""
    r = await call(tool_ctx, "pivot_table", path="sales.csv", group_by="Region",
                   value_column="Amount", split_by="Product", file_name="cross")
    assert r.data["columns"] == ["Region", "Gadgets", "Widgets", "Total"]
    north = next(row for row in r.data["rows"] if row[0] == "North")
    assert north == ["North", 200, 100, 300]


@pytest.mark.asyncio
async def test_the_summary_is_a_real_file_with_the_right_number_of_rows(tool_ctx, sales):
    r = await call(tool_ctx, "pivot_table", path="sales.csv", group_by="Region", file_name="saved")
    from claw.tools.table_tools import read_table
    head, rows = read_table(Path(r.data["path"]))
    assert len(rows) == 3 and head[0] == "Region"


# ---------- filter_rows (13.04 overdue, 13.06 low stock) ----------

@pytest.fixture
def stock(folder: Path) -> Path:
    return write_csv(folder / "stock.csv", ["Item", "Quantity", "Due"], [
        ["Bolts", 4, "2026-01-10"],
        ["Nuts", 60, "2026-05-01"],
        ["Washers", 9, "2026-02-14"],
        ["Screws", 0, "2026-06-30"],
    ])


@pytest.mark.asyncio
async def test_low_stock_is_the_rows_below_the_threshold(tool_ctx, stock):
    r = await call(tool_ctx, "filter_rows", path="stock.csv", column="Quantity", test="below", value="10")
    names = sorted(row[0] for row in r.data["rows"])
    assert names == ["Bolts", "Screws", "Washers"], names
    assert r.data["matched"] == 3 and r.data["checked"] == 4


@pytest.mark.asyncio
async def test_overdue_is_a_date_comparison(tool_ctx, stock):
    r = await call(tool_ctx, "filter_rows", path="stock.csv", column="Due", test="before",
                   value="2026-03-01", file_name="overdue")
    assert sorted(row[0] for row in r.data["rows"]) == ["Bolts", "Washers"]


@pytest.mark.asyncio
async def test_text_tests_work_and_zero_is_not_empty(tool_ctx, stock):
    has = await call(tool_ctx, "filter_rows", path="stock.csv", column="Item", test="contains",
                     value="ut", file_name="c1")
    assert [row[0] for row in has.data["rows"]] == ["Nuts"]
    empty = await call(tool_ctx, "filter_rows", path="stock.csv", column="Quantity", test="empty",
                       file_name="c2")
    assert empty.data["matched"] == 0, "a quantity of 0 is a value, not a blank"


@pytest.mark.asyncio
async def test_matching_nothing_is_an_answer_not_an_error(tool_ctx, stock):
    r = await call(tool_ctx, "filter_rows", path="stock.csv", column="Quantity", test="above",
                   value="1000", file_name="none")
    assert r.ok and r.data["matched"] == 0


# ---------- reconcile_tables (7.18, 13.03, 13.15) ----------

@pytest.mark.asyncio
async def test_a_bank_statement_against_invoices(tool_ctx, folder):
    write_csv(folder / "invoices.csv", ["Ref", "Amount"], [
        ["INV-1", 100], ["INV-2", 250], ["INV-3", 75]])
    write_csv(folder / "bank.csv", ["Ref", "Amount"], [
        ["INV-1", 100], ["INV-2", 200], ["INV-4", 60]])

    r = await call(tool_ctx, "reconcile_tables", left="invoices.csv", right="bank.csv",
                   key="Ref", amount="Amount")
    assert r.data["matched"] == 1                 # INV-1 only
    assert r.data["only_in_first"] == 1           # INV-3 never paid
    assert r.data["only_in_second"] == 1          # INV-4 unexpected
    assert r.data["amounts_differ"] == 1          # INV-2 short by 50
    short = next(row for row in r.data["rows"] if row[0] == "INV-2")
    assert short[2] == 250 and short[3] == 200 and short[4] == 50


@pytest.mark.asyncio
async def test_a_penny_of_rounding_is_not_a_discrepancy(tool_ctx, folder):
    write_csv(folder / "a.csv", ["Ref", "Amount"], [["X", 10.00]])
    write_csv(folder / "b.csv", ["Ref", "Amount"], [["X", 10.005]])
    r = await call(tool_ctx, "reconcile_tables", left="a.csv", right="b.csv", key="Ref",
                   amount="Amount", file_name="rec2")
    assert r.data["amounts_differ"] == 0 and r.data["matched"] == 1


@pytest.mark.asyncio
async def test_two_identical_tables_reconcile_to_nothing_to_do(tool_ctx, folder):
    for n in ("p.csv", "q.csv"):
        write_csv(folder / n, ["Ref", "Amount"], [["A", 1], ["B", 2]])
    r = await call(tool_ctx, "reconcile_tables", left="p.csv", right="q.csv", key="Ref",
                   amount="Amount", file_name="rec3")
    assert r.data["matched"] == 2 and r.data["rows"] == []


# ---------- find_outliers (7.10) ----------

@pytest.mark.asyncio
async def test_the_one_strange_transaction_is_found(tool_ctx, folder):
    rows = [[f"T{i}", 100 + i] for i in range(12)]
    rows.append(["FRAUD", 99000])
    write_csv(folder / "tx.csv", ["Ref", "Amount"], rows)

    r = await call(tool_ctx, "find_outliers", path="tx.csv", column="Amount")
    found = [row[0] for row in r.data["rows"]]
    assert found == ["FRAUD"], f"flagged {found}"
    assert r.data["checked"] == 13


@pytest.mark.asyncio
async def test_one_huge_value_cannot_hide_itself(tool_ctx, folder):
    """Why the median is used and not the mean.

    A mean is dragged by the very row being looked for, far enough that it
    stops looking unusual. The median is not, so this is the case that would
    fail if someone swapped the statistic for a more familiar one.
    """
    rows = [[f"T{i}", 10] for i in range(10)]
    rows.append(["WHALE", 1_000_000])
    write_csv(folder / "whale.csv", ["Ref", "Amount"], rows)
    r = await call(tool_ctx, "find_outliers", path="whale.csv", column="Amount", file_name="w")
    assert [row[0] for row in r.data["rows"]] == ["WHALE"]


@pytest.mark.asyncio
async def test_an_ordinary_column_has_no_outliers(tool_ctx, folder):
    write_csv(folder / "even.csv", ["Ref", "Amount"], [[f"T{i}", 100 + i] for i in range(10)])
    r = await call(tool_ctx, "find_outliers", path="even.csv", column="Amount", file_name="e")
    assert r.data["unusual"] == 0


@pytest.mark.asyncio
async def test_too_few_numbers_says_so_rather_than_guessing(tool_ctx, folder):
    write_csv(folder / "tiny.csv", ["Ref", "Amount"], [["A", 1], ["B", 2]])
    with pytest.raises(ToolError, match="too few"):
        await call(tool_ctx, "find_outliers", path="tiny.csv", column="Amount", file_name="t")


# ---------- the rule they all share ----------

@pytest.mark.asyncio
async def test_none_of_them_change_the_table_they_read(tool_ctx, sales):
    before = sales.read_bytes()
    await call(tool_ctx, "pivot_table", path="sales.csv", group_by="Region", file_name="p9")
    await call(tool_ctx, "filter_rows", path="sales.csv", column="Amount", test="above", value="50", file_name="f9")
    await call(tool_ctx, "find_outliers", path="sales.csv", column="Amount", file_name="o9")
    assert sales.read_bytes() == before, "an input table was modified"


@pytest.mark.asyncio
async def test_a_column_that_is_not_there_names_the_ones_that_are(tool_ctx, sales):
    with pytest.raises(ToolError, match="Region"):
        await call(tool_ctx, "pivot_table", path="sales.csv", group_by="Continent", file_name="x")
