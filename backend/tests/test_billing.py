"""Invoices, quotations, purchase orders and receipts (13.02, 13.07, 13.13).

Four challenges, one document: the same line items, the same arithmetic, the
same totals block, with a different word at the top and a different name for
the other party. Four tools would have put four descriptions in a catalogue a
small brain already spends a quarter of its reading on.

The point of these tests is that no number comes from the brain. The brain
supplies "2 x A3 poster @ 1200"; every total is computed in Python, written as
a real spreadsheet formula too, and then checked by reopening the saved file
and adding it up again from what is actually on the sheet.
"""

from pathlib import Path

import openpyxl
import pytest

from claw.tools.billing_tools import KINDS, parse_item
from tests.test_phase_a import call


def saved(ctx):
    return Path(ctx.settings.permissions.authorized_folders[0])


def values(path):
    wb = openpyxl.load_workbook(path)
    rows = [list(r) for r in wb[wb.sheetnames[0]].iter_rows(values_only=True)]
    wb.close()
    return rows


# ---------- reading a line ----------
def test_the_three_ways_people_write_a_line():
    assert parse_item("2 x A3 poster @ 1200") == ("A3 poster", 2.0, 1200.0)
    assert parse_item("A3 poster x 2 @ 1200") == ("A3 poster", 2.0, 1200.0)
    assert parse_item("A3 poster, 2, 1200") == ("A3 poster", 2.0, 1200.0)


def test_one_of_something_needs_no_quantity():
    assert parse_item("Logo design @ 50000") == ("Logo design", 1.0, 50000.0)


def test_thousands_separators_and_currency_marks_survive():
    assert parse_item("3 x Banner @ N15,000") == ("Banner", 3.0, 15000.0)
    assert parse_item("2 x Frame @ 1,250.50") == ("Frame", 2.0, 1250.5)


def test_a_line_nobody_can_read_says_how_to_write_one():
    with pytest.raises(Exception) as exc:
        parse_item("some banners probably")
    assert "2 x A3 poster @ 1200" in str(exc.value)


# ---------- the document ----------
async def test_an_invoice_adds_up_and_is_checked_from_the_file(tool_ctx):
    r = await call(tool_ctx, "make_document", kind="invoice", to="Riverside Hotel",
                   items=["3 x Banner @ 15000", "2 x A3 poster @ 1200", "Logo design @ 50000"],
                   from_name="Ilorin Print Works", currency="N")
    assert r.ok and r.verified
    assert r.data["subtotal"] == 3 * 15000 + 2 * 1200 + 50000 == 97400
    assert r.data["total"] == 97400 and r.data["tax"] == 0

    rows = values(Path(r.data["path"]))
    flat = [c for row in rows for c in row if c is not None]
    assert "INVOICE" in flat and "Riverside Hotel" in flat and "Ilorin Print Works" in flat
    # the amount column is a real formula, so editing a quantity keeps it right
    assert any(isinstance(c, str) and c.startswith("=B") and "*C" in c for c in flat)
    assert any(isinstance(c, str) and c.startswith("=SUM(D") for c in flat)


async def test_tax_is_added_and_stated(tool_ctx):
    r = await call(tool_ctx, "make_document", to="Ada", items=["4 x Mug @ 2500"], tax_percent=7.5)
    assert r.data["subtotal"] == 10000
    assert r.data["tax"] == 750 and r.data["total"] == 10750
    assert "tax" in r.summary.lower()


async def test_each_kind_says_what_it_is(tool_ctx):
    for kind, word in (("invoice", "INVOICE"), ("quote", "QUOTATION"),
                       ("purchase_order", "PURCHASE ORDER"), ("receipt", "RECEIPT")):
        r = await call(tool_ctx, "make_document", kind=kind, to="Ada", items=["1 x Thing @ 100"])
        flat = [c for row in values(Path(r.data["path"])) for c in row if c is not None]
        assert word in flat, kind
        assert KINDS[kind]["party"] in flat, kind


async def test_the_words_people_use_for_each_kind(tool_ctx):
    for said, word in (("quotation", "QUOTATION"), ("estimate", "QUOTATION"),
                       ("PO", "PURCHASE ORDER"), ("bill", "INVOICE")):
        r = await call(tool_ctx, "make_document", kind=said, to="Ada", items=["1 x Thing @ 100"])
        flat = [c for row in values(Path(r.data["path"])) for c in row if c is not None]
        assert word in flat, said


async def test_a_kind_claw_does_not_make_is_refused_by_name(tool_ctx):
    with pytest.raises(Exception) as exc:
        await call(tool_ctx, "make_document", kind="contract", to="Ada", items=["1 x Thing @ 100"])
    assert "invoice" in str(exc.value)


async def test_one_document_per_customer(tool_ctx):
    # 13.02: "generate invoices for multiple customers" is this tool, once each.
    for who, items in (("Riverside Hotel", ["2 x Banner @ 15000"]),
                       ("Ado Mall", ["5 x Flyer @ 300"]),
                       ("Fajuyi Suites", ["1 x Signboard @ 80000"])):
        r = await call(tool_ctx, "make_document", to=who, items=items)
        assert r.ok and r.verified
    made = sorted(p.name for p in saved(tool_ctx).glob("invoice-*.xlsx"))
    assert len(made) == 3, made
    assert any("Riverside" in n for n in made) and any("Ado" in n for n in made)


async def test_nothing_is_overwritten(tool_ctx):
    for _ in range(2):
        await call(tool_ctx, "make_document", to="Ada", items=["1 x Thing @ 100"])
    assert len(list(saved(tool_ctx).glob("invoice-Ada*.xlsx"))) == 2


async def test_a_due_date_appears_only_when_asked_for(tool_ctx):
    plain = await call(tool_ctx, "make_document", to="Ada", items=["1 x Thing @ 100"])
    dated = await call(tool_ctx, "make_document", to="Ada", items=["1 x Thing @ 100"], due_in_days=30)
    flat = lambda p: [c for row in values(Path(p)) for c in row if c is not None]
    assert "Payment due" not in flat(plain.data["path"])
    assert "Payment due" in flat(dated.data["path"])


async def test_the_detail_the_person_sees_lists_every_line(tool_ctx):
    r = await call(tool_ctx, "make_document", to="Ada",
                   items=["3 x Banner @ 15000", "2 x Mug @ 2500"])
    assert "3 x Banner @ 15000 = 45000" in r.untrusted_text
    assert "2 x Mug @ 2500 = 5000" in r.untrusted_text


def test_a_price_written_with_its_currency():
    # "3 x Banner @ N15,000" is how a price is written where this is used, and
    # it was refused until the pattern allowed the mark in front of the number.
    assert parse_item("3 x Banner @ N15,000")[2] == 15000.0
    assert parse_item("2 x Frame @ ₦1,250.50")[2] == 1250.5
    assert parse_item("Logo @ $500")[2] == 500.0
    assert parse_item("Design x 2 @ GBP 99") == ("Design", 2.0, 99.0)
