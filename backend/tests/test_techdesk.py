"""Phase C — TechDesk sale workflow through the app's screen, against the TEST DOUBLE desktop.

The TechDesk stand-in imitates TechDesk's Sales screens as a GUESS; the real app is not touched here
(Test F is BLOCKED — docs/WINDOWS_ACCEPTANCE.md). No real transaction is ever created by these tests.
"""

import pytest

from claw.integrations.techdesk import money, product_candidates
from claw.computer.driver import ControlInfo
from claw.permissions.policy import Decision, PermissionPolicy, RiskLevel
from tests.test_desktop import act, call
from tests.test_phase_a import finish, run


def test_money_and_candidates():
    assert money("₦3,500") == 3500 and money("Total: N12,000.50") == 12000.5 and money("NGN 700") == 700 and money("Qty") is None
    cs = [ControlInfo(0, "ListItem", "Phone charger (Type-C)"), ControlInfo(1, "Text", "₦3,500"),
          ControlInfo(2, "ListItem", "USB cable - ₦1,500")]
    assert [(n, p) for _, n, p in product_candidates(cs, "type-c phone chargers")] == [("Phone charger (Type-C)", 3500)]
    assert [(n, p) for _, n, p in product_candidates(cs, "usb cable")] == [("USB cable", 1500)]
    assert product_candidates(cs, "laptop") == []


async def test_f_prepare_cancel_then_record_with_approval(desk_ctx, fake_server):
    fake = desk_ctx.fake
    fake.add_techdesk()
    desk_ctx.policy = PermissionPolicy({RiskLevel.LOCAL_WRITE: Decision.ALLOW, RiskLevel.EXTERNAL: Decision.ALLOW}, [])
    # 1. prepare, then cancel: nothing recorded
    out, approvals = await run(desk_ctx, fake_server, [
        act("prepare_techdesk_sale", items=[{"product": "Type-C phone charger", "quantity": 2}]),
        act("cancel_techdesk_sale"),
        finish("Cancelled."),
    ], task="Open TechDesk and prepare a sale for two phone chargers, then cancel it")
    assert out.status == "completed" and [s["outcome"] for s in out.steps] == ["verified", "verified"], out.summary()
    assert approvals == [] and fake.td["sales"] == [] and fake.td["form"] is None
    # 2. prepare again; the user approves recording the exact total
    out, approvals = await run(desk_ctx, fake_server, [
        act("prepare_techdesk_sale", items=[{"product": "Type-C phone charger", "quantity": 2}]),
        act("record_techdesk_sale", expected_total=7000, summary="2 × Phone charger (Type-C) = ₦7,000"),
        finish("Recorded."),
    ], task="Prepare a sale for two Type-C phone chargers and record it")
    assert out.status == "completed", out.summary()
    prep = out.steps[0]
    assert prep["outcome"] == "verified" and "₦7,000" in prep["detail"]
    assert [a["tool"] for a in approvals] == ["record_techdesk_sale"] and approvals[0]["risk"] == "destructive"
    assert fake.td["sales"] == [("INV-0001", "Phone charger (Type-C) x2", 7000)]
    rec = out.steps[1]
    assert rec["outcome"] == "verified" and "INV-0001" in rec["detail"] and "found it in the Sales list" in rec["detail"]


async def test_declining_approval_records_nothing(desk_ctx, fake_server):
    desk_ctx.fake.add_techdesk()
    desk_ctx.policy = PermissionPolicy({RiskLevel.LOCAL_WRITE: Decision.ALLOW}, [])
    out, approvals = await run(desk_ctx, fake_server, [
        act("prepare_techdesk_sale", items=[{"product": "USB cable", "quantity": 3}]),
        act("record_techdesk_sale", expected_total=4500, summary="3 × USB cable"),
    ], task="Sell three USB cables", approve=False)
    assert desk_ctx.fake.td["sales"] == [] and out.status == "stopped"
    assert [a["tool"] for a in approvals] == ["record_techdesk_sale"]
    assert desk_ctx.fake.td["form"] is not None  # the prepared sale is left on screen, unrecorded


async def test_ambiguous_and_missing_products_ask_instead_of_guessing(desk_ctx):
    desk_ctx.fake.add_techdesk()
    r = await call(desk_ctx, "prepare_techdesk_sale", items=[{"product": "phone charger", "quantity": 2}])
    assert not r.ok and r.data["state"] == "ambiguous"
    assert "Phone charger (Type-C) (₦3,500)" in r.summary and "Phone charger (iPhone) (₦4,500)" in r.summary
    r = await call(desk_ctx, "prepare_techdesk_sale", items=[{"product": "laptop battery", "quantity": 1}])
    assert not r.ok and r.data["state"] == "missing" and "Which product" in r.summary


async def test_total_mismatch_blocks_recording(desk_ctx):
    from claw.tools.base import ToolError

    desk_ctx.fake.add_techdesk(total_bug=True)  # TechDesk shows ₦500 less than prices × quantities
    r = await call(desk_ctx, "prepare_techdesk_sale", items=[{"product": "USB cable", "quantity": 2}])
    assert r.ok and not r.verified and "₦2,500" in r.summary and "₦3,000" in r.summary
    with pytest.raises(ToolError, match="didn't match"):
        await call(desk_ctx, "record_techdesk_sale", expected_total=2500, summary="2 × USB cable")
    assert desk_ctx.fake.td["sales"] == []


async def test_record_needs_a_prepared_sale_and_the_same_total(desk_ctx):
    from claw.tools.base import ToolError

    desk_ctx.fake.add_techdesk()
    with pytest.raises(ToolError, match="Prepare the sale first"):
        await call(desk_ctx, "record_techdesk_sale", expected_total=3000, summary="test sale")
    await call(desk_ctx, "prepare_techdesk_sale", items=[{"product": "USB cable", "quantity": 2}])
    with pytest.raises(ToolError, match="not the one prepared"):
        await call(desk_ctx, "record_techdesk_sale", expected_total=9999, summary="test sale")
    # the screen changes after approval (someone edits the quantity): nothing is recorded
    fake = desk_ctx.fake
    fake.td["form"][0]["qty"] = 5
    fake._td_render()
    r = await call(desk_ctx, "record_techdesk_sale", expected_total=3000, summary="2 × USB cable")
    assert not r.ok and "NOT recorded" in r.summary and fake.td["sales"] == []


async def test_pin_screen_stops_claw(desk_ctx):
    desk_ctx.fake.add_techdesk(pin=True)
    r = await call(desk_ctx, "prepare_techdesk_sale", items=[{"product": "USB cable", "quantity": 1}])
    assert not r.ok and r.data["state"] == "pin" and "never types PINs" in r.summary


async def test_opens_techdesk_from_start_menu_or_explains(desk_ctx, tmp_path):
    from claw.tools.base import ToolError

    with pytest.raises(ToolError, match="no TechDesk shortcut"):
        await call(desk_ctx, "prepare_techdesk_sale", items=[{"product": "USB cable", "quantity": 1}])
    (desk_ctx.start_menu_dirs[0] / "TechDesk.lnk").write_text("shortcut")
    r = await call(desk_ctx, "prepare_techdesk_sale", items=[{"product": "USB cable", "quantity": 1}])
    assert r.ok and r.verified and any("techdesk" in t.lower() for t in desk_ctx.fake.launched)
