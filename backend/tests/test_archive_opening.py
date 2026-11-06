"""Opening an archive somebody else made.

Claw could pack a .zip and not open one, so a supplier's folder of photos or
a bank's statements meant doing it by hand.

Most of these tests are about the archive being UNTRUSTED. The names inside
it were written somewhere else, and the two classic ways a program gets this
wrong - writing outside the destination, and unpacking until the disk is
full - are each checked here with an archive built to do exactly that.
"""

from __future__ import annotations

import hashlib
import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from claw.tools.archive_tools import MAX_RATIO, safe_target
from claw.tools.base import ToolError
from tests.test_phase_a import call


def folder(ctx, name="Inbox"):
    d = Path(ctx.settings.permissions.authorized_folders[0]) / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def make_zip(path: Path, items: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in items.items():
            z.writestr(name, data)


# ---------- the destination check, on its own ----------
def test_a_name_that_climbs_out_is_refused(tmp_path):
    dest = tmp_path / "unpacked"
    dest.mkdir()
    assert safe_target(dest, "notes.txt") == (dest / "notes.txt").resolve()
    assert safe_target(dest, "photos/one.jpg") == (dest / "photos/one.jpg").resolve()
    for evil in ("../escaped.txt", "../../escaped.txt", "photos/../../escaped.txt",
                 r"..\..\escaped.txt"):
        with pytest.raises(ToolError, match="outside the folder"):
            safe_target(dest, evil)


def test_an_absolute_path_is_refused(tmp_path):
    dest = tmp_path / "unpacked"
    dest.mkdir()
    for evil in ("/etc/passwd", r"C:\Windows\System32\drivers\etc\hosts", "/root/.ssh/authorized_keys"):
        with pytest.raises(ToolError, match="absolute path"):
            safe_target(dest, evil)


# ---------- the same, through the tool ----------
async def test_a_zip_slip_archive_writes_nothing_outside(tool_ctx):
    """The attack: an entry named ../../ lands outside every authorized folder."""
    d = folder(tool_ctx)
    outside = Path(tool_ctx.settings.permissions.authorized_folders[0]).parent / "ESCAPED.txt"
    make_zip(d / "evil.zip", {"ok.txt": b"fine", "../../ESCAPED.txt": b"got out"})

    with pytest.raises(ToolError, match="outside the folder"):
        await call(tool_ctx, "open_archive", path="evil.zip", folder="Inbox")
    assert not outside.exists(), "a zip wrote a file outside the authorized folders"


async def test_nothing_is_written_at_all_when_one_entry_is_bad(tool_ctx):
    """Destinations are all checked before the first byte is written.

    Otherwise a malicious archive gets its good files unpacked and leaves a
    half-finished folder that looks like a successful job.
    """
    d = folder(tool_ctx)
    make_zip(d / "mixed.zip", {"a.txt": b"one", "b.txt": b"two", "../../OUT.txt": b"bad"})
    with pytest.raises(ToolError):
        await call(tool_ctx, "open_archive", path="mixed.zip", folder="Inbox")
    assert not list(d.glob("mixed/*")), "files were unpacked from an archive that was refused"


async def test_a_symlink_entry_is_skipped_not_followed(tool_ctx):
    """A link can point anywhere; what gets written through it lands there."""
    d = folder(tool_ctx)
    path = d / "linky.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("real.txt", b"content")
        info = zipfile.ZipInfo("link.txt")
        info.external_attr = (0o120777 << 16)       # symlink mode
        z.writestr(info, "/etc/passwd")
    r = await call(tool_ctx, "open_archive", path="linky.zip", folder="Inbox")
    assert r.ok
    out = Path(r.data["folder"])
    assert (out / "real.txt").is_file()
    assert not (out / "link.txt").exists(), "a symlink entry was unpacked"
    assert r.data["skipped_links"] == 1


async def test_a_decompression_bomb_is_refused(tool_ctx):
    """Tiny archive, enormous contents. Refused before anything is written."""
    d = folder(tool_ctx)
    path = d / "bomb.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("huge.bin", b"\0" * (120 * 1024 * 1024))     # compresses to almost nothing
    assert path.stat().st_size * MAX_RATIO < 120 * 1024 * 1024, "the fixture is not actually a bomb"
    with pytest.raises(ToolError, match="not a normal archive"):
        await call(tool_ctx, "open_archive", path="bomb.zip", folder="Inbox")
    assert not (d / "bomb").exists()


# ---------- the ordinary job ----------
async def test_opening_an_ordinary_zip(tool_ctx):
    d = folder(tool_ctx)
    make_zip(d / "photos.zip", {
        "photos/one.jpg": b"\xff\xd8 first", "photos/two.jpg": b"\xff\xd8 second",
        "notes.txt": b"from the supplier"})
    before = hashlib.sha256((d / "photos.zip").read_bytes()).hexdigest()

    r = await call(tool_ctx, "open_archive", path="photos.zip", folder="Inbox")
    assert r.ok and r.verified and r.data["files"] == 3
    out = Path(r.data["folder"])
    assert (out / "photos" / "one.jpg").read_bytes() == b"\xff\xd8 first"
    assert (out / "notes.txt").read_bytes() == b"from the supplier"
    assert hashlib.sha256((d / "photos.zip").read_bytes()).hexdigest() == before, \
        "the archive itself was modified"


async def test_only_some_files_can_be_taken_out(tool_ctx):
    d = folder(tool_ctx)
    make_zip(d / "mixed.zip", {"a.pdf": b"%PDF one", "b.pdf": b"%PDF two",
                               "c.jpg": b"\xff\xd8", "notes.txt": b"hi"})
    r = await call(tool_ctx, "open_archive", path="mixed.zip", folder="Inbox", only="*.pdf")
    assert r.ok and r.data["files"] == 2
    names = sorted(p.name for p in Path(r.data["folder"]).rglob("*") if p.is_file())
    assert names == ["a.pdf", "b.pdf"]


async def test_a_tar_works_the_same_way(tool_ctx):
    d = folder(tool_ctx)
    path = d / "stuff.tar.gz"
    with tarfile.open(path, "w:gz") as t:
        for name, data in (("one.txt", b"first"), ("sub/two.txt", b"second")):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    r = await call(tool_ctx, "open_archive", path="stuff.tar.gz", folder="Inbox")
    assert r.ok and r.data["files"] == 2
    assert (Path(r.data["folder"]) / "sub" / "two.txt").read_bytes() == b"second"


async def test_a_tar_that_climbs_out_is_refused_too(tool_ctx):
    d = folder(tool_ctx)
    path = d / "evil.tar"
    with tarfile.open(path, "w") as t:
        data = b"got out"
        info = tarfile.TarInfo("../../ESCAPED.txt")
        info.size = len(data)
        t.addfile(info, io.BytesIO(data))
    with pytest.raises(ToolError, match="outside the folder"):
        await call(tool_ctx, "open_archive", path="evil.tar", folder="Inbox")


# ---------- looking without unpacking ----------
async def test_looking_inside_unpacks_nothing(tool_ctx):
    d = folder(tool_ctx)
    make_zip(d / "box.zip", {"a.pdf": b"%PDF", "b.pdf": b"%PDF", "c.jpg": b"\xff\xd8"})
    before = sorted(p.name for p in d.iterdir())

    r = await call(tool_ctx, "look_inside_archive", path="box.zip", folder="Inbox")
    assert r.ok and r.data["files"] == 3
    assert "2 .pdf" in r.summary
    assert "Nothing was unpacked" in r.summary
    assert sorted(p.name for p in d.iterdir()) == before, "looking inside created something"


async def test_an_archive_needing_another_program_says_so(tool_ctx):
    """Better than failing halfway with something unreadable."""
    d = folder(tool_ctx)
    (d / "design.rar").write_bytes(b"Rar!\x1a\x07\x00 not really")
    with pytest.raises(ToolError, match="7-Zip|separate program"):
        await call(tool_ctx, "look_inside_archive", path="design.rar", folder="Inbox")


async def test_a_file_that_is_not_an_archive_says_so(tool_ctx):
    d = folder(tool_ctx)
    (d / "notes.zip").write_bytes(b"this is just text, not a zip")
    with pytest.raises(ToolError, match="not an archive"):
        await call(tool_ctx, "open_archive", path="notes.zip", folder="Inbox")
