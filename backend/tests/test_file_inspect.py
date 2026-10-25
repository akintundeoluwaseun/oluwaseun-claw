import os
import time

import pytest

from claw.tools.base import ToolError
from claw.tools.registry import build_registry

REG = build_registry()


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
    r = await call(tool_ctx, "read_text_file", path=str(files / "notes.txt"))
    assert r.untrusted_text == "Call Mr. Ade at 4pm"


async def test_find_newest_pdf_first(tool_ctx, files):
    r = await call(tool_ctx, "find_files", extension="pdf")
    assert [os.path.basename(f["path"]) for f in r.data["files"]] == ["new invoice.pdf", "old report.pdf"]


async def test_refuses_outside_and_binary(tool_ctx, files, tmp_path):
    with pytest.raises(ToolError, match="not allowed"):
        await call(tool_ctx, "read_text_file", path=str(tmp_path / "secret.txt"))
    with pytest.raises(ToolError, match="text files only"):
        await call(tool_ctx, "read_text_file", path=str(files / "photo.jpg"))
    with pytest.raises(ToolError, match="not allowed"):
        await call(tool_ctx, "list_folder", folder=str(files / ".." ))
