"""One answer to "does this tool only look, or does it make or change files?" (reuse audit §2.2).

Before this, three hand-kept lists (executor, report, constraints) had already drifted apart:
compare_folders and table_totals counted as "work done", check_file as looking in one list and
not the other. Looking is now read from each tool's own risk level in the registry; making files is
one list here. A test keeps every making tool registered and every registered tool classified.
"""

from __future__ import annotations

from functools import cache

# Read-only by risk, but they act on a screen or a page rather than look at it.
UI_ACTIONS = frozenset({"click", "click_link", "close_tab", "focus_window", "scroll", "pause_for_me"})

# Tools that create or change files (checked by the "no new files" limit and the invented-file guard).
MAKES_FILES = frozenset({
    "create_spreadsheet", "write_text_file", "save_report", "list_to_table", "combine_files", "combine_tables",
    "remove_duplicates", "add_chart", "build_model", "make_flyer", "make_motion_video", "edit_image", "save_links",
    "create_folder", "copy_files", "sort_lines", "add_computed_column", "make_searchable_pdf", "download_file",
    "edit_text_file", "move_file", "rename_file", "sort_into_folders", "extract_emails", "rename_many", "archive_folder", "make_presentation", "export_pdf", "make_3d_render",
})
CHANGES_FILES = frozenset({"move_file", "rename_file", "edit_text_file", "sort_into_folders", "rename_many"})


@cache
def looking_tools() -> frozenset[str]:
    from claw.tools.registry import build_registry  # noqa: PLC0415 - built once, on first use

    return frozenset(s.name for s in build_registry().all() if s.risk.value == "read_only") - UI_ACTIONS


def is_looking(tool: str | None) -> bool:
    return bool(tool) and tool in looking_tools()
