"""Working a web page by refs: look at it, then click / type / choose by ref.

The operating style is OpenClaw's (MIT): one snapshot tool that lists what is on the
page with refs, and actions that take a ref and hand back the page as it is afterwards,
so the brain never acts on a page it has not seen. See claw/browser/snapshot.py.

Safety is S-CLAW's own and unchanged: password, card and code fields are refused, a
button whose words mean paying, sending, deleting or publishing asks first (or is
treated as destructive), and everything read from the page is untrusted text.
"""

from __future__ import annotations

import re

from pydantic import Field

from claw.agent.schemas import Capability
from claw.browser import snapshot as snap
from claw.permissions.policy import RiskLevel
from claw.tools.base import ToolArgs, ToolContext, ToolError, ToolRegistry, ToolResult, ToolSpec

B = Capability.BROWSER
_REF = re.compile(r"^@?(?:ref=)?((?:f\d+)?e\d+)$", re.I)
_DESTRUCTIVE = re.compile(r"\b(pay|buy|purchase|place order|checkout|check out|delete|remove|transfer|send money|"
                          r"withdraw|unsubscribe|cancel (?:my )?(?:account|subscription))\b", re.I)
_EXTERNAL = re.compile(r"\b(send|submit|post|publish|share|confirm|sign up|register|book|reserve|apply|"
                       r"save|update|upload|add to cart|subscribe|follow|like|comment|reply)\b", re.I)
_SECRET = re.compile(r"password|passcode|\bpin\b|card number|cvv|cvc|security code|one[- ]time|otp", re.I)


def _ref(raw: str) -> str:
    m = _REF.match(raw.strip())
    if not m:
        raise ToolError(f"'{raw}' is not a ref. Use one like e12 from the last look_at_page.")
    return m.group(1)


def _known(ctx: ToolContext, ref: str) -> dict:
    refs = getattr(ctx.browser, "page_refs", None) or {}
    if ref not in refs:
        raise ToolError(f"There is no {ref} on the last snapshot. Call look_at_page first and use a ref from it.")
    return refs[ref]


async def _take(ctx: ToolContext, interactive: bool, max_chars: int = 6000) -> snap.Snapshot:
    page = await ctx.browser.page()
    raw = await page.aria_snapshot(mode="ai", timeout=10000)
    s = snap.build(raw, interactive=interactive, max_chars=max_chars)
    ctx.browser.page_refs = s.refs
    ctx.browser.seen_urls.update(u for u in s.urls if u.startswith(("http://", "https://")))
    return s


async def _after(ctx: ToolContext, what: str) -> ToolResult:
    page = await ctx.browser.page()
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=8000)
    except Exception:  # noqa: BLE001 - a click that loads nothing is normal
        pass
    s = await _take(ctx, interactive=True, max_chars=3500)
    title = await page.title()
    return ToolResult(True, f"{what} The page is now '{title or page.url}'.", {"url": page.url, "refs": len(s.refs)},
                      True, untrusted_text=f"Page after the action ({page.url}):\n{s.text}")


# ---------- look_at_page ----------
class LookArgs(ToolArgs):
    only_controls: bool = Field(default=False, description="true: only buttons, links and fields; false: text too")


async def look_at_page(args: LookArgs, ctx: ToolContext) -> ToolResult:
    page = await ctx.browser.page()
    s = await _take(ctx, args.only_controls)
    return ToolResult(True, f"Looked at '{await page.title() or page.url}': {len(s.refs)} element(s) with refs"
                      + (" (the page was too long; the end was cut)" if s.truncated else "") + ".",
                      {"url": page.url, "refs": len(s.refs), "truncated": s.truncated}, True,
                      untrusted_text=f"{page.url}\n{s.text}")


# ---------- click ----------
class ClickArgs(ToolArgs):
    ref: str = Field(min_length=2, max_length=20, description="A ref from look_at_page, e.g. e12")


def click_risk(args: ClickArgs, ctx: ToolContext) -> RiskLevel:
    try:
        el = _known(ctx, _ref(args.ref))
    except ToolError:
        return RiskLevel.READ_ONLY            # the pre-check refuses it anyway
    name = el.get("name", "")
    if _DESTRUCTIVE.search(name):
        return RiskLevel.DESTRUCTIVE
    if el.get("role") in ("button", "menuitem") and _EXTERNAL.search(name):
        return RiskLevel.EXTERNAL
    return RiskLevel.READ_ONLY


def click_context(args: ClickArgs, ctx: ToolContext) -> str:
    el = _known(ctx, _ref(args.ref))
    return f"Clicks the {el.get('role')} \"{el.get('name') or args.ref}\" on the page."


def check_click(args: ClickArgs, ctx: ToolContext) -> None:
    _known(ctx, _ref(args.ref))


async def click(args: ClickArgs, ctx: ToolContext) -> ToolResult:
    ref = _ref(args.ref)
    el = _known(ctx, ref)
    page = await ctx.browser.page()
    await page.locator(f"aria-ref={ref}").click(timeout=10000)
    return await _after(ctx, f"Clicked {el.get('role')} \"{el.get('name') or ref}\".")


# ---------- type ----------
class TypeArgs(ToolArgs):
    ref: str = Field(min_length=2, max_length=20, description="A text box ref from look_at_page")
    text: str = Field(max_length=4000)
    press_enter: bool = Field(default=False, description="Press Enter after typing (often submits a search)")


def check_type(args: TypeArgs, ctx: ToolContext) -> None:
    el = _known(ctx, _ref(args.ref))
    if _SECRET.search(el.get("name", "")):
        raise ToolError("That is a password, card or code field. Claw never types those; please enter it yourself.")


def type_risk(args: TypeArgs, ctx: ToolContext) -> RiskLevel:
    # Typing a search is looking; typing elsewhere and pressing Enter can send a form.
    try:
        el = _known(ctx, _ref(args.ref))
    except ToolError:
        return RiskLevel.LOCAL_WRITE
    if el.get("role") == "searchbox" or re.search(r"search", el.get("name", ""), re.I):
        return RiskLevel.READ_ONLY
    return RiskLevel.EXTERNAL if args.press_enter else RiskLevel.LOCAL_WRITE


async def type_text_into(args: TypeArgs, ctx: ToolContext) -> ToolResult:
    ref = _ref(args.ref)
    check_type(args, ctx)
    page = await ctx.browser.page()
    loc = page.locator(f"aria-ref={ref}")
    kind = await loc.evaluate("el => (el.type || '').toLowerCase() + ' ' + (el.autocomplete || '')")
    if "password" in kind or re.search(r"cc-|one-time-code", kind):
        raise ToolError("That is a password, card or code field. Claw never types those; please enter it yourself.")
    await loc.fill(args.text, timeout=10000)
    got = await loc.input_value(timeout=5000)
    if args.press_enter:
        await loc.press("Enter")
        return await _after(ctx, f"Typed into {ref} and pressed Enter.")
    return ToolResult(got == args.text, f"Typed into {ref}" + ("" if got == args.text else f", but the box shows '{got[:80]}'") + ".",
                      {"ref": ref}, got == args.text)


# ---------- choose ----------
class ChooseArgs(ToolArgs):
    ref: str = Field(min_length=2, max_length=20, description="A dropdown (combobox) ref from look_at_page")
    option: str = Field(min_length=1, max_length=200, description="The option's visible text")


async def choose(args: ChooseArgs, ctx: ToolContext) -> ToolResult:
    ref = _ref(args.ref)
    _known(ctx, ref)
    page = await ctx.browser.page()
    loc = page.locator(f"aria-ref={ref}")
    try:
        await loc.select_option(label=args.option, timeout=8000)
    except Exception:  # noqa: BLE001 - not a native <select>: open it and click the option
        await loc.click(timeout=8000)
        await page.get_by_role("option", name=args.option).first.click(timeout=8000)
    return await _after(ctx, f"Chose '{args.option}' in {ref}.")


def register(reg: ToolRegistry) -> None:
    R = RiskLevel.READ_ONLY
    reg.register(ToolSpec("look_at_page", "List what is on the current web page, each button, link and field with a ref "
                          "like e12. Use the refs with click, type_in and choose_option.", B, R, LookArgs, look_at_page))
    reg.register(ToolSpec("click", "Click a button or link on the current web page by its ref from look_at_page.",
                          B, R, ClickArgs, click, precheck=check_click, risk_for=click_risk, context_for=click_context))
    reg.register(ToolSpec("type_in", "Type into a text box on the current web page by its ref; never passwords or codes.",
                          B, RiskLevel.LOCAL_WRITE, TypeArgs, type_text_into, precheck=check_type, risk_for=type_risk))
    reg.register(ToolSpec("choose_option", "Choose an option in a dropdown on the current web page by its ref.",
                          B, RiskLevel.LOCAL_WRITE, ChooseArgs, choose, precheck=check_click))
