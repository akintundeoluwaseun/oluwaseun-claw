"""Working a page by refs (OpenClaw's operating style), against the local test site in a real browser."""

import pytest

from claw.permissions.policy import RiskLevel
from claw.tools.base import ToolError
from claw.tools.registry import build_registry

REG = build_registry()


async def call(ctx, name, **args):
    spec = REG.get(name)
    a = spec.parse_args(args)
    if spec.precheck:
        spec.precheck(a, ctx)
    return await spec.handler(a, ctx)


def ref_of(ctx, role, name):
    return next(r for r, v in ctx.browser.page_refs.items() if v["role"] == role and v["name"].startswith(name))


async def test_look_type_choose_and_click_by_ref(tool_ctx, site):
    await call(tool_ctx, "open_url", url=site.base_url + "/form")
    r = await call(tool_ctx, "look_at_page", only_controls=True)
    assert r.ok and 'button "Submit registration"' in r.untrusted_text and "[ref=e" in r.untrusted_text
    name = ref_of(tool_ctx, "textbox", "Full name")
    t = await call(tool_ctx, "type_in", ref=name, text="Ada Lovelace")
    assert t.ok and t.verified
    c = await call(tool_ctx, "choose_option", ref=ref_of(tool_ctx, "combobox", "Country"), option="Nigeria")
    assert c.ok and "Chose 'Nigeria'" in c.summary
    # a submit button asks first; a plain link does not
    submit = ref_of(tool_ctx, "button", "Submit registration")
    spec = REG.get("click")
    assert spec.effective_risk(spec.parse_args({"ref": submit}), tool_ctx) == RiskLevel.EXTERNAL
    link = ref_of(tool_ctx, "link", "Download price list")
    assert spec.effective_risk(spec.parse_args({"ref": link}), tool_ctx) == RiskLevel.READ_ONLY


async def test_passwords_and_unknown_refs_are_refused(tool_ctx, site):
    await call(tool_ctx, "open_url", url=site.base_url + "/form")
    await call(tool_ctx, "look_at_page", only_controls=True)
    pw = ref_of(tool_ctx, "textbox", "Password")
    with pytest.raises(ToolError, match="password"):
        await call(tool_ctx, "type_in", ref=pw, text="secret")
    with pytest.raises(ToolError, match="no e999"):
        await call(tool_ctx, "click", ref="e999")


async def test_a_click_returns_the_new_page(tool_ctx, site):
    await call(tool_ctx, "open_url", url=site.base_url + "/")
    await call(tool_ctx, "look_at_page")
    first_link = next(r for r, v in tool_ctx.browser.page_refs.items() if v["role"] == "link")
    r = await call(tool_ctx, "click", ref=first_link)
    assert r.ok and "Page after the action" in r.untrusted_text
