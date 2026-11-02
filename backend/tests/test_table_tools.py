"""Milestone 3: combine tables, remove duplicates, totals across files, charts - on real files, re-read afterwards."""

from pathlib import Path

import openpyxl
import pytest

from claw.tools.table_tools import read_table, to_number
from tests.test_phase_a import call


def bench(tool_ctx, name):
    root = Path(tool_ctx.settings.permissions.authorized_folders[0])
    d = root / "S-CLAW Bench" / name
    d.mkdir(parents=True)
    return d


def branches(d):
    (d / "lagos.csv").write_text("date,product,amount\n2026-01-03,Rice,\"12,000\"\n2026-01-05,Beans,8000\n", encoding="utf-8")
    (d / "abuja.csv").write_text("﻿Date;Product;Amount\n2026-01-04;rice;₦15,000\n2026-01-09;Garri;4000\n2026-01-11;Beans;6000\n", encoding="utf-8")
    (d / "ibadan.csv").write_text("DATE,PRODUCT, amount \n2026-01-02,Garri,3500\n", encoding="utf-8")


def test_money_as_people_write_it():
    assert to_number("₦12,000") == 12000 and to_number("$1,250.50") == 1250.5 and to_number("(300)") == -300
    assert to_number("N/A") is None and to_number("") is None


async def test_combine_matches_columns_and_finds_the_folder_by_name(tool_ctx):
    d = bench(tool_ctx, "Branch sales")
    branches(d)
    r = await call(tool_ctx, "combine_tables", folder="Branch sales", file_name="all branches")   # name only, no path
    assert r.ok and r.verified and r.data["rows"] == 6
    head, rows = read_table(d / "all branches.xlsx")
    assert head == ["Source", "Date", "Product", "Amount"]
    assert {row[0] for row in rows} == {"Lagos", "Abuja", "Ibadan"}
    amounts = [row[3] for row in rows]
    assert sum(amounts) == 48500 and all(isinstance(a, int) for a in amounts)    # real numbers in Excel, not text


async def test_totals_across_files_and_per_group(tool_ctx):
    d = bench(tool_ctx, "Branch sales 2")
    branches(d)
    r = await call(tool_ctx, "table_totals", folder="Branch sales 2", group_by="product")
    assert r.data["total"] == 48500 and r.data["rows"] == 6 and "48,500" in r.summary
    assert r.data["groups"] == {"Rice": 27000, "Beans": 14000, "Garri": 7500}


async def test_duplicates_by_email_or_phone_and_original_untouched(tool_ctx):
    d = bench(tool_ctx, "CRM export")
    src = d / "customers.csv"
    text = ("name,phone,email\nAdaeze Okafor,08031112222,ada@example.com\nTunde Bello,08035556666,tunde@example.com\n"
            "adaeze okafor,0803 111 2222,ADA@example.com\nKemi Adeyemi,08037778888,kemi@example.com\n"
            "Tunde Bello,+2348035556666,tunde.b@example.com\n")
    src.write_text(text, encoding="utf-8")
    r = await call(tool_ctx, "remove_duplicates", path="customers.csv", folder="CRM export")
    assert r.verified and r.data["rows_after"] == 3 and r.data["removed"] == 2
    assert src.read_text(encoding="utf-8") == text
    _, rows = read_table(d / "customers clean.csv")
    assert [row[0] for row in rows] == ["Adaeze Okafor", "Tunde Bello", "Kemi Adeyemi"]


async def test_chart_with_live_totals(tool_ctx):
    d = bench(tool_ctx, "Charts")
    branches(d)
    await call(tool_ctx, "combine_tables", folder=str(d), file_name="sales")
    r = await call(tool_ctx, "add_chart", path="sales.xlsx", folder="Charts", label_column="product", value_column="amount")
    assert r.verified and r.data["points"] == 3
    wb = openpyxl.load_workbook(d / "sales with chart.xlsx")
    assert len(wb["Chart"]._charts) == 1 and str(wb["Chart"]["B2"].value).startswith("=SUMIF(")


async def test_two_folders_with_one_name_are_not_guessed(tool_ctx):
    bench(tool_ctx, "Data")
    (Path(tool_ctx.settings.permissions.authorized_folders[0]) / "Other" / "Data").mkdir(parents=True)
    from claw.tools.base import ToolError
    with pytest.raises(ToolError, match="2 folders called 'data'"):
        await call(tool_ctx, "table_totals", folder="Data")


def test_table_requests_get_the_table_tools():
    from claw.agent.executor import fitting_tools
    from claw.tools.registry import build_registry
    r = build_registry()
    assert fitting_tools("Combine the three CSV files in the 'Branch sales' folder into one spreadsheet", r)[0] == "combine_tables"
    assert "remove_duplicates" in fitting_tools("customers.csv has duplicate customers, save a clean copy", r)
    assert "table_totals" in fitting_tools("What is the total amount of all sales in the three CSV files?", r)


async def test_saving_finds_the_folder_the_brain_half_named(tool_ctx):
    d = bench(tool_ctx, "Flyers")
    r = await call(tool_ctx, "write_text_file", file_name="note.txt", text="hi", folder="S-CLAW Bench/Flyers")
    assert r.ok and (d / "note.txt").is_file()
    r = await call(tool_ctx, "list_folder", folder="Flyers")
    assert r.ok and "note.txt" in r.untrusted_text
