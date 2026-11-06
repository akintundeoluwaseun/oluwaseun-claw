"""Changing PDFs: joining, splitting, turning, stamping, shrinking.

Claw could read a PDF and never alter one, so everything a person does to a
PDF between receiving it and sending it on meant opening something else.

Two things every test here checks, because they are the two ways this kind of
tool goes wrong quietly:

  - the original is still there, byte for byte. A scan is often the only copy.
  - the result was reopened and counted. A tool that writes a file and reports
    what it MEANT to write is the fabrication problem in another costume.
"""

from __future__ import annotations

import hashlib
import io
import sys
from pathlib import Path

import pytest

from claw.tools.base import ToolError
from claw.tools.pdf_edit_tools import parse_pages
from tests.test_phase_a import call

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import challenge_bench as cb  # noqa: E402


def folder(ctx, name="Scans"):
    d = Path(ctx.settings.permissions.authorized_folders[0]) / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def pages_pdf(lines: list[str]) -> bytes:
    """A real multi-page PDF: tiny_pdf makes one page, so join several."""
    from pypdf import PdfReader, PdfWriter
    w = PdfWriter()
    for line in lines:
        w.append(PdfReader(io.BytesIO(cb.tiny_pdf([line]))))
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def digest(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def count(p: Path) -> int:
    from pypdf import PdfReader
    return len(PdfReader(str(p)).pages)


# ---------- reading page numbers the way a person writes them ----------
def test_page_ranges_are_read_the_way_people_write_them():
    assert parse_pages("3", 10) == [2]                 # one-based in, zero-based out
    assert parse_pages("2-4", 10) == [1, 2, 3]
    assert parse_pages("1,4,9-10", 10) == [0, 3, 8, 9]
    assert parse_pages("all", 3) == [0, 1, 2]
    assert parse_pages("4-2", 10) == [1, 2, 3]         # backwards is still a range
    assert parse_pages("2,2,3", 10) == [1, 2]          # a repeat is not two pages
    assert parse_pages("last", 5) == [4]


def test_a_page_that_does_not_exist_is_refused_not_clamped():
    """Silently giving pages 1-8 when 9 was asked for would be the wrong kind of helpful."""
    with pytest.raises(ToolError, match="does not exist"):
        parse_pages("9", 8)
    with pytest.raises(ToolError, match="does not exist"):
        parse_pages("1-99", 8)
    with pytest.raises(ToolError, match="not a page number"):
        parse_pages("the last few", 8)


# ---------- joining ----------
async def test_joining_keeps_every_page_and_the_order(tool_ctx):
    d = folder(tool_ctx)
    for n in (1, 2, 3):
        (d / f"invoice {n}.pdf").write_bytes(pages_pdf([f"INVOICE {n}"]))
    before = {p.name: digest(p) for p in d.glob("*.pdf")}

    r = await call(tool_ctx, "combine_pdfs", folder="Scans",
                   files=["invoice 1.pdf", "invoice 2.pdf", "invoice 3.pdf"],
                   file_name="all invoices")
    assert r.ok and r.verified
    out = Path(r.data["path"])
    assert count(out) == 3 == r.data["pages"]
    assert {p.name: digest(p) for p in d.glob("*.pdf") if p.name in before} == before, \
        "joining changed one of the originals"

    # In the order asked for, not the order found on disk.
    from pypdf import PdfReader
    text = [pg.extract_text() or "" for pg in PdfReader(str(out)).pages]
    assert "INVOICE 1" in text[0] and "INVOICE 2" in text[1] and "INVOICE 3" in text[2]


async def test_joining_one_file_is_refused(tool_ctx):
    d = folder(tool_ctx)
    (d / "only.pdf").write_bytes(pages_pdf(["ONE"]))
    with pytest.raises(ToolError, match="at least two"):
        await call(tool_ctx, "combine_pdfs", folder="Scans", files=["only.pdf"])


# ---------- taking pages out ----------
async def test_extracting_takes_the_pages_asked_for(tool_ctx):
    d = folder(tool_ctx)
    (d / "report.pdf").write_bytes(pages_pdf([f"Page {i}" for i in range(1, 9)]))
    before = digest(d / "report.pdf")

    r = await call(tool_ctx, "extract_pages", path="report.pdf", folder="Scans", pages="2-4")
    assert r.ok and r.verified and r.data["pages"] == 3
    from pypdf import PdfReader
    text = " ".join(pg.extract_text() or "" for pg in PdfReader(r.data["path"]).pages)
    assert "Page 2" in text and "Page 4" in text
    assert "Page 5" not in text and "Page 1 " not in text + " "
    assert digest(d / "report.pdf") == before, "the original was modified"


# ---------- splitting ----------
async def test_splitting_loses_no_pages(tool_ctx):
    d = folder(tool_ctx)
    (d / "report.pdf").write_bytes(pages_pdf([f"Page {i}" for i in range(1, 9)]))
    before = digest(d / "report.pdf")

    r = await call(tool_ctx, "split_pdf", path="report.pdf", folder="Scans", every=3)
    assert r.ok and r.verified
    parts = [Path(p) for p in r.data["files"]]
    assert len(parts) == 3                       # 3 + 3 + 2
    assert [count(p) for p in parts] == [3, 3, 2]
    assert sum(count(p) for p in parts) == 8, "a page went missing in the split"
    # Numbered so they sort correctly, and the original untouched.
    assert [p.stem[-1] for p in parts] == ["1", "2", "3"]
    assert digest(d / "report.pdf") == before


async def test_splitting_a_one_page_pdf_is_refused(tool_ctx):
    d = folder(tool_ctx)
    (d / "single.pdf").write_bytes(pages_pdf(["ONE"]))
    with pytest.raises(ToolError, match="nothing to split"):
        await call(tool_ctx, "split_pdf", path="single.pdf", folder="Scans")


# ---------- turning ----------
async def test_rotating_turns_only_the_pages_asked_for(tool_ctx):
    d = folder(tool_ctx)
    (d / "scan.pdf").write_bytes(pages_pdf([f"Page {i}" for i in range(1, 5)]))
    before = digest(d / "scan.pdf")

    r = await call(tool_ctx, "rotate_pdf", path="scan.pdf", folder="Scans",
                   degrees=90, pages="1,3")
    assert r.ok and r.verified
    from pypdf import PdfReader
    turns = [int(p.rotation or 0) % 360 for p in PdfReader(r.data["path"]).pages]
    assert turns == [90, 0, 90, 0], f"turned the wrong pages: {turns}"
    assert digest(d / "scan.pdf") == before


async def test_a_rotation_that_is_not_a_quarter_turn_is_refused(tool_ctx):
    d = folder(tool_ctx)
    (d / "scan.pdf").write_bytes(pages_pdf(["ONE"]))
    with pytest.raises(Exception, match="(?i)quarter|90"):
        await call(tool_ctx, "rotate_pdf", path="scan.pdf", folder="Scans", degrees=45)


# ---------- stamping ----------
async def test_stamping_puts_the_word_on_every_page(tool_ctx):
    d = folder(tool_ctx)
    (d / "bill.pdf").write_bytes(pages_pdf([f"Page {i}" for i in range(1, 4)]))
    before = digest(d / "bill.pdf")

    r = await call(tool_ctx, "stamp_pdf", path="bill.pdf", folder="Scans", text="PAID")
    assert r.ok and r.verified
    assert r.data["stamped"] == 3 and r.data["pages"] == 3
    assert digest(d / "bill.pdf") == before

    from pypdf import PdfReader
    for page in PdfReader(r.data["path"]).pages:
        assert "PAID" in (page.extract_text() or ""), "a page came back without the stamp"


async def test_the_stamp_is_drawn_on_the_page_not_hung_off_it(tool_ctx):
    """The first version used a FreeText annotation.

    It rendered as small left-aligned text instead of a stamp, and an
    annotation can be hidden, left out of a printout, or dropped by the next
    program that touches the file. A document that only says PAID in some
    viewers is worse than one that does not, because the person believes it
    is marked. So the word goes into the page's own content.
    """
    d = folder(tool_ctx)
    (d / "bill2.pdf").write_bytes(pages_pdf(["Total due: N9,000"]))
    r = await call(tool_ctx, "stamp_pdf", path="bill2.pdf", folder="Scans", text="DRAFT")

    from pypdf import PdfReader
    page = PdfReader(r.data["path"]).pages[0]
    assert "DRAFT" in (page.extract_text() or ""), "the stamp is not in the page content"
    annots = page.get("/Annots") or []
    assert not any("DRAFT" in str(a.get_object().get("/Contents", "")) for a in annots), \
        "the stamp is an annotation again"
    # And it has not covered up what the document says.
    assert "9,000" in (page.extract_text() or "")


async def test_a_long_stamp_still_fits_on_the_page(tool_ctx):
    """CONFIDENTIAL is nearly three times the length of PAID."""
    d = folder(tool_ctx)
    (d / "bill3.pdf").write_bytes(pages_pdf(["Quotation"]))
    r = await call(tool_ctx, "stamp_pdf", path="bill3.pdf", folder="Scans", text="CONFIDENTIAL")
    assert r.ok and r.verified and r.data["stamped"] == 1


# ---------- shrinking ----------
async def test_shrinking_a_bloated_pdf_really_shrinks_it(tool_ctx):
    """A page of uncompressed drawing instructions, as many exports produce."""
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, NameObject
    d = folder(tool_ctx)
    w = PdfWriter()
    for _ in range(8):
        w.add_blank_page(width=595, height=842)
    for page in w.pages:
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 12 Tf (hello world) Tj ET\n" * 400)
        page[NameObject("/Contents")] = stream
    with open(d / "bloated.pdf", "wb") as fh:
        w.write(fh)
    before = digest(d / "bloated.pdf")

    r = await call(tool_ctx, "shrink_pdf", path="bloated.pdf", folder="Scans")
    assert r.ok and r.verified
    assert r.data["pages"] == 8, "shrinking must not drop pages"
    assert r.data["bytes_after"] < r.data["bytes_before"] / 2
    assert digest(d / "bloated.pdf") == before


async def test_shrinking_says_so_when_it_cannot_help(tool_ctx):
    """An honest "no" beats a 2% saving reported as a win."""
    d = folder(tool_ctx)
    (d / "tight.pdf").write_bytes(pages_pdf(["ONE"]))
    r = await call(tool_ctx, "shrink_pdf", path="tight.pdf", folder="Scans")
    assert r.ok
    assert "already as small" in r.summary or "%" in r.summary


# ---------- the file it was given ----------
async def test_a_password_protected_pdf_says_so(tool_ctx):
    from pypdf import PdfWriter
    d = folder(tool_ctx)
    w = PdfWriter()
    w.add_blank_page(width=595, height=842)
    w.encrypt("secret")
    with open(d / "locked.pdf", "wb") as fh:
        w.write(fh)
    with pytest.raises(ToolError, match="password"):
        await call(tool_ctx, "split_pdf", path="locked.pdf", folder="Scans")


async def test_a_file_that_is_not_a_pdf_says_so(tool_ctx):
    d = folder(tool_ctx)
    (d / "notes.pdf").write_bytes(b"this is not a pdf at all")
    with pytest.raises(ToolError, match="(?i)could not be opened|no pages"):
        await call(tool_ctx, "shrink_pdf", path="notes.pdf", folder="Scans")
