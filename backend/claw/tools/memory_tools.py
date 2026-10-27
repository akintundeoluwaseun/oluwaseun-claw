"""Remembering things about the person, visibly and on purpose.

Three rules shape all of this:

**Only what was said.** S-CLAW stores what the person stated, not what it worked
out about them. "She said she prefers mornings" is a memory; "she seems to
prefer mornings" is a guess wearing a memory's clothes, and guesses that harden
into facts are how an assistant becomes quietly wrong about someone for months.

**Never a secret.** The refusal is in `claw/memory/secrets.py` and runs before
anything is written, not when it is shown. A password, a card number, a token
or a private key is refused with a reason, and S-CLAW says so rather than
storing it quietly.

**Always removable.** Every memory carries where it came from and when, is
listed in Settings, and `forget_this` deletes it. Nothing is remembered that
cannot be seen and undone.
"""

from __future__ import annotations

from pydantic import Field, field_validator

from claw.agent.schemas import Capability
from claw.memory.secrets import looks_like_secret
from claw.permissions.policy import RiskLevel
from claw.tools.base import ToolArgs, ToolContext, ToolError, ToolRegistry, ToolResult, ToolSpec

#: What a memory can be about. A closed list, because "other" becomes a bin.
KINDS = {
    "preference": "how the person likes things done",
    "project": "something they are working on",
    "contact": "a person they deal with",
    "decision": "something that was settled, so it is not re-argued",
    "fact": "something true about their setup or situation",
}
NOT_WRITTEN = "Nothing was written down."


def _db(ctx: ToolContext):
    if ctx.memory_store is None:
        raise ToolError("Memory is not available in this task.")
    return ctx.memory_store


class RememberArgs(ToolArgs):
    kind: str = Field(description="One of: " + ", ".join(KINDS))
    subject: str = Field(min_length=1, max_length=80,
                         description='Who or what it is about — "me", a person, a project')
    fact: str = Field(min_length=3, max_length=500,
                      description="What to remember, in the person's own terms")

    @field_validator("kind")
    @classmethod
    def _known(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in KINDS:
            raise ValueError(f"kind must be one of: {', '.join(KINDS)}")
        return v


def check_remember(args: RememberArgs, ctx: ToolContext) -> None:
    """Refuse a secret before anyone is asked to approve storing it."""
    reason = looks_like_secret(args.fact) or looks_like_secret(args.subject)
    if reason:
        raise ToolError(f"S-CLAW will not remember that: {reason}. {NOT_WRITTEN} "
                        "Passwords and codes stay with you — S-CLAW asks for them when "
                        "they are needed and never keeps them.")


async def remember(args: RememberArgs, ctx: ToolContext) -> ToolResult:
    db = _db(ctx)
    saved = db.remember(args.kind, args.subject, args.fact, "you told S-CLAW", ctx.task_id)
    # Read back, like every other write in this codebase.
    back = next((m for m in db.memories(kind=args.kind) if m["id"] == saved.get("id")), None)
    return ToolResult(
        back is not None,
        f"Noted, under {args.kind} · {args.subject}: “{args.fact}”. "
        "You can see and remove it in Settings → Memory."
        if back else "The memory was written but could not be read back.",
        {"id": saved.get("id"), "kind": args.kind, "subject": args.subject},
        verified=back is not None,
    )


class RecallArgs(ToolArgs):
    about: str = Field(default="", max_length=120,
                       description="A word to look for; empty for everything remembered")
    kind: str = Field(default="", description="Narrow it to one kind, or empty for all")

    @field_validator("kind")
    @classmethod
    def _known(cls, v: str) -> str:
        v = v.strip().lower()
        if v and v not in KINDS:
            raise ValueError(f"kind must be one of: {', '.join(KINDS)}")
        return v


async def recall(args: RecallArgs, ctx: ToolContext) -> ToolResult:
    found = _db(ctx).memories(query=args.about or None, kind=args.kind or None, limit=60)
    if not found:
        where = f" about '{args.about}'" if args.about else ""
        return ToolResult(True, f"Nothing is remembered{where}.", {"memories": []}, verified=True)
    lines = [f"{m['kind']} · {m['subject']}: {m['fact']}" for m in found]
    return ToolResult(
        True, f"{len(found)} thing(s) remembered.",
        {"memories": [{k: m[k] for k in ("id", "kind", "subject", "fact", "updated_at")} for m in found]},
        verified=True,
        # What is remembered was typed by a person and can say anything at all.
        untrusted_text="\n".join(lines),
    )


class ForgetArgs(ToolArgs):
    id: str = Field(min_length=4, max_length=64, description="The memory's id, from recall")


async def forget_this(args: ForgetArgs, ctx: ToolContext) -> ToolResult:
    db = _db(ctx)
    gone = db.forget(args.id)
    if gone is None:
        raise ToolError("There is no memory with that id. Use recall to see what is there.")
    still = any(m["id"] == args.id for m in db.memories(limit=1000))
    return ToolResult(
        not still,
        f"Forgotten: {gone['kind']} · {gone['subject']}: “{gone['fact']}”."
        if not still else "It is still there; nothing was removed.",
        {"id": args.id, "kind": gone["kind"]},
        verified=not still,
    )


def register_memory_tools(reg: ToolRegistry) -> None:
    kinds = ", ".join(f"{k} ({why})" for k, why in KINDS.items())
    reg.register(ToolSpec(
        "remember",
        "Remember something the person has told you about themselves, their work or "
        f"the people they deal with. Kinds: {kinds}. Only what they actually said — "
        "never a conclusion you drew, and never a password, code or card number.",
        Capability.FILES, RiskLevel.LOCAL_WRITE, RememberArgs, remember, precheck=check_remember))
    reg.register(ToolSpec(
        "recall",
        "Look at what is remembered about the person, their projects and their contacts.",
        Capability.FILES, RiskLevel.READ_ONLY, RecallArgs, recall))
    reg.register(ToolSpec(
        "forget_this",
        "Remove one thing from memory, for good.",
        Capability.FILES, RiskLevel.DESTRUCTIVE, ForgetArgs, forget_this))
