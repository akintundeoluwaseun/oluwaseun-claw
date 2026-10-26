"""TechDesk (the user's shop-management app): prepare, cancel and record a sale through its screen.

Chosen with the user (Oct 2026): Claw operates TechDesk-enterprise like a person would, through
Windows UI Automation — the same way it uses WhatsApp — and never reads TechDesk's code, database or
storage. Everything it reports (product names, prices, totals, receipt numbers) is read from the screen.

Safety:
- Preparing a sale never submits it. Recording it is a separate step that always asks the user first,
  and only goes ahead if the screen still shows the same items and total that were approved.
- An ambiguous or missing product stops with a question; nothing is guessed.
- A PIN screen stops Claw: PINs are for the user to type.

NOT YET RUN AGAINST THE REAL APP: the button and field names below ("Sales", "New Sale", "Search
products", "Qty", "Total", "Complete Sale") are best guesses from TechDesk's screens and are matched
loosely. Confirm them on Windows with docs/WINDOWS_ACCEPTANCE.md → Test F, on test data only.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import asdict, dataclass, field

from claw.computer.driver import ControlInfo, DesktopDriver, WindowInfo

CONTROL_LIMIT = 600
CLICKABLE = {"Button", "Hyperlink", "ListItem", "MenuItem", "TabItem", "TreeItem", "DataItem", "Text"}

NAV_SALES = re.compile(r"^\s*(sales|point of sale|pos|sales \(pos\))\s*$", re.I)
NEW_SALE = re.compile(r"^\s*\+?\s*(new sale|add sale|create sale|new transaction|start sale)\s*$", re.I)
SEARCH_FIELD = re.compile(r"search|product|item|find", re.I)
QTY_FIELD = re.compile(r"^\s*(qty|quantity)\b", re.I)
TOTAL_LABEL = re.compile(r"^\s*(grand\s+)?total\b", re.I)
SUBMIT = re.compile(r"^\s*(complete|save|record|finish|confirm|checkout|check out|submit)( the)?\s*(sale|order|transaction|payment)?\s*$", re.I)
CANCEL = re.compile(r"^\s*(cancel|close|discard)\b", re.I)
PIN_SCREEN = re.compile(r"enter (your )?pin|pin sign[- ]in|unlock with pin|sign in with pin", re.I)
RECEIPT = re.compile(r"\b(invoice|receipt)\s*(no\.?|number|#)?\s*[:#]?\s*([A-Z0-9-]{3,})", re.I)
MONEY = re.compile(r"(?:₦|NGN|N)\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{2}))?", re.I)


class TechDeskProblem(Exception):
    def __init__(self, message: str, state: str = "failed"):
        super().__init__(message)
        self.message = message
        self.state = state


@dataclass
class SaleLine:
    product: str
    unit_price: float
    quantity: int

    @property
    def amount(self) -> float:
        return self.unit_price * self.quantity


@dataclass
class PreparedSale:
    lines: list[SaleLine] = field(default_factory=list)
    displayed_total: float | None = None

    @property
    def expected_total(self) -> float:
        return sum(l.amount for l in self.lines)

    def totals_match(self) -> bool:
        return self.displayed_total is not None and abs(self.displayed_total - self.expected_total) < 0.5

    def as_dict(self) -> dict:
        return {"lines": [asdict(l) | {"amount": l.amount} for l in self.lines], "displayed_total": self.displayed_total,
                "expected_total": self.expected_total, "totals_match": self.totals_match()}


def money(text: str) -> float | None:
    m = MONEY.search(text or "")
    if not m:
        return None
    return float(m.group(1).replace(",", "")) + (float("0." + m.group(2)) if m.group(2) else 0.0)


def naira(v: float | None) -> str:
    return "unknown" if v is None else f"₦{v:,.0f}" if v == int(v) else f"₦{v:,.2f}"


def find_window(windows: list[WindowInfo]) -> WindowInfo | None:
    hits = [w for w in windows if "techdesk" in w.title.lower() or w.process.lower().startswith("techdesk")]
    return hits[0] if hits else None


def _first(controls: list[ControlInfo], pattern: re.Pattern, roles: set[str] | None = None) -> ControlInfo | None:
    for c in controls:
        if (roles is None or c.role in roles) and c.enabled and pattern.search(c.name or ""):
            return c
    return None


def _words(s: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) > 1]


def product_candidates(controls: list[ControlInfo], query: str) -> list[tuple[ControlInfo, str, float]]:
    """Rows on screen whose text contains every word of the query and shows a price.
    The price may be in the row's own name or in the Text right after it."""
    want = [w.rstrip("s") for w in _words(query)]
    out = []
    for i, c in enumerate(controls):
        if c.role not in CLICKABLE or c.role == "Text" and c.name and money(c.name) and not _words(re.sub(MONEY, "", c.name)):
            continue
        name = (c.name or "").strip()
        words = [w.rstrip("s") for w in _words(re.sub(MONEY, "", name))]
        if not name or not all(any(x.startswith(w) or w.startswith(x) for x in words) for w in want):
            continue
        if SEARCH_FIELD.search(name) and c.role != "ListItem":
            continue
        price = money(name)
        if price is None:
            for nxt in controls[i + 1:i + 4]:
                price = money(nxt.name)
                if price is not None:
                    break
        if price is None:
            continue
        clean = re.sub(r"\s*[-–·|,]?\s*" + MONEY.pattern, "", name, flags=re.I).strip(" -–·|,")
        out.append((c, clean, price))
    # The same product can appear as a row and as its own Text label: keep one per name.
    seen, unique = set(), []
    for c, n, p in out:
        if n.lower() not in seen:
            seen.add(n.lower())
            unique.append((c, n, p))
    return unique


def displayed_total(controls: list[ControlInfo]) -> float | None:
    for i, c in enumerate(controls):
        if TOTAL_LABEL.search(c.name or "") and not re.search(r"sub\s*total", c.name or "", re.I):
            v = money(c.name)
            if v is not None:
                return v
            for nxt in controls[i + 1:i + 3]:
                v = money(nxt.name) or money(nxt.value)
                if v is not None:
                    return v
    return None


class TechDesk:
    """Drives one TechDesk window through a DesktopSession (`call` runs driver methods on its thread)."""

    def __init__(self, call, driver: DesktopDriver):
        self.call = call
        self.d = driver
        self.win: WindowInfo | None = None

    async def controls(self) -> list[ControlInfo]:
        return await self.call(self.d.controls, self.win.handle, CONTROL_LIMIT)

    async def attach(self, launch_target=None) -> None:
        """launch_target: None (don't open TechDesk) or a callable returning the program to start."""
        ok, why = await self.call(self.d.available)
        if not ok:
            raise TechDeskProblem(why, "unavailable")
        self.win = find_window(await self.call(self.d.list_windows))
        if self.win is None and launch_target is not None:
            await self.call(self.d.launch, launch_target())
            for _ in range(40):
                await asyncio.sleep(0.5)
                self.win = find_window(await self.call(self.d.list_windows))
                if self.win:
                    await asyncio.sleep(2)  # splash screen
                    break
        if self.win is None:
            raise TechDeskProblem("TechDesk isn't open." if launch_target is None else "TechDesk didn't open within 20 seconds.", "not_open")
        await self.call(self.d.focus_window, self.win.handle)
        c = await self.controls()
        if PIN_SCREEN.search(" ".join(x.name for x in c)):
            raise TechDeskProblem("TechDesk is asking for a PIN. Please sign in yourself (Claw never types PINs), then ask again.", "pin")

    async def click(self, pattern: re.Pattern, what: str, roles=CLICKABLE) -> None:
        c = _first(await self.controls(), pattern, roles)
        if c is None:
            raise TechDeskProblem(f"Couldn't find {what} in TechDesk. Nothing was changed.")
        await self.call(self.d.invoke, c.index)
        await asyncio.sleep(0.8)

    async def open_new_sale(self) -> None:
        controls = await self.controls()
        if _first(controls, NEW_SALE) is None:  # not on the Sales page yet
            await self.click(NAV_SALES, "the Sales page")
        await self.click(NEW_SALE, "the New Sale button")

    async def add_item(self, product: str, quantity: int, sale: PreparedSale) -> None:
        controls = await self.controls()
        search = _first(controls, SEARCH_FIELD, {"Edit", "ComboBox"})
        if search is None:
            raise TechDeskProblem("Couldn't find the product search box in the new sale form.")
        await self.call(self.d.set_text, search.index, product)
        await asyncio.sleep(0.8)
        controls = await self.controls()
        found = product_candidates(controls, product)
        if not found:
            raise TechDeskProblem(f"TechDesk shows no product matching '{product}'. Which product did you mean?", "missing")
        if len(found) > 1:
            names = "; ".join(f"{n} ({naira(p)})" for _, n, p in found[:6])
            raise TechDeskProblem(f"Several products match '{product}': {names}. Which one should Claw use?", "ambiguous")
        row, name, price = found[0]
        before_qty = [c.index for c in controls if c.role in ("Edit", "Spinner") and QTY_FIELD.search(c.name or "")]
        await self.call(self.d.invoke, row.index)
        await asyncio.sleep(0.6)
        controls = await self.controls()
        qty_fields = [c for c in controls if c.role in ("Edit", "Spinner") and QTY_FIELD.search(c.name or "")]
        if not qty_fields:
            raise TechDeskProblem(f"Added {name}, but couldn't find its quantity box.")
        qty = qty_fields[-1] if len(qty_fields) > len(before_qty) else qty_fields[-1]
        await self.call(self.d.set_text, qty.index, str(quantity))
        await asyncio.sleep(0.4)
        shown = (await self.call(self.d.read, qty.index)).strip()
        if shown != str(quantity):
            raise TechDeskProblem(f"Set the quantity of {name} to {quantity}, but TechDesk shows '{shown}'.")
        sale.lines.append(SaleLine(name, price, quantity))

    async def read_total(self, sale: PreparedSale) -> None:
        sale.displayed_total = displayed_total(await self.controls())

    async def submit(self) -> str | None:
        """Press the complete/save button; return a receipt or invoice number only if TechDesk shows one."""
        await self.click(SUBMIT, "the button that completes the sale", {"Button"})
        await asyncio.sleep(1.2)
        text = " ".join(c.name for c in await self.controls())
        m = RECEIPT.search(text)
        return m.group(3) if m else None

    async def form_open(self) -> bool:
        return _first(await self.controls(), SUBMIT, {"Button"}) is not None

    async def cancel(self) -> bool:
        await self.click(CANCEL, "the Cancel button of the sale form", {"Button"})
        return not await self.form_open()

    async def sales_list_has(self, total: float, products: list[str]) -> bool:
        """After recording: does the Sales page now list a sale with this total and these products?"""
        controls = await self.controls()
        if _first(controls, NAV_SALES) and _first(controls, NEW_SALE) is None:
            await self.click(NAV_SALES, "the Sales page")
            controls = await self.controls()
        for i, c in enumerate(controls):
            window = " ".join(x.name for x in controls[i:i + 6])
            if any(abs((money(x.name) or -1) - total) < 0.5 for x in controls[i:i + 6]) and all(
                    p.lower().split()[0] in window.lower() for p in products):
                return True
        return False
