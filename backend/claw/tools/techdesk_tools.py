"""TechDesk tools: prepare a sale (never submits), cancel it, record it (always asks first)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from claw.agent.schemas import Capability
from claw.computer.launcher import choose_app
from claw.integrations.techdesk import PreparedSale, TechDesk, TechDeskProblem, naira
from claw.permissions.policy import RiskLevel
from claw.tools.base import NoArgs, ToolArgs, ToolContext, ToolError, ToolRegistry, ToolResult, ToolSpec


class Item(BaseModel):
    product: str = Field(min_length=2, max_length=120, description="Product as the user named it, e.g. 'phone charger'")
    quantity: int = Field(ge=1, le=999)


class PrepareArgs(ToolArgs):
    items: list[Item] = Field(min_length=1, max_length=20)


def _td(ctx: ToolContext) -> TechDesk:
    if ctx.desktop is None:
        raise ToolError("Desktop control is not available in this session.")
    return TechDesk(ctx.desktop.call, ctx.desktop.driver)


def _launch_target(ctx: ToolContext) -> str:
    try:
        return choose_app("TechDesk", ctx.start_menu_dirs).target
    except ToolError:
        raise ToolError("TechDesk isn't open and no TechDesk shortcut was found in the Start menu. Open TechDesk, then ask again.")


def _lines_text(sale: PreparedSale) -> str:
    rows = [f"- {l.quantity} × {l.product} @ {naira(l.unit_price)} = {naira(l.amount)}" for l in sale.lines]
    return "\n".join(rows + [f"Expected total: {naira(sale.expected_total)}", f"TechDesk shows: {naira(sale.displayed_total)}"])


async def prepare_sale(args: PrepareArgs, ctx: ToolContext) -> ToolResult:
    td = _td(ctx)
    sale = PreparedSale()
    try:
        await td.attach(lambda: _launch_target(ctx))
        await td.open_new_sale()
        for item in args.items:
            await td.add_item(item.product, item.quantity, sale)
        await td.read_total(sale)
    except TechDeskProblem as exc:
        partial = f" (Added so far: {', '.join(l.product for l in sale.lines)}; the sale was NOT recorded.)" if sale.lines else ""
        return ToolResult(False, exc.message + partial, {"state": exc.state, **sale.as_dict()}, verified=True)
    ctx.memory.app_state["techdesk_sale"] = sale.as_dict()
    ok = sale.totals_match()
    if sale.displayed_total is None:
        note = "Couldn't read the total TechDesk shows, so the sale is not checked."
    elif not ok:
        note = f"TechDesk shows {naira(sale.displayed_total)} but the prices × quantities add up to {naira(sale.expected_total)}. Please check before recording."
    else:
        note = f"Total {naira(sale.displayed_total)} matches the prices shown."
    return ToolResult(True, f"Prepared the sale in TechDesk (not recorded yet). {note}",
                      {"state": "prepared", **sale.as_dict()}, verified=ok, untrusted_text=_lines_text(sale))


async def cancel_sale(args: NoArgs, ctx: ToolContext) -> ToolResult:
    td = _td(ctx)
    try:
        await td.attach(None)
        closed = await td.cancel()
    except TechDeskProblem as exc:
        return ToolResult(False, exc.message, {"state": exc.state}, verified=True)
    ctx.memory.app_state.pop("techdesk_sale", None)
    return ToolResult(closed, "Cancelled the sale; nothing was recorded." if closed else "Pressed Cancel, but the sale form is still open.",
                      {"cancelled": closed}, verified=closed)


class RecordArgs(ToolArgs):
    expected_total: float = Field(gt=0, le=1e12, description="The total the user approved (from prepare_techdesk_sale)")
    summary: str = Field(min_length=3, max_length=500, description="Items and quantities, shown to the user for approval")


def check_record(args: RecordArgs, ctx: ToolContext) -> None:
    prepared = ctx.memory.app_state.get("techdesk_sale")
    if not prepared:
        raise ToolError("Prepare the sale first (prepare_techdesk_sale) so the user can see the items and total.")
    if not prepared["totals_match"]:
        raise ToolError("The total TechDesk showed didn't match the prices, so Claw won't record this sale. Please check it in TechDesk.")
    if abs(prepared["displayed_total"] - args.expected_total) >= 0.5:
        raise ToolError(f"That total ({naira(args.expected_total)}) is not the one prepared ({naira(prepared['displayed_total'])}).")


async def record_sale(args: RecordArgs, ctx: ToolContext) -> ToolResult:
    """Runs only after the user approved recording this sale."""
    check_record(args, ctx)
    prepared = ctx.memory.app_state["techdesk_sale"]
    td = _td(ctx)
    try:
        await td.attach(None)
        now = PreparedSale()
        await td.read_total(now)
        if now.displayed_total is None or abs(now.displayed_total - args.expected_total) >= 0.5:
            return ToolResult(False, f"The sale on screen changed (TechDesk now shows {naira(now.displayed_total)}), so it was NOT recorded.",
                              {"recorded": False}, verified=True)
        receipt = await td.submit()
        still_open = await td.form_open()
        listed = await td.sales_list_has(args.expected_total, [l["product"] for l in prepared["lines"]])
    except TechDeskProblem as exc:
        return ToolResult(False, exc.message + " Check TechDesk to see whether the sale was saved.", {"state": exc.state}, verified=False)
    ctx.memory.app_state.pop("techdesk_sale", None)
    ok = (not still_open) and listed
    msg = f"Recorded the sale of {naira(args.expected_total)} in TechDesk"
    msg += f" (receipt/invoice {receipt}, as shown by TechDesk)" if receipt else ""
    msg += " and found it in the Sales list." if ok else ", but couldn't find it in the Sales list afterwards. Please check TechDesk."
    return ToolResult(True, msg, {"recorded": True, "receipt": receipt, "verified_in_list": listed}, verified=ok)


def register_techdesk_tools(reg: ToolRegistry) -> None:
    D = Capability.DESKTOP
    reg.register(ToolSpec("prepare_techdesk_sale",
                          "In TechDesk, start a new sale, find each product, enter quantities, and read the prices and total from the screen. Does NOT record the sale.",
                          D, RiskLevel.LOCAL_WRITE, PrepareArgs, prepare_sale))
    reg.register(ToolSpec("cancel_techdesk_sale", "Cancel the sale form open in TechDesk without recording it.",
                          D, RiskLevel.LOCAL_WRITE, NoArgs, cancel_sale))
    reg.register(ToolSpec("record_techdesk_sale",
                          "Record (complete) the prepared TechDesk sale. Always asks the user first; only if the screen still shows the approved total.",
                          D, RiskLevel.DESTRUCTIVE, RecordArgs, record_sale, precheck=check_record))
