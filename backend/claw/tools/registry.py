"""Assemble the set of tools the agent may use."""

from __future__ import annotations

from claw.tools.base import ToolRegistry
from claw.tools.browser_tools import register_browser_tools
from claw.tools.calendar_tools import register_calendar_tools
from claw.tools.desktop_tools import register_desktop_tools
from claw.tools.document_tools import register_document_tools
from claw.tools.file_inspect import register_file_inspect_tools
from claw.tools.file_ops import register_file_ops
from claw.tools.file_tools import register_file_tools
from claw.tools.human_tools import register_human_tools
from claw.tools.mail_tools import register_mail_tools
from claw.tools.memory_tools import register_memory_tools
from claw.tools.message_tools import register_message_tools
from claw.tools.system_tools import register_system_tools
from claw.tools.text_tools import register_text_tools
from claw.tools.image_tools import register_image_tools
from claw.tools.pdf_tools import register_pdf_tools
from claw.tools import page_tools


def build_registry() -> ToolRegistry:
    reg = ToolRegistry()
    register_browser_tools(reg)
    register_file_tools(reg)
    register_file_inspect_tools(reg)
    register_file_ops(reg)
    register_text_tools(reg)
    register_calendar_tools(reg)
    register_human_tools(reg)
    register_mail_tools(reg)
    register_memory_tools(reg)
    register_document_tools(reg)
    register_pdf_tools(reg)
    register_desktop_tools(reg)
    register_system_tools(reg)
    register_message_tools(reg)
    register_image_tools(reg)
    page_tools.register(reg)
    return reg
