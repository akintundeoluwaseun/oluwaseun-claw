"""Tool definitions.

The model never runs code. It can only name a registered tool and supply
arguments; the arguments are validated against the tool's Pydantic model
before anything happens, and the tool's risk level decides whether it runs,
asks the user, or is refused.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, ValidationError

from claw.agent.schemas import Capability
from claw.config import Settings, describe_validation_error
from claw.permissions.policy import canonical_path
from claw.permissions.policy import PermissionPolicy, RiskLevel

if TYPE_CHECKING:
    from claw.browser.session import BrowserSession
    from claw.computer.driver import DesktopSession


class ToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class NoArgs(ToolArgs):
    pass


@dataclass
class ToolResult:
    ok: bool
    summary: str  # one line, shown to the user and the model
    data: dict[str, Any] = field(default_factory=dict)
    verified: bool = False  # True only when the tool checked that the effect really happened
    untrusted_text: str = ""  # page/document content: fed to the model as data, never as instructions


class ToolError(Exception):
    """An expected failure with a message fit for the user and the model."""

    def __init__(self, message: str, *, transient: bool = False):
        super().__init__(message)
        self.message = message
        self.transient = transient


@dataclass
class TaskMemory:
    """What Claw has actually seen and made during one task (used to stop invented facts)."""

    seen_text: list[str] = field(default_factory=list)
    seen_files: set[str] = field(default_factory=set)
    outputs: list[dict[str, Any]] = field(default_factory=list)
    read_untrusted: bool = False  # anything from the web, a file or an app has been read
    injection_seen: bool = False  # that content tried to give Claw instructions
    app_state: dict[str, Any] = field(default_factory=dict)  # per-app working state a tool sets up and a later tool completes

    def corpus(self) -> str:
        return "\n".join(self.seen_text)

    def note_file(self, path: str | Path) -> None:
        """Record that Claw really opened this file."""
        self.seen_files.add(str(canonical_path(path)))

    def saw_file(self, location: str) -> bool:
        """Was this file opened in this task, however the path is spelled?"""
        if location in self.seen_files:
            return True
        try:
            return str(canonical_path(location)) in self.seen_files
        except (OSError, ValueError):  # not a usable path (e.g. a URL, or too long)
            return False


@dataclass
class ToolContext:
    settings: Settings
    policy: PermissionPolicy
    data_dir: Path
    browser: "BrowserSession"
    task_id: str
    desktop: "DesktopSession | None" = None
    # Reads an image with a model that can see (online Google AI, or the offline seeing model).
    vision: Callable[[bytes, str], Awaitable[str]] | None = None
    start_menu_dirs: list[Path] | None = None  # tests only; None = the real Start menu
    memory: TaskMemory = field(default_factory=TaskMemory)
    llm: Any = None  # the brain adapter, for tools that summarise long documents in chunks
    docs: Any = None  # PdfPipeline (OCR-aware PDF reading with a cache)
    # Stop and ask the person for something only they can do - a password, a code
    # sent to their phone, a CAPTCHA. Returns True to carry on, False to stop, and
    # None when nobody answered in time. None outside a running task.
    ask_user: Callable[[dict[str, Any]], Awaitable[bool | None]] | None = None
    #: Recent tasks, for the daily briefing. A callable rather than the database
    #: itself: a tool can read what happened, never change it.
    recent_tasks: Callable[[int], list[dict[str, Any]]] | None = None
    #: What S-CLAW remembers about the person. None when memory is unavailable.
    memory_store: Any = None


Handler = Callable[[ToolArgs, ToolContext], Awaitable[ToolResult]]
Precheck = Callable[[ToolArgs, ToolContext], None]
RiskFn = Callable[[ToolArgs, ToolContext], RiskLevel]
#: One sentence for the approval card: what approving this would actually do,
#: in terms of what is on screen rather than in terms of the arguments.
ContextFn = Callable[[ToolArgs, ToolContext], str]

# Words that turn a click into a consequential action that always needs the user's OK.
CONSEQUENTIAL = re.compile(
    r"\b(send|delete|remove|erase|discard|buy|purchase|pay|checkout|place order|order now|transfer|"
    r"submit|post|publish|uninstall|format|empty|sign out|log out|unsubscribe|confirm)\b",
    re.I,
)


def escalate_by_label(label: str, base: RiskLevel) -> RiskLevel:
    return RiskLevel.DESTRUCTIVE if CONSEQUENTIAL.search(label or "") else base


@dataclass
class ToolSpec:
    name: str
    description: str
    capability: Capability
    risk: RiskLevel
    args_model: type[ToolArgs]
    handler: Handler
    # A sensitive scope overrides the risk decision with its own setting (e.g. browser history).
    sensitive_scope: str | None = None
    # Cheap checks run BEFORE asking the user, so nobody approves a step that cannot work.
    precheck: Precheck | None = None
    # Some actions are riskier than their tool's default (e.g. clicking a button labelled "Send").
    risk_for: RiskFn | None = None
    # Some arguments do not say what they do. ["enter"] is one of them.
    context_for: ContextFn | None = None

    def effective_risk(self, args: ToolArgs, ctx: ToolContext) -> RiskLevel:
        return self.risk_for(args, ctx) if self.risk_for else self.risk

    def approval_context(self, args: ToolArgs, ctx: ToolContext) -> str:
        """What approving this would do, for the person deciding.

        Never raises: a missing sentence costs some clarity, an exception here
        would cost the approval itself.
        """
        if self.context_for is None:
            return ""
        try:
            return self.context_for(args, ctx) or ""
        except Exception:   # noqa: BLE001 - an explanation is never worth a crash
            return ""

    def parse_args(self, raw: Any) -> ToolArgs:
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise ToolError(f"Arguments for {self.name} must be an object.")
        try:
            return self.args_model.model_validate(raw)
        except ValidationError as exc:
            raise ToolError(f"Invalid arguments for {self.name}: " + "; ".join(describe_validation_error(exc))) from exc

    def for_model(self) -> dict[str, Any]:
        schema = self.args_model.model_json_schema()
        schema.pop("title", None)
        return {"name": self.name, "description": self.description, "risk": self.risk.value, "args": schema}


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"tool {spec.name} registered twice")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def all(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def names(self) -> list[str]:
        return list(self._tools)
