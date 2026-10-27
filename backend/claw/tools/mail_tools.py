"""Mail, the way a person does it: open a compose window with it already written.

There is no mail integration here, and that is deliberate. Mail lives in a
browser or in a mail program, S-CLAW already drives both, and an IMAP client
inside S-CLAW would mean holding the password to someone's entire mailbox to do
something the browser already does with the session they are signed into.

So this tool opens a compose window — Gmail, Outlook on the web, or whatever
Windows has set as the default mail program — with the recipients, the subject
and the body already filled in.

**It never sends.** Pressing Send stays a human action, or a separate approved
step. A tool that could both write and send a mail on its own is one bad
sentence away from mailing the wrong person.
"""

from __future__ import annotations

import re
from urllib.parse import quote, urlencode

from pydantic import Field, field_validator

from claw.agent.schemas import Capability
from claw.permissions.policy import RiskLevel
from claw.tools.base import ToolArgs, ToolContext, ToolError, ToolRegistry, ToolResult, ToolSpec

ADDRESS = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$")
MAX_RECIPIENTS = 20
MAX_BODY = 20_000

SERVICES = {
    "gmail": "https://mail.google.com/mail/?view=cm&fs=1&{params}",
    "outlook": "https://outlook.office.com/mail/deeplink/compose?{params}",
    "default": "mailto:{to}?{params}",
}
#: What each service calls the fields, because none of them agree.
FIELDS = {
    "gmail": {"to": "to", "cc": "cc", "bcc": "bcc", "subject": "su", "body": "body"},
    "outlook": {"to": "to", "cc": "cc", "bcc": "bcc", "subject": "subject", "body": "body"},
    "default": {"cc": "cc", "bcc": "bcc", "subject": "subject", "body": "body"},
}
SIGN_IN = re.compile(r"\b(sign in|log in|login|accounts\.google|choose an account|microsoftonline)\b", re.I)


class MailArgs(ToolArgs):
    to: list[str] = Field(min_length=1, max_length=MAX_RECIPIENTS, description="Who it goes to")
    subject: str = Field(default="", max_length=300)
    body: str = Field(default="", max_length=MAX_BODY)
    cc: list[str] = Field(default_factory=list, max_length=MAX_RECIPIENTS)
    bcc: list[str] = Field(default_factory=list, max_length=MAX_RECIPIENTS)
    service: str = Field(default="gmail", description="gmail, outlook, or default for the mail program on this computer")

    @field_validator("to", "cc", "bcc")
    @classmethod
    def _addresses(cls, values: list[str]) -> list[str]:
        out = []
        for raw in values:
            address = raw.strip()
            if not ADDRESS.match(address):
                raise ValueError(f"'{raw}' is not an e-mail address S-CLAW can be sure about. "
                                 "Give the full address, or look it up first.")
            out.append(address)
        return out

    @field_validator("subject")
    @classmethod
    def _one_line(cls, v: str) -> str:
        if "\n" in v or "\r" in v:
            raise ValueError("a subject line is one line")
        return v.strip()

    @field_validator("service")
    @classmethod
    def _known(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in SERVICES:
            raise ValueError(f"service must be one of: {', '.join(SERVICES)}")
        return v


def compose_url(args: MailArgs) -> str:
    names = FIELDS[args.service]
    params: dict[str, str] = {}
    if args.service == "default":
        for key in ("cc", "bcc"):
            if getattr(args, key):
                params[names[key]] = ",".join(getattr(args, key))
        if args.subject:
            params[names["subject"]] = args.subject
        if args.body:
            params[names["body"]] = args.body
        query = urlencode(params, quote_via=quote)
        return SERVICES["default"].format(to=",".join(args.to), params=query).rstrip("?")
    params[names["to"]] = ",".join(args.to)
    for key in ("cc", "bcc"):
        if getattr(args, key):
            params[names[key]] = ",".join(getattr(args, key))
    if args.subject:
        params[names["subject"]] = args.subject
    if args.body:
        params[names["body"]] = args.body
    return SERVICES[args.service].format(params=urlencode(params, quote_via=quote))


def check_compose(args: MailArgs, ctx: ToolContext) -> None:
    if args.service == "default" and ctx.desktop is None:
        raise ToolError("Opening the computer's own mail program needs desktop control, which is "
                        "not available here. Use the gmail or outlook service instead.")


async def compose_mail(args: MailArgs, ctx: ToolContext) -> ToolResult:
    url = compose_url(args)
    everyone = args.to + args.cc + args.bcc
    shown = ", ".join(args.to[:3]) + (f" and {len(args.to) - 3} more" if len(args.to) > 3 else "")

    if args.service == "default":
        await ctx.desktop.call(ctx.desktop.driver.launch, url)
        return ToolResult(
            True,
            f"Opened a new mail to {shown} in this computer's mail program, with the subject and "
            "the message filled in. Nothing has been sent: read it, then press Send yourself.",
            {"service": "default", "to": args.to, "cc": args.cc, "bcc": args.bcc,
             "subject": args.subject, "sent": False},
            verified=False)   # another program owns the window; Claw cannot read it back

    info = await ctx.browser.goto(url)
    title = info.get("title") or ""
    needs_sign_in = bool(SIGN_IN.search(title) or SIGN_IN.search(info.get("url") or ""))
    note = (" It is asking you to sign in first — do that, and the draft will be waiting."
            if needs_sign_in else
            " Nothing has been sent: read it, then press Send yourself.")
    return ToolResult(
        True,
        f"Opened a new {args.service} mail to {shown} with the subject and the message "
        f"filled in.{note}",
        {"service": args.service, "to": args.to, "cc": args.cc, "bcc": args.bcc,
         "subject": args.subject, "url": info.get("url"), "page_title": title,
         "needs_sign_in": needs_sign_in, "recipients": len(everyone), "sent": False},
        # Verified means the compose page really opened, never that a mail went anywhere.
        verified=not needs_sign_in and (info.get("status") or 200) < 400,
    )


def register_mail_tools(reg: ToolRegistry) -> None:
    reg.register(ToolSpec(
        "compose_mail",
        "Open a new e-mail with the recipients, subject and message already written. "
        "Never sends it: the person presses Send.",
        Capability.BROWSER, RiskLevel.EXTERNAL, MailArgs, compose_mail, precheck=check_compose))
