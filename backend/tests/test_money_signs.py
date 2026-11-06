"""Both number readers, held to one rule about signs and currency.

Found by probing summarize_column with the kind of column a real ledger has.
A refund written "(2,000)" came back as +2000, so the total was out by 4,000 -
and the tool still reported itself verified. table_tools.to_number had read
brackets correctly all along, which is the part that makes it a real bug
rather than a missing feature: the same column, totalled by table_totals and
summarized by summarize_column, gave two different answers, and nothing in
the app could tell you which to believe.

Separately, to_number returned None for "N2,000". Naira is written with a
bare N constantly - invoices, WhatsApp, exported statements - so the row was
not totalled wrongly, it was dropped, and the total came out short with
nothing to say so.

Both read through claw.tools.table_tools.clean_number_text now. These tests
exist to stop them drifting apart again.
"""

import pytest

from claw.tools.table_tools import clean_number_text, to_number
from claw.tools.text_tools import _number

# (cell, value) - what every reader of money must agree this is worth.
AGREED = [
    ("1000", 1000.0),
    ("1,000", 1000.0),
    ("-500", -500.0),
    ("₦3000", 3000.0),
    ("N2,000", 2000.0),          # bare N: naira
    ("N15,000", 15000.0),
    ("$12.50", 12.5),
    ("NGN 450", 450.0),
    ("(2000)", -2000.0),         # accounting brackets: a debit
    ("(N1,500)", -1500.0),
    ("(₦2,500.50)", -2500.5),
    ("1500-", -1500.0),          # trailing minus, as some exports write it
    ("−750", -750.0),       # MINUS SIGN, not a hyphen
    ("－300", -300.0),       # fullwidth
]

NOT_A_NUMBER = ["", "   ", "N/A", "n/a", "-", "--", "TBC", "pending"]


@pytest.mark.parametrize("cell,value", AGREED)
def test_both_readers_agree(cell, value):
    assert _number(cell) == value, f"text_tools._number read {cell!r} as {_number(cell)}"
    assert to_number(cell) == value, f"table_tools.to_number read {cell!r} as {to_number(cell)}"


@pytest.mark.parametrize("cell", NOT_A_NUMBER)
def test_neither_reader_invents_a_number(cell):
    assert _number(cell) is None, f"_number found {_number(cell)} in {cell!r}"
    assert to_number(cell) is None, f"to_number found {to_number(cell)} in {cell!r}"


def test_a_bracketed_total_is_not_off_by_double():
    """The arithmetic the bug actually broke."""
    ledger = ["N10,000", "(2,500)", "N1,500", "(N500)"]
    assert sum(_number(x) for x in ledger) == 8500
    assert sum(to_number(x) for x in ledger) == 8500


def test_an_en_dash_is_a_range_not_a_negative():
    """Deliberately not treated as a minus: "10-20" in a cell means a range."""
    text, negative = clean_number_text("10–20")
    assert not negative
    assert "−" not in text


def test_a_letter_n_that_is_not_naira_is_left_alone():
    assert _number("N/A") is None
    assert to_number("N/A") is None
    # A word beginning with N must not lose its N and become a number.
    assert to_number("November") is None


def test_the_shared_cleaner_reports_the_sign_separately():
    assert clean_number_text("(1,250)") == ("1250", True)
    assert clean_number_text("N1,250") == ("1250", False)
