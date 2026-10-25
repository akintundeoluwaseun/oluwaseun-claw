"""Assemble the set of tools the agent may use."""

from __future__ import annotations

from claw.tools.base import ToolRegistry
from claw.tools.browser_tools import register_browser_tools
from claw.tools.file_tools import register_file_tools


def build_registry() -> ToolRegistry:
    reg = ToolRegistry()
    register_browser_tools(reg)
    register_file_tools(reg)
    return reg
