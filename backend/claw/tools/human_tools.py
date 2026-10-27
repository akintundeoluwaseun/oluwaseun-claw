"""Stopping to ask for the one thing only the person can do.

Every site eventually asks for something S-CLAW must not have: a password, a
code texted to a phone, a QR code to scan, a CAPTCHA, a bank's confirmation
screen. The wrong answers are to type something invented, to give up quietly, or
to sit on a login page until the step times out.

The right answer is this: say exactly what is needed, send a notification so the
person knows even if they have walked away, wait, and carry on from where it
stopped once they say it is done.

S-CLAW never types the credential, never reads it, and never stores it. The
person does that themselves in the window that is already open.
"""

from __future__ import annotations

from pydantic import Field, field_validator

from claw.agent.schemas import Capability
from claw.permissions.policy import RiskLevel
from claw.tools.base import ToolArgs, ToolContext, ToolError, ToolRegistry, ToolResult, ToolSpec

#: Things a person might be asked to do themselves, for wording and for the icon.
KINDS = ("sign in", "two-factor code", "captcha", "payment confirmation",
         "permission dialog", "something else")

# If any of these appear in what the model wants to say, it is asking for the
# secret itself rather than asking the person to type it. Refused outright.
FORBIDDEN = ("tell me your password", "what is your password", "send me the code",
             "type your password here", "give me your pin", "share your otp")


class PauseArgs(ToolArgs):
    what_is_needed: str = Field(
        min_length=3, max_length=300,
        description='What the person has to do, e.g. "sign in to Instagram in the browser window"')
    why: str = Field(default="", max_length=300,
                     description="What S-CLAW was doing when it got stuck")
    kind: str = Field(default="something else", description=f"One of: {', '.join(KINDS)}")

    @field_validator("kind")
    @classmethod
    def _known(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in KINDS:
            raise ValueError(f"kind must be one of: {', '.join(KINDS)}")
        return v

    @field_validator("what_is_needed", "why")
    @classmethod
    def _not_asking_for_the_secret(cls, v: str) -> str:
        low = v.lower()
        for phrase in FORBIDDEN:
            if phrase in low:
                raise ValueError(
                    "S-CLAW must never ask for a password, PIN or code. Ask the person to "
                    "type it themselves in the window that is open.")
        return v


async def pause_for_me(args: PauseArgs, ctx: ToolContext) -> ToolResult:
    if ctx.ask_user is None:
        raise ToolError("There is nobody to ask: this is not running as a task.")

    answered = await ctx.ask_user({
        "kind": "needs_you",                 # not an allow/deny: the app words it differently
        "tool": "pause_for_me",
        "title": "S-CLAW needs you",
        "description": args.what_is_needed,
        "detail": args.why,
        "what": args.kind,
        # So nothing downstream mistakes this for a request to do something risky.
        "risk": "read_only",
    })

    if answered is None:
        return ToolResult(
            False,
            f"Waited for you to {args.what_is_needed}, but nobody answered, so the task stopped "
            "where it was. Nothing was skipped and nothing was guessed.",
            {"kind": args.kind, "answered": None}, verified=False)
    if answered is False:
        return ToolResult(
            False,
            f"You chose not to {args.what_is_needed}, so the task stopped there.",
            {"kind": args.kind, "answered": False}, verified=False)
    return ToolResult(
        True,
        f"You said that is done ({args.what_is_needed}). Carrying on from where it stopped.",
        {"kind": args.kind, "answered": True}, verified=True)


def register_human_tools(reg: ToolRegistry) -> None:
    # Read-only on purpose: this tool changes nothing. It waits. Giving it a higher
    # risk level would mean asking the person for permission to ask the person.
    reg.register(ToolSpec(
        "pause_for_me",
        "Stop and ask the person to do something only they can do - sign in, enter a code "
        "sent to their phone, pass a CAPTCHA - then carry on once they say it is done.",
        Capability.REASONING, RiskLevel.READ_ONLY, PauseArgs, pause_for_me))
