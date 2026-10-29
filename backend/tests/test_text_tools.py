"""The text, table and system tools.

These are the deterministic jobs - counting, searching, merging, sorting,
comparing, arithmetic over a column - so the tests assert exact answers rather
than "it produced something".
"""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from claw.tools.base import ToolError
from claw.tools.registry import build_registry

REG = build_registry()

PARAGRAPH = "Hello from Oluwaseun Claw.\nClaw is a desktop agent.\n\nClaw runs on Windows.\n"


async def call(ctx, name, **args):
    spec = REG.get(name)
    if spec.precheck:
        spec.precheck(spec.parse_args(args), ctx)
    return await spec.handler(spec.parse_args(args), ctx)


@pytest.fixture
def folder(tool_ctx):
    return Path(tool_ctx.settings.permissions.authorized_folders[0])


@pytest.fixture
def notes(folder):
    p = folder / "notes.txt"
    p.write_text(PARAGRAPH, encoding="utf-8")
    return p


# ---------- counting ----------
async def test_count_text_counts_exactly(tool_ctx, notes):
    r = await call(tool_ctx, "count_text", path=str(notes))
    assert r.verified
    assert r.data["words"] == 13
    assert r.data["characters"] == len(PARAGRAPH)
    assert r.data["lines"] == 4
    assert r.data["paragraphs"] == 2
    assert r.data["characters_without_spaces"] == sum(1 for c in PARAGRAPH if not c.isspace())


# ---------- searching ----------
async def test_search_in_file_reports_every_line(tool_ctx, notes):
    r = await call(tool_ctx, "search_in_file", path=str(notes), query="claw")
    assert r.data["occurrences"] == 3 and len(r.data["lines"]) == 3
    assert [m["line"] for m in r.data["lines"]] == [1, 2, 4]  # line 3 is blank


async def test_search_is_case_sensitive_when_asked(tool_ctx, notes):
    r = await call(tool_ctx, "search_in_file", path=str(notes), query="claw", match_case=True)
    assert r.data["occurrences"] == 0 and r.data["found"] is False


async def test_search_query_is_not_a_regular_expression(tool_ctx, folder):
    p = folder / "odd.txt"
    p.write_text("a.b\naxb\n", encoding="utf-8")
    r = await call(tool_ctx, "search_in_file", path=str(p), query="a.b")
    assert r.data["occurrences"] == 1  # "axb" would match if the query were a pattern


async def test_search_whole_words(tool_ctx, folder):
    p = folder / "w.txt"
    p.write_text("Claw\nClaws\n", encoding="utf-8")
    assert (await call(tool_ctx, "search_in_file", path=str(p), query="Claw")).data["occurrences"] == 2
    r = await call(tool_ctx, "search_in_file", path=str(p), query="Claw", whole_words=True)
    assert r.data["occurrences"] == 1


# ---------- e-mail addresses ----------
async def test_extract_emails_deduplicates_and_saves(tool_ctx, folder):
    p = folder / "contacts.txt"
    p.write_text("Write to adebayo@example.com or ADEBAYO@Example.com.\n"
                 "Ngozi: ngozi.obi@mail.example.ng\nnot-an-address@\n", encoding="utf-8")
    r = await call(tool_ctx, "extract_emails", path=str(p), save_as="found.txt")
    assert r.data["emails"] == ["adebayo@example.com", "ngozi.obi@mail.example.ng"]
    saved = Path(r.data["saved_to"])
    assert saved.read_text(encoding="utf-8").splitlines() == r.data["emails"]


# ---------- combining ----------
async def test_combine_files_leaves_originals_alone(tool_ctx, folder):
    a, b = folder / "a.txt", folder / "b.txt"
    a.write_text("first", encoding="utf-8")
    b.write_text("second", encoding="utf-8")
    r = await call(tool_ctx, "combine_files", paths=[str(a), str(b)],
                   file_name="joined.txt", divider="---")
    out = Path(r.data["path"])
    assert r.verified and out.read_text(encoding="utf-8") == "first\n\n---\n\nsecond\n"
    assert a.read_text(encoding="utf-8") == "first" and b.read_text(encoding="utf-8") == "second"


async def test_combine_refuses_a_file_outside_authorized_folders(tool_ctx, folder, tmp_path):
    inside = folder / "a.txt"
    inside.write_text("x", encoding="utf-8")
    outside = tmp_path / "secret.txt"
    outside.write_text("y", encoding="utf-8")
    with pytest.raises(ToolError, match="not allowed"):
        await call(tool_ctx, "combine_files", paths=[str(inside), str(outside)], file_name="j.txt")


# ---------- comparing ----------
async def test_compare_files_changes_neither(tool_ctx, folder):
    a, b = folder / "one.txt", folder / "two.txt"
    a.write_text("line one\nline two\nline three\n", encoding="utf-8")
    b.write_text("line one\nline 2\nline three\n", encoding="utf-8")
    before = (a.read_bytes(), b.read_bytes())
    r = await call(tool_ctx, "compare_files", first=str(a), second=str(b))
    assert r.data["identical"] is False
    assert r.data["lines_added"] == 1 and r.data["lines_removed"] == 1
    assert "line 2" in r.untrusted_text
    assert (a.read_bytes(), b.read_bytes()) == before


async def test_compare_identical_files(tool_ctx, folder):
    a, b = folder / "x.txt", folder / "y.txt"
    for p in (a, b):
        p.write_text("same\n", encoding="utf-8")
    r = await call(tool_ctx, "compare_files", first=str(a), second=str(b))
    assert r.data["identical"] is True and "identical" in r.summary


async def test_compare_can_ignore_whitespace(tool_ctx, folder):
    a, b = folder / "p.txt", folder / "q.txt"
    a.write_text("hello   world\n", encoding="utf-8")
    b.write_text("hello world\n", encoding="utf-8")
    assert (await call(tool_ctx, "compare_files", first=str(a), second=str(b))).data["identical"] is False
    r = await call(tool_ctx, "compare_files", first=str(a), second=str(b), ignore_whitespace=True)
    assert r.data["identical"] is True


# ---------- sorting ----------
async def test_sort_lines_into_a_new_file(tool_ctx, folder):
    p = folder / "names.txt"
    p.write_text("Yusuf\nadebayo\nNgozi\nadebayo\n", encoding="utf-8")
    r = await call(tool_ctx, "sort_lines", path=str(p), file_name="sorted.txt", remove_duplicates=True)
    out = Path(r.data["path"])
    assert out.read_text(encoding="utf-8").splitlines() == ["adebayo", "Ngozi", "Yusuf"]
    assert r.data["duplicates_removed"] == 1
    assert p.read_text(encoding="utf-8").splitlines() == ["Yusuf", "adebayo", "Ngozi", "adebayo"]


async def test_sort_keeps_a_header_row(tool_ctx, folder):
    p = folder / "table.csv"
    p.write_text("Name\nYusuf\nAdebayo\n", encoding="utf-8")
    r = await call(tool_ctx, "sort_lines", path=str(p), file_name="s.csv", skip_first_line=True)
    assert Path(r.data["path"]).read_text(encoding="utf-8").splitlines() == ["Name", "Adebayo", "Yusuf"]


# ---------- CSV arithmetic ----------
@pytest.fixture
async def products(tool_ctx, folder):
    r = await call(tool_ctx, "create_spreadsheet", file_name="products.csv",
                   columns=["Product", "Price", "Quantity"],
                   rows=[["Item 1", 1000, 2], ["Item 2", 2500, 3], ["Item 3", "n/a", 1]],
                   folder=str(folder))
    return Path(r.data["path"])


async def test_summarize_column(tool_ctx, products):
    r = await call(tool_ctx, "summarize_column", path=str(products), column="price")
    assert r.data["count"] == 2 and r.data["sum"] == 3500 and r.data["average"] == 1750
    assert r.data["minimum"] == 1000 and r.data["maximum"] == 2500
    assert r.data["rows_without_a_number"] == 1


async def test_summarize_names_the_columns_it_has(tool_ctx, products):
    with pytest.raises(ToolError, match="Product, Price, Quantity"):
        await call(tool_ctx, "summarize_column", path=str(products), column="Total")


async def test_add_computed_column_multiplies(tool_ctx, products):
    r = await call(tool_ctx, "add_computed_column", path=str(products), first_column="Price",
                   operation="multiply", second_column="Quantity",
                   new_column="Total value", file_name="totals.csv")
    out = Path(r.data["path"])
    lines = out.read_text(encoding="utf-8-sig").splitlines()
    assert lines[0] == "Product,Price,Quantity,Total value"
    assert lines[1] == "Item 1,1000,2,2000"
    assert lines[2] == "Item 2,2500,3,7500"
    assert lines[3].endswith(",")          # no number in the row, so nothing is invented
    assert r.data["rows_computed"] == 2
    assert products.read_text(encoding="utf-8-sig").count("Total value") == 0


async def test_add_computed_column_needs_one_operand(tool_ctx, products):
    with pytest.raises(ToolError, match="not both and not neither"):
        await call(tool_ctx, "add_computed_column", path=str(products), first_column="Price",
                   operation="multiply", second_column="Quantity", number=2,
                   new_column="x", file_name="x.csv")


async def test_add_computed_column_rejects_an_unknown_operation(tool_ctx, products):
    with pytest.raises(Exception, match="multiply, divide, add or subtract"):
        await call(tool_ctx, "add_computed_column", path=str(products), first_column="Price",
                   operation="__import__('os').system", number=2, new_column="x", file_name="x.csv")


async def test_divide_by_zero_leaves_the_cell_blank(tool_ctx, products):
    r = await call(tool_ctx, "add_computed_column", path=str(products), first_column="Price",
                   operation="divide", number=0, new_column="Per", file_name="per.csv")
    assert r.data["rows_computed"] == 0


# ---------- a list into a table ----------
async def test_list_to_table_splits_and_strips_bullets(tool_ctx, folder):
    text = ("- Adebayo Okafor, adebayo@example.com, 0801 000 0001\n"
            "- Chidinma Eze, chidinma@example.com, 0802 000 0002\n")
    r = await call(tool_ctx, "list_to_table", text=text,
                   columns=["Name", "Email", "Phone"], file_name="contacts.csv",
                   folder=str(folder))
    lines = Path(r.data["path"]).read_text(encoding="utf-8-sig").splitlines()
    assert lines[0] == "Name,Email,Phone"
    assert lines[1] == "Adebayo Okafor,adebayo@example.com,0801 000 0001"
    assert r.data["rows"] == 2


async def test_list_to_table_accepts_the_word_tab(tool_ctx, folder):
    """A tab cannot be passed as itself: tool arguments arrive stripped of whitespace."""
    r = await call(tool_ctx, "list_to_table", text="Adebayo\tLagos\nNgozi\tAbuja",
                   columns=["Name", "City"], file_name="t.csv", folder=str(folder),
                   separator="tab")
    lines = Path(r.data["path"]).read_text(encoding="utf-8-sig").splitlines()
    assert lines[1] == "Adebayo,Lagos" and r.data["rows"] == 2


async def test_combine_without_a_divider(tool_ctx, folder):
    a, b = folder / "c.txt", folder / "d.txt"
    a.write_text("one\n", encoding="utf-8")
    b.write_text("two\n", encoding="utf-8")
    r = await call(tool_ctx, "combine_files", paths=[str(a), str(b)], file_name="cd.txt")
    assert Path(r.data["path"]).read_text(encoding="utf-8") == "one\n\ntwo\n"


async def test_list_to_table_pads_a_short_line(tool_ctx, folder):
    r = await call(tool_ctx, "list_to_table", text="only a name\n", columns=["Name", "Email"],
                   file_name="one.csv", folder=str(folder))
    assert Path(r.data["path"]).read_text(encoding="utf-8-sig").splitlines()[1] == "only a name,"


# ---------- moving ----------
async def test_move_file_moves_and_verifies(tool_ctx, folder, notes):
    (folder / "Archive").mkdir()
    before = notes.read_bytes()
    r = await call(tool_ctx, "move_file", path=str(notes), destination_folder=str(folder / "Archive"))
    moved = Path(r.data["path"])
    assert r.verified and moved.read_bytes() == before and not notes.exists()
    assert moved.parent.name == "Archive"


async def test_move_never_overwrites(tool_ctx, folder, notes):
    dest = folder / "Archive"
    dest.mkdir()
    (dest / "notes.txt").write_text("already here", encoding="utf-8")
    with pytest.raises(ToolError, match="already exists"):
        await call(tool_ctx, "move_file", path=str(notes), destination_folder=str(dest))
    assert notes.exists() and (dest / "notes.txt").read_text(encoding="utf-8") == "already here"


async def test_move_refuses_a_destination_outside_authorized_folders(tool_ctx, notes, tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    with pytest.raises(ToolError, match="not allowed"):
        await call(tool_ctx, "move_file", path=str(notes), destination_folder=str(outside))
    assert notes.exists()


# ---------- the system ----------
async def test_current_time_matches_the_clock(tool_ctx):
    r = await call(tool_ctx, "current_time")
    assert r.verified
    assert abs(r.data["unix_seconds"] - time.time()) < 5
    assert r.data["date"] == time.strftime("%Y-%m-%d")
    assert r.data["day_of_week"] == time.strftime("%A")


async def test_disk_space_reports_real_numbers(tool_ctx, folder):
    r = await call(tool_ctx, "disk_space", path=str(folder))
    import shutil

    usage = shutil.disk_usage(folder)
    assert r.data["total_bytes"] == usage.total
    assert 0 <= r.data["percent_free"] <= 100
    assert r.data["free_gb"] > 0


async def test_disk_space_refuses_an_unauthorized_folder(tool_ctx, tmp_path):
    with pytest.raises(ToolError, match="not allowed"):
        await call(tool_ctx, "disk_space", path=str(tmp_path / "elsewhere"))


def _my_process_name() -> str:
    """What the operating system calls THIS process.

    Not the same as the interpreter's filename. Launched through a console
    script - `.venv/bin/pytest`, which is what a contributor types - the process
    is called "pytest" while sys.executable still points at python, so asking
    for `Path(sys.executable).name` asks about a program that genuinely is not
    running. is_program_running reads `ps -eo comm=`, so the test asks the same
    source the tool does.
    """
    if sys.platform == "win32":
        return Path(sys.executable).name  # python.exe really is the process
    out = subprocess.run(["/bin/ps", "-p", str(os.getpid()), "-o", "comm="],
                         capture_output=True, text=True, check=False, timeout=10)
    name = Path(out.stdout.strip().splitlines()[-1].strip()).name if out.stdout.strip() else ""
    return name or Path(sys.executable).name


async def test_this_process_is_running(tool_ctx):
    """The one program certainly running is the one asking."""
    me = _my_process_name()
    r = await call(tool_ctx, "is_program_running", program=me)
    assert r.data["running"] is True and r.data["processes_checked"] > 0


async def test_a_program_that_is_not_running(tool_ctx):
    r = await call(tool_ctx, "is_program_running", program="definitely-not-a-real-program-xyz")
    assert r.data["running"] is False and r.data["matches"] == []


async def test_known_windows_names_are_translated(tool_ctx):
    r = await call(tool_ctx, "is_program_running", program="Notepad")
    assert r.data["looked_for"] == "notepad.exe"


# ---------- finding old files ----------
async def test_find_files_by_age(tool_ctx, folder):
    old, new = folder / "old.txt", folder / "new.txt"
    old.write_text("old", encoding="utf-8")
    new.write_text("new", encoding="utf-8")
    long_ago = time.time() - 40 * 86400
    os.utime(old, (long_ago, long_ago))

    stale = await call(tool_ctx, "find_files", extension=".txt", not_modified_in_days=30)
    assert [Path(f["path"]).name for f in stale.data["files"]] == ["old.txt"]
    assert "not changed in 30 day(s)" in stale.summary

    recent = await call(tool_ctx, "find_files", extension=".txt", modified_in_days=7)
    assert [Path(f["path"]).name for f in recent.data["files"]] == ["new.txt"]
