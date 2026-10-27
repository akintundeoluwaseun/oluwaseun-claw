import os
import time
from pathlib import Path

import pytest

from claw.tools.base import ToolError
from claw.tools.registry import build_registry

REG = build_registry()


@pytest.fixture
def folder(tool_ctx):
    return Path(tool_ctx.settings.permissions.authorized_folders[0])


async def call(ctx, name, **args):
    spec = REG.get(name)
    return await spec.handler(spec.parse_args(args), ctx)


@pytest.fixture
def files(tool_ctx, tmp_path):
    root = tmp_path / "saved"
    (root / "Downloads").mkdir()
    old = root / "Downloads" / "old report.pdf"
    old.write_bytes(b"%PDF-old")
    os.utime(old, (time.time() - 3600, time.time() - 3600))
    (root / "Downloads" / "new invoice.pdf").write_bytes(b"%PDF-new")
    (root / "notes.txt").write_text("Call Mr. Ade at 4pm", encoding="utf-8")
    (root / "photo.jpg").write_bytes(b"\xff\xd8\xff")
    (tmp_path / "secret.txt").write_text("outside")
    return root


async def test_list_and_read(tool_ctx, files):
    listing = await call(tool_ctx, "list_folder")
    assert "Downloads/" in listing.untrusted_text and "notes.txt" in listing.untrusted_text
    r = await call(tool_ctx, "read_file", path=str(files / "notes.txt"))
    assert r.untrusted_text == "Call Mr. Ade at 4pm"


async def test_find_newest_pdf_first(tool_ctx, files):
    r = await call(tool_ctx, "find_files", extension="pdf")
    assert [os.path.basename(f["path"]) for f in r.data["files"]] == ["new invoice.pdf", "old report.pdf"]


async def test_refuses_outside_and_binary(tool_ctx, files, tmp_path):
    with pytest.raises(ToolError, match="not allowed"):
        await call(tool_ctx, "read_file", path=str(tmp_path / "secret.txt"))
    with pytest.raises(ToolError, match="isn't supported"):
        await call(tool_ctx, "read_file", path=str(files / "photo.jpg"))
    with pytest.raises(ToolError, match="not allowed"):
        await call(tool_ctx, "list_folder", folder=str(files / ".." ))


# ---------- create_folder and rename_file ----------
# The five steps a user asked for end to end: make a folder, write a file, read it,
# append to it keeping the first line, rename it, and confirm nothing changed inside.

async def test_folder_file_edit_rename_end_to_end(tool_ctx, folder):
    made = await call(tool_ctx, "create_folder", folder_name="Claw Test", inside=str(folder))
    target = Path(made.data["path"])
    assert made.verified and target.is_dir() and target.name == "Claw Test"

    line1, line2 = "Hello from Oluwaseun Claw.", "Today's test is complete."
    written = await call(tool_ctx, "write_text_file", file_name="hello.txt", text=line1,
                         folder=str(target))
    path = Path(written.data["path"])
    assert written.verified and path.read_text(encoding="utf-8") == line1

    read = await call(tool_ctx, "read_file", path=str(path))
    assert line1 in (read.untrusted_text or "")

    await call(tool_ctx, "edit_text_file", path=str(path), find=line1,
               replace_with=f"{line1}\n{line2}")
    assert path.read_text(encoding="utf-8") == f"{line1}\n{line2}"

    before = path.read_bytes()
    renamed = await call(tool_ctx, "rename_file", path=str(path), new_name="hello-test.txt")
    new_path = Path(renamed.data["path"])
    assert renamed.verified
    assert new_path.is_file() and not path.exists()
    assert new_path.read_bytes() == before  # a rename must not touch the contents
    assert new_path.parent == target        # and must not move it somewhere else


async def test_create_folder_is_idempotent_and_says_so(tool_ctx, folder):
    first = await call(tool_ctx, "create_folder", folder_name="Reports", inside=str(folder))
    again = await call(tool_ctx, "create_folder", folder_name="Reports", inside=str(folder))
    assert first.data["created"] and not again.data["created"]
    assert again.data["already_existed"] and again.verified
    assert "already" in again.summary.lower()


@pytest.mark.parametrize("name", ["../escaped", "..\\escaped", "sub/under", "C:\\Windows"])
async def test_create_folder_refuses_a_path(tool_ctx, folder, name):
    """Silently turning '../../escaped' into a folder called 'escaped' is not what was asked."""
    with pytest.raises(ToolError, match="not a path"):
        await call(tool_ctx, "create_folder", folder_name=name, inside=str(folder))


async def test_create_folder_stays_inside_authorized_folders(tool_ctx):
    with pytest.raises(ToolError):
        await call(tool_ctx, "create_folder", folder_name="x", inside="/etc")


async def test_rename_never_overwrites(tool_ctx, folder):
    a = await call(tool_ctx, "write_text_file", file_name="a.txt", text="first", folder=str(folder))
    await call(tool_ctx, "write_text_file", file_name="b.txt", text="second", folder=str(folder))
    with pytest.raises(ToolError, match="already exists"):
        await call(tool_ctx, "rename_file", path=a.data["path"], new_name="b.txt")
    assert (folder / "b.txt").read_text(encoding="utf-8") == "second"  # untouched
    assert Path(a.data["path"]).is_file()  # and the original is still there


@pytest.mark.parametrize("bad", ["evil.exe", "evil.bat", "evil.ps1", "evil.cmd", "evil.dll"])
async def test_rename_cannot_turn_a_document_into_a_program(tool_ctx, folder, bad):
    f = await call(tool_ctx, "write_text_file", file_name="notes.txt", text="hi", folder=str(folder))
    with pytest.raises(ToolError, match="program"):
        await call(tool_ctx, "rename_file", path=f.data["path"], new_name=bad)


@pytest.mark.parametrize("bad", ["../escaped.txt", "..\\escaped.txt", "sub/x.txt"])
async def test_rename_refuses_a_path(tool_ctx, folder, bad):
    f = await call(tool_ctx, "write_text_file", file_name="notes.txt", text="hi", folder=str(folder))
    with pytest.raises(ToolError, match="not a path"):
        await call(tool_ctx, "rename_file", path=f.data["path"], new_name=bad)


async def test_rename_keeps_the_extension_when_none_is_given(tool_ctx, folder):
    f = await call(tool_ctx, "write_text_file", file_name="notes.txt", text="hi", folder=str(folder))
    r = await call(tool_ctx, "rename_file", path=f.data["path"], new_name="renamed")
    assert Path(r.data["path"]).name == "renamed.txt"


async def test_rename_records_the_file_as_seen(tool_ctx, folder):
    """So a report may cite it afterwards under its new name."""
    f = await call(tool_ctx, "write_text_file", file_name="notes.txt", text="hi", folder=str(folder))
    r = await call(tool_ctx, "rename_file", path=f.data["path"], new_name="final.txt")
    assert tool_ctx.memory.saw_file(r.data["path"])
