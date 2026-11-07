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
from claw.tools.billing_tools import register_billing_tools
from claw.tools.cad_tools import register_cad_tools
from claw.tools.archive_tools import register_archive_tools
from claw.tools.batch_image_tools import register_batch_image_tools
from claw.tools.clip_tools import register_clip_tools
from claw.tools.merge_tools import register_merge_tools
from claw.tools.rewrite_tools import register_rewrite_tools
from claw.tools.clipboard_tools import register_clipboard_tools
from claw.tools.install_tools import register_install_tools
from claw.tools.table_extract_tools import register_table_extract_tools
from claw.tools.pdf_edit_tools import register_pdf_edit_tools
from claw.tools.code_tools import register_code_tools
from claw.tools.memory_tools import register_memory_tools
from claw.tools.message_tools import register_message_tools
from claw.tools.system_tools import register_system_tools
from claw.tools.text_tools import register_text_tools
from claw.tools.image_tools import register_image_tools
from claw.tools.media_tools import register_media_tools
from claw.tools.motion_tools import register_motion_tools
from claw.tools.office_tools import register_office_tools
from claw.tools.os_tools import register_os_tools
from claw.tools.research_tools import register_more_research_tools, register_research_tools
from claw.tools.three_d_tools import register_three_d_tools
from claw.tools.analysis_tools import register_analysis_tools
from claw.tools.table_tools import register_model_tools, register_table_tools
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
    register_billing_tools(reg)
    register_cad_tools(reg)
    register_pdf_edit_tools(reg)
    register_archive_tools(reg)
    register_batch_image_tools(reg)
    register_clip_tools(reg)
    register_merge_tools(reg)
    register_rewrite_tools(reg)
    register_table_extract_tools(reg)
    register_install_tools(reg)
    register_clipboard_tools(reg)
    register_code_tools(reg)
    register_document_tools(reg)
    register_pdf_tools(reg)
    register_desktop_tools(reg)
    register_system_tools(reg)
    register_message_tools(reg)
    register_image_tools(reg)
    register_motion_tools(reg)
    register_media_tools(reg)
    register_os_tools(reg)
    register_office_tools(reg)
    register_research_tools(reg)
    register_more_research_tools(reg)
    register_three_d_tools(reg)
    register_table_tools(reg)
    register_model_tools(reg)
    register_analysis_tools(reg)
    page_tools.register(reg)
    return reg
