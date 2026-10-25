"""Tool definitions.

The model never runs code. It can only name a registered tool and supply
arguments; the arguments are validated against the tool's Pydantic model
before anything happens, and the tool's risk level decides whether it runs,
asks the user, or is refused.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, ValidationError

from claw.agent.schemas import Capability
from claw.config import Settings, describe_validation_error
from claw.permissions.policy import PermissionPolicy, RiskLevel

if TYPE_CHECKING:
    from claw.browser.session import BrowserSession


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
class ToolContext:
    settings: Settings
    policy: PermissionPolicy
    data_dir: Path
    browser: "BrowserSession"
    task_id: str


Handler = Callable[[ToolArgs, ToolContext], Awaitable[ToolResult]]
Precheck = Callable[[ToolArgs, ToolContext], None]


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
