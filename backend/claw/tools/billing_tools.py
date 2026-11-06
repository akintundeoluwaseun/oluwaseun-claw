"""Priced business documents: an invoice, a quotation, a purchase order, a receipt.

Challenges 13.02, 13.07, 13.13 and parts of 13.05 read as four features. They
are one document with a different word at the top and a different name for the
other party - the same line items, the same arithmetic, the same totals block.
Building four tools would put four descriptions in a catalogue a small brain
already spends a quarter of its reading on, which is the mistake
analysis_tools.py was written to avoid. So: one tool, a `kind`.

Nothing here asks the brain for a number. Line totals, the subtotal, tax and
the grand total are computed in Python from the quantities and prices it was
given, written as real spreadsheet formulas as well, and then the saved file is
reopened and the totals recomputed from what is actually on the sheet. A brain
that is wrong about arithmetic - which the benchmark catches constantly -
cannot make the document wrong, and cannot make it *say* it is right.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator

from claw.agent.schemas import Capability
from claw.permissions.policy import RiskLevel
from claw.tools.table_tools import clean_number_text
from claw.tools.base import ToolArgs, ToolContext, ToolError, ToolRegistry, ToolResult, ToolSpec, as_str_list
from claw.tools.table_tools import _fmt, _out, find_folder

#: What each kind calls itself, what it calls the other party, and whether it
#: is a demand for money, an offer, an order, or a record of payment.
KINDS: dict[str, dict[str, str]] = {
    "invoice": {"title": "INVOICE", "party": "Bill to", "ref": "Invoice no.", "terms": "Payment due"},
    "quote": {"title": "QUOTATION", "party": "Prepared for", "ref": "Quotation no.", "terms": "Valid until"},
    "purchase_order": {"title": "PURCHASE ORDER", "party": "Supplier", "ref": "Order no.", "terms": "Required by"},
    "receipt": {"title": "RECEIPT", "party": "Received from", "ref": "Receipt no.", "terms": "Paid on"},
}

#: "2 x A3 poster @ 1200", "A3 poster x 2 @ 1200", "A3 poster, 2, 1200".
#: Three shapes because people write it three ways and a 2B copies whichever
#: shape the person used in their request.
#: A price is often written with its currency in front: N15,000 / ₦15,000 /
#: $1,200 / £99. Leaving this out refused "3 x Banner @ N15,000", which is
#: exactly how a price is written where this is used.
_CUR = r"(?:[₦$£€¥]|N|NGN|USD|GBP|EUR)?\s*"
#: A price may be negative: a discount, a credit note or a deposit already
#: paid is an ordinary line on an invoice, and refusing it meant the whole
#: document could not be made. Written "-1000", "(1,000)" or "(N1,000)",
#: which is how the three of them appear in practice. A quantity is never
#: negative, so only the price group allows it.
_SIGN = r"(?:-|\u2212)?\s*"
_PRICE = r"(?P<price>\(?\s*" + _SIGN + r"(?:[₦$£€¥]|N|NGN|USD|GBP|EUR)?\s*" + _SIGN + r"[\d.,]+\s*\)?)"
_ITEM_PATTERNS = (
    re.compile(r"^\s*(?P<qty>[\d.,]+)\s*[x*]\s*(?P<desc>.+?)\s*(?:@|at)\s*" + _PRICE + r"\s*$", re.I),
    re.compile(r"^\s*(?P<desc>.+?)\s*[x*]\s*(?P<qty>[\d.,]+)\s*(?:@|at)\s*" + _PRICE + r"\s*$", re.I),
    re.compile(r"^\s*(?P<desc>[^,;|]+)\s*[,;|]\s*(?P<qty>[\d.,]+)\s*[,;|]\s*" + _PRICE + r"\s*$"),
    re.compile(r"^\s*(?P<desc>.+?)\s*(?:@|at)\s*" + _PRICE + r"\s*$", re.I),   # qty defaults to 1
)


def _number(raw: str, *, allow_negative: bool = False) -> float:
    """A quantity or price as written: 1,200 / 1200.50 / N1,200 / (N1,000).

    Signs come from clean_number_text, the same reader the table tools use, so
    "(1,000)" means -1000 here exactly as it does in a ledger column. A
    quantity that comes out negative is refused rather than quietly flipped:
    "-2 x poster" is a mistake, not a credit note.
    """
    text, negative = clean_number_text(str(raw))
    if text.startswith("-"):
        negative, text = True, text[1:]
    cleaned = re.sub(r"[^\d.]", "", text)
    if not cleaned or cleaned.count(".") > 1:
        raise ToolError(f"'{raw.strip()}' is not a number Claw can use.")
    value = float(cleaned)
    if negative and not allow_negative:
        raise ToolError(f"'{raw.strip()}' cannot be a negative number here.")
    return -value if negative else value


#: A quantity with a sign in front of it. Without this guard the line fell
#: through to the last pattern, which defaults the quantity to 1 and keeps the
#: rest as the description, so "-2 x poster @ 100" became one "2 x poster" at
#: 100 - an invoice short by 100, with nothing on it looking wrong. A sign on
#: a quantity is a typo, and the person is the only one who knows which.
_SIGNED_QTY = re.compile(r"^\s*[-\u2212+]\s*[\d.,]+\s*[x*]", re.I)


def parse_item(text: str) -> tuple[str, float, float]:
    """One line of a document: description, quantity, unit price."""
    if _SIGNED_QTY.match(text):
        raise ToolError(
            f"'{text.strip()[:60]}' has a sign in front of the quantity. Write the quantity "
            "plainly, and put the minus on the price if the line is a discount: "
            '"1 x Loyalty discount @ -1000".')
    for pattern in _ITEM_PATTERNS:
        m = pattern.match(text)
        if m:
            qty = _number(m.group("qty")) if "qty" in m.groupdict() and m.group("qty") else 1.0
            desc = m.group("desc").strip(" -–—\t")
            if not desc:
                break
            return desc, qty, _number(m.group("price"), allow_negative=True)
    raise ToolError(
        f"Claw could not read '{text.strip()[:60]}' as a line. Write each one as "
        '"2 x A3 poster @ 1200" - how many, what it is, and the price for one.')


class DocumentArgs(ToolArgs):
    kind: str = Field(default="invoice", description="invoice, quote, purchase_order or receipt")
    to: str = Field(min_length=1, max_length=120, description="Who it is for (the customer or supplier)")
    items: list[str] = Field(min_length=1, max_length=60,
                             description='Lines, each "2 x A3 poster @ 1200"')
    from_name: str | None = Field(default=None, max_length=120, description="Your business name")
    reference: str | None = Field(default=None, max_length=40, description="Document number")
    tax_percent: float = Field(default=0.0, ge=0, le=100, description="VAT or sales tax, e.g. 7.5")
    currency: str = Field(default="", max_length=8, description='e.g. "N", "$", "GBP"')
    due_in_days: int = Field(default=0, ge=0, le=365, description="Days until payment is due")
    note: str | None = Field(default=None, max_length=300, description="Anything to add at the bottom")
    folder: str | None = Field(default=None, max_length=500)
    file_name: str | None = Field(default=None, max_length=100)

    @field_validator("items", mode="before")
    @classmethod
    def _lines(cls, v):
        return as_str_list(v, limit=60, extra_separators="\n;")

    @field_validator("kind")
    @classmethod
    def _known(cls, v):
        k = (v or "invoice").strip().lower().replace(" ", "_").replace("-", "_")
        aliases = {"quotation": "quote", "estimate": "quote", "bill": "invoice",
                   "po": "purchase_order", "order": "purchase_order"}
        k = aliases.get(k, k)
        if k not in KINDS:
            raise ValueError(f"kind must be one of: {', '.join(KINDS)}")
        return k


def _rows(items: list[str]) -> list[tuple[str, float, float, float]]:
    out = []
    for raw in items:
        desc, qty, price = parse_item(raw)
        out.append((desc, qty, price, round(qty * price, 2)))
    return out


async def make_document(args: DocumentArgs, ctx: ToolContext) -> ToolResult:
    """Write a priced document and check its own arithmetic from the saved file."""
    import openpyxl  # noqa: PLC0415
    from openpyxl.styles import Alignment, Border, Font, Side  # noqa: PLC0415
    from openpyxl.worksheet.properties import PageSetupProperties  # noqa: PLC0415

    words = KINDS[args.kind]
    lines = _rows(args.items)
    subtotal = round(sum(r[3] for r in lines), 2)
    tax = round(subtotal * args.tax_percent / 100, 2)
    total = round(subtotal + tax, 2)
    cur = (args.currency or "").strip()
    money = f"{cur}#,##0.00" if cur else "#,##0.00"

    folder = find_folder(ctx, args.folder)
    name = args.file_name or f"{args.kind}-{re.sub(r'[^A-Za-z0-9]+', '-', args.to).strip('-')[:40] or 'document'}"
    out = _out(ctx, folder, name, "xlsx")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = words["title"].title()
    bold, head = Font(bold=True), Font(bold=True, size=18)
    thin = Border(bottom=Side(style="thin"))

    ws["A1"] = words["title"]
    ws["A1"].font = head
    row = 3
    if args.from_name:
        ws[f"A{row}"] = "From"; ws[f"A{row}"].font = bold; ws[f"B{row}"] = args.from_name; row += 1
    ws[f"A{row}"] = words["party"]; ws[f"A{row}"].font = bold; ws[f"B{row}"] = args.to; row += 1
    ws[f"A{row}"] = words["ref"]; ws[f"A{row}"].font = bold
    ws[f"B{row}"] = args.reference or f"{args.kind[:3].upper()}-{date.today():%Y%m%d}"; row += 1
    ws[f"A{row}"] = "Date"; ws[f"A{row}"].font = bold; ws[f"B{row}"] = f"{date.today():%d %B %Y}"; row += 1
    if args.due_in_days:
        ws[f"A{row}"] = words["terms"]; ws[f"A{row}"].font = bold
        ws[f"B{row}"] = f"{date.today() + timedelta(days=args.due_in_days):%d %B %Y}"; row += 1

    row += 1
    header_row = row
    for col, title in zip("ABCD", ("Description", "Quantity", "Unit price", "Amount")):
        c = ws[f"{col}{row}"]
        c.value, c.font, c.border = title, bold, thin
    row += 1
    first_item = row
    for desc, qty, price, amount in lines:
        ws[f"A{row}"] = desc
        ws[f"B{row}"] = qty
        ws[f"C{row}"] = price
        # A real formula as well as the value, so the sheet stays correct if the
        # person edits a quantity - and so the number is not just asserted.
        ws[f"D{row}"] = f"=B{row}*C{row}"
        ws[f"C{row}"].number_format = ws[f"D{row}"].number_format = money
        row += 1
    last_item = row - 1

    row += 1
    def total_line(label: str, value: float, formula: str, strong: bool = False):
        nonlocal row
        ws[f"C{row}"] = label
        ws[f"C{row}"].font = bold
        ws[f"C{row}"].alignment = Alignment(horizontal="right")
        ws[f"D{row}"] = formula
        ws[f"D{row}"].number_format = money
        if strong:
            ws[f"D{row}"].font = bold
            ws[f"D{row}"].border = Border(top=Side(style="thin"), bottom=Side(style="double"))
        row += 1

    total_line("Subtotal", subtotal, f"=SUM(D{first_item}:D{last_item})")
    if args.tax_percent:
        total_line(f"Tax {_fmt(args.tax_percent)}%", tax, f"=D{row - 1}*{args.tax_percent / 100}")
        total_line("Total", total, f"=D{row - 2}+D{row - 1}", strong=True)
    else:
        total_line("Total", total, f"=SUM(D{first_item}:D{last_item})", strong=True)
    if args.note:
        row += 1
        ws[f"A{row}"] = args.note
    for col, width in zip("ABCD", (46, 12, 16, 16)):
        ws.column_dimensions[col].width = width

    # Make it print on one page across. Those four columns come to about 8.7
    # inches, and A4 portrait leaves roughly 6.8 once the margins are taken
    # off, so the Amount column - every figure on the invoice - went onto a
    # second page on its own. The file was correct and the printout was not,
    # which is the worse of the two for a document whose whole purpose is to
    # be sent to somebody. Found by rendering one and looking at it.
    # fitToHeight 0 means "as many pages down as it needs": a 60-line invoice
    # must not be squeezed to illegibility to fit one page.
    ws.print_area = f"A1:D{row}"
    ws.page_setup.orientation = "portrait"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    wb.save(out)

    # ---- check it from the file, not from the variables above ----
    check = openpyxl.load_workbook(out, read_only=True)
    sheet = check[check.sheetnames[0]]
    saved = [[c for c in r] for r in sheet.iter_rows(min_row=header_row, values_only=True)]
    check.close()
    body = [r for r in saved[1:] if r and isinstance(r[1], (int, float)) and isinstance(r[2], (int, float))]
    recomputed = round(sum(float(r[1]) * float(r[2]) for r in body), 2)
    ok = len(body) == len(lines) and abs(recomputed - subtotal) < 0.01
    note = "" if ok else (f"The saved file adds up to {recomputed}, not {subtotal}" if body
                          else "The saved file has no priced lines")

    ctx.memory.outputs.append({"path": str(out), "kind": "spreadsheet", "verified": ok, "note": note})
    summary = (f"{words['title'].title()} for {args.to}: {len(lines)} line(s), "
               f"total {cur}{_fmt(total)}" + (f" (incl. {cur}{_fmt(tax)} tax)" if tax else "")
               + f". Saved to {out} and the totals were checked by reopening it.")
    detail = "\n".join(f"{q:g} x {d} @ {p:g} = {a:g}" for d, q, p, a in lines)
    return ToolResult(ok, summary if ok else f"{summary} WARNING: {note}.",
                      {"path": str(out), "kind": args.kind, "lines": len(lines),
                       "subtotal": subtotal, "tax": tax, "total": total},
                      verified=ok, untrusted_text=detail)


def register_billing_tools(reg: ToolRegistry) -> None:
    reg.register(ToolSpec(
        "make_document",
        "Make an invoice, quotation, purchase order or receipt with line items and totals, "
        "and check the arithmetic by reopening the file.",
        Capability.DATA, RiskLevel.LOCAL_WRITE, DocumentArgs, make_document))
