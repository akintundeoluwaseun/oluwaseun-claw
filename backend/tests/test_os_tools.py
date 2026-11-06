"""Milestone 4 (section 15): startup apps, memory, broken shortcuts, renaming many files, archives."""

import os
import zipfile
from pathlib import Path

import pytest

from claw.tools.base import ToolError
from tests.test_phase_a import call


def folder(tool_ctx, name):
    d = Path(tool_ctx.settings.permissions.authorized_folders[0]) / name
    d.mkdir(parents=True)
    return d


async def test_memory_and_startup_lists_are_read_only(tool_ctx):
    r = await call(tool_ctx, "top_memory")
    assert r.ok and r.data["top"] and "Nothing was closed" in r.summary
    r = await call(tool_ctx, "list_startup_apps")
    assert r.ok and "Nothing was changed" in r.summary


async def test_broken_shortcuts(tool_ctx):
    d = folder(tool_ctx, "Desktop links")
    (d / "Site.url").write_text("[InternetShortcut]\nURL=https://example.com\n")
    (d / "Old.url").write_text("[InternetShortcut]\nURL=C:\\Gone\\app.exe\n")
    os.symlink(d / "missing-target.txt", d / "dead link")
    r = await call(tool_ctx, "find_broken_shortcuts", folder="Desktop links")
    names = {Path(b["path"]).name for b in r.data["broken"]}
    assert names == {"Old.url", "dead link"} and "Nothing was deleted" in r.summary


async def test_rename_many_numbers_in_date_order_and_never_overwrites(tool_ctx):
    d = folder(tool_ctx, "Holiday")
    for i, n in enumerate(("IMG_0009.JPG", "IMG_0002.JPG", "IMG_0005.JPG")):
        (d / n).write_bytes(n.encode())
        os.utime(d / n, (1_700_000_000 + i, 1_700_000_000 + i))
    r = await call(tool_ctx, "rename_many", folder="Holiday", pattern="*.JPG", new_name="Lagos trip {n}")
    assert r.verified and sorted(p.name for p in d.iterdir()) == ["Lagos trip 1.jpg", "Lagos trip 2.jpg", "Lagos trip 3.jpg"]
    assert (d / "Lagos trip 1.jpg").read_bytes() == b"IMG_0009.JPG"            # oldest first
    (d / "Lagos trip 9.jpg").write_bytes(b"keep me")
    with pytest.raises(ToolError, match="already exists"):
        await call(tool_ctx, "rename_many", folder="Holiday", pattern="Lagos trip [123].jpg", new_name="Lagos trip {n}", start=7)
    assert (d / "Lagos trip 9.jpg").read_bytes() == b"keep me"
    with pytest.raises(ToolError, match="needs \\{n\\}"):
        await call(tool_ctx, "rename_many", folder="Holiday", new_name="same")


async def test_rename_many_can_pad_the_number_the_way_people_ask_for(tool_ctx):
    """"Wedding 001", not "Wedding 1".

    The width used to come from how many files there were, so three files
    could only ever be 1, 2, 3. Cameras and phones pad, and a person asking
    for 001 wants the files to sort properly in Explorer - which 1, 2, ... 10
    does not. The count cannot tell you the width, so it has to be sayable.
    """
    d = folder(tool_ctx, "Wedding")
    for i, n in enumerate(("b.jpg", "a.jpg", "c.jpg")):
        (d / n).write_bytes(n.encode())
        os.utime(d / n, (1_700_000_000 + i, 1_700_000_000 + i))

    r = await call(tool_ctx, "rename_many", folder="Wedding", pattern="*.jpg",
                   new_name="Wedding {n}", digits=3)
    assert r.verified
    assert sorted(p.name for p in d.iterdir()) == [
        "Wedding 001.jpg", "Wedding 002.jpg", "Wedding 003.jpg"]
    # Padding must not disturb the order: oldest is still number one.
    assert (d / "Wedding 001.jpg").read_bytes() == b"b.jpg"


async def test_rename_many_still_defaults_to_just_enough_digits(tool_ctx):
    """digits=0 is the old behaviour, so nothing that worked before changes."""
    d = folder(tool_ctx, "Trip")
    for i, n in enumerate(("x.jpg", "y.jpg")):
        (d / n).write_bytes(n.encode())
        os.utime(d / n, (1_700_000_000 + i, 1_700_000_000 + i))
    await call(tool_ctx, "rename_many", folder="Trip", pattern="*.jpg", new_name="Trip {n}")
    assert sorted(p.name for p in d.iterdir()) == ["Trip 1.jpg", "Trip 2.jpg"]


async def test_archive_is_reopened_and_checked(tool_ctx):
    d = folder(tool_ctx, "Website project")
    (d / "src").mkdir()
    (d / "src" / "app.js").write_text("console.log(1)")
    (d / "README.md").write_text("# site")
    r = await call(tool_ctx, "archive_folder", folder="Website project", file_name="site backup")
    out = d.parent / "site backup.zip"
    assert r.verified and out.is_file() and r.data["files"] == 2
    assert sorted(zipfile.ZipFile(out).namelist()) == ["Website project/README.md", "Website project/src/app.js"]
    with pytest.raises(ToolError, match="outside the folder"):
        await call(tool_ctx, "archive_folder", folder="Website project", save_in="Website project")
