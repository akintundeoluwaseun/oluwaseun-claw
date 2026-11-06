"""Finding your way around a folder.

search_in_file could look inside ONE file. That is not how anyone navigates a
folder of work - you ask "where does this appear?" and expect a list of files
and lines. Without it the only way to search a folder was to read every file
in turn, which on a 2B brain means filling the context window with files that
had nothing in them.

Also here: edit_text_file now accepts code. run_script writes a .py file into
the person's folder, and Claw could not then fix a line of it.
"""

from pathlib import Path

import pytest

from claw.tools.base import ToolError
from claw.tools.document_tools import EDITABLE
from tests.test_phase_a import call


@pytest.fixture
def tree(tool_ctx):
    root = Path(tool_ctx.settings.permissions.authorized_folders[0])
    (root / "notes.md").write_text("The invoice total was wrong\nand the invoice date too\n")
    (root / "script.py").write_text("def total():\n    return invoice_total\n")
    (root / "data.csv").write_text("item,price\nInvoice,100\n")
    (root / "deep").mkdir()
    (root / "deep" / "more.txt").write_text("nothing relevant here\n")
    (root / "deep" / "other.py").write_text("# invoice again\n")
    (root / "picture.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 50)
    return root


async def test_it_finds_the_word_across_the_folder(tool_ctx, tree):
    r = await call(tool_ctx, "search_in_folder", query="invoice")
    assert r.ok and r.data["found"]
    files = {h["file"] for h in r.data["files"]}
    assert {"notes.md", "script.py", "data.csv"} <= files
    assert any(f.endswith("other.py") for f in files), "subfolders must be searched"


async def test_it_reports_the_lines_not_just_the_files(tool_ctx, tree):
    r = await call(tool_ctx, "search_in_folder", query="invoice total")
    hit = next(h for h in r.data["files"] if h["file"] == "notes.md")
    assert hit["lines"][0]["line"] == 1
    assert "invoice total" in hit["lines"][0]["text"].lower()
    assert "notes.md" in r.untrusted_text


async def test_pictures_are_skipped_not_decoded_as_text(tool_ctx, tree):
    r = await call(tool_ctx, "search_in_folder", query="invoice")
    assert r.data["skipped"] >= 1
    assert not any("picture.png" in h["file"] for h in r.data["files"])


async def test_a_pattern_narrows_it_to_the_files_asked_for(tool_ctx, tree):
    r = await call(tool_ctx, "search_in_folder", query="invoice", pattern="*.py")
    files = {h["file"] for h in r.data["files"]}
    assert all(f.endswith(".py") for f in files), files
    assert "notes.md" not in files


async def test_case_and_whole_words(tool_ctx, tree):
    loose = await call(tool_ctx, "search_in_folder", query="INVOICE")
    assert loose.data["found"], "the default must ignore case"
    exact = await call(tool_ctx, "search_in_folder", query="INVOICE", match_case=True)
    assert not exact.data["found"]
    whole = await call(tool_ctx, "search_in_folder", query="total", whole_words=True)
    hits = {h["file"] for h in whole.data["files"]}
    assert "notes.md" in hits and "script.py" in hits   # "total()" is a whole word


async def test_a_word_that_is_not_there_says_so_rather_than_failing(tool_ctx, tree):
    r = await call(tool_ctx, "search_in_folder", query="zebra")
    assert r.ok and not r.data["found"]
    assert "no files" in r.summary and "nothing matched" in r.untrusted_text


async def test_the_query_is_not_read_as_a_regular_expression(tool_ctx, tree):
    (tree / "odd.txt").write_text("a.b and axb\n")
    r = await call(tool_ctx, "search_in_folder", query="a.b")
    hit = next(h for h in r.data["files"] if h["file"] == "odd.txt")
    assert hit["lines"][0]["text"].count("a.b") == 1
    assert r.data["occurrences"] == 1, "'a.b' must not match 'axb'"


async def test_a_folder_outside_the_allowed_ones_is_refused(tool_ctx, tree):
    with pytest.raises(ToolError):
        await call(tool_ctx, "search_in_folder", query="x", folder="/etc")


# ---------- editing the code it writes ----------
async def test_claw_can_fix_a_line_of_the_program_it_wrote(tool_ctx, tree):
    r = await call(tool_ctx, "edit_text_file", path=str(tree / "script.py"),
                   find="return invoice_total", replace_with="return 0")
    assert r.ok
    assert "return 0" in (tree / "script.py").read_text()


def test_code_is_editable_and_secrets_are_not():
    for ext in (".py", ".js", ".ts", ".sh", ".ps1", ".sql", ".scad"):
        assert ext in EDITABLE, ext
    for ext in (".env", ".exe", ".dll", ".key", ".pem"):
        assert ext not in EDITABLE, ext


async def test_a_file_claw_will_not_edit_says_what_it_will(tool_ctx, tree):
    (tree / "thing.bin").write_bytes(b"\0\1\2")
    with pytest.raises(ToolError) as exc:
        await call(tool_ctx, "edit_text_file", path=str(tree / "thing.bin"),
                   find="a", replace_with="b")
    assert ".py" in str(exc.value) and ".bin" in str(exc.value)
