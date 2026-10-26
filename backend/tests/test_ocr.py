"""Scanned-PDF reading with real Tesseract OCR on synthetic documents.

Skipped automatically where Tesseract isn't installed (it is bundled with Claw's
Windows build; in the Linux workspace it comes from the system).
"""

import threading

from pathlib import Path

import pytest

from claw.documents.ocr import TesseractEngine, parse_tsv
from claw.documents.pdf_pipeline import PdfPipeline, chunks, search
from claw.tools.base import ToolError
from tests.pdf_fixtures import encrypt, merge, page_image, scanned_pdf
from tests.test_documents import make_pdf

ENGINE = TesseractEngine()
needs_ocr = pytest.mark.skipif(not ENGINE.available()[0], reason="Tesseract not installed here")

INVOICE = ["INVOICE NUMBER 4471", "Customer: Adebayo Stores, Ado Ekiti", "Total due: 45,000 naira", "Payment by 30 November 2026"]
MINUTES = ["MEETING MINUTES", "The committee approved the new budget.", "Next meeting: Friday at 10 AM."]


@pytest.fixture
def pipe(tmp_path):
    return PdfPipeline(tmp_path / "cache")


# 1. Normal text-based PDF: no OCR at all
def test_text_pdf_uses_embedded_text_without_ocr(tmp_path, monkeypatch):
    make_pdf(tmp_path / "t.pdf", "Quarterly sales grew twelve percent in Ekiti State")
    engine = TesseractEngine()
    monkeypatch.setattr(engine, "recognize", lambda *a, **k: pytest.fail("OCR must not run on text pages"))
    r = PdfPipeline(tmp_path / "c", engine).read(tmp_path / "t.pdf")
    assert r.pages[0].source == "text" and "twelve percent" in r.pages[0].text


# 2. Clear printed scan
@needs_ocr
def test_clear_scan(tmp_path, pipe):
    scanned_pdf(tmp_path / "s.pdf", [page_image(INVOICE)])
    stages = []
    r = pipe.read(tmp_path / "s.pdf", progress=lambda st, d, t: stages.append(st))
    p = r.pages[0]
    assert p.source == "ocr" and p.status == "ok" and p.confidence > 80
    for needle in ("INVOICE NUMBER 4471", "Adebayo Stores", "45,000 naira"):
        assert needle in p.text
    assert "ocr" in stages and stages[-1] == "done"


# 3. Multi-page scan keeps page order and boundaries
@needs_ocr
def test_multi_page_order(tmp_path, pipe):
    scanned_pdf(tmp_path / "m.pdf", [page_image(INVOICE), page_image(MINUTES), page_image(["APPENDIX", "Signed by the treasurer."])])
    r = pipe.read(tmp_path / "m.pdf")
    assert [p.number for p in r.pages] == [1, 2, 3]
    assert "INVOICE" in r.pages[0].text and "MINUTES" in r.pages[1].text and "APPENDIX" in r.pages[2].text
    full = r.pages_text()
    assert full.index("[Page 1") < full.index("[Page 2") < full.index("[Page 3")


# 4. Rotated and slightly skewed scans
@needs_ocr
def test_rotated_scan_is_turned_upright(tmp_path, pipe):
    scanned_pdf(tmp_path / "r.pdf", [page_image(INVOICE, rotate=90)])
    p = pipe.read(tmp_path / "r.pdf").pages[0]
    assert p.rotation in (90, 270) and "Adebayo Stores" in p.text and "turned" in p.note


@needs_ocr
def test_slightly_skewed_scan(tmp_path, pipe):
    scanned_pdf(tmp_path / "k.pdf", [page_image(INVOICE, rotate=3)])
    p = pipe.read(tmp_path / "k.pdf").pages[0]
    assert p.source == "ocr" and "Adebayo" in p.text and "45,000" in p.text


# 5. Mixed PDF: text pages read directly, scanned pages OCR'd, order kept
@needs_ocr
def test_mixed_pdf(tmp_path, pipe):
    make_pdf(tmp_path / "t1.pdf", "Cover page typed text about the annual report")
    scanned_pdf(tmp_path / "s2.pdf", [page_image(MINUTES)])
    make_pdf(tmp_path / "t3.pdf", "Closing page typed text with contact details")
    merge(tmp_path / "mixed.pdf", [tmp_path / "t1.pdf", tmp_path / "s2.pdf", tmp_path / "t3.pdf"])
    r = pipe.read(tmp_path / "mixed.pdf")
    assert [p.source for p in r.pages] == ["text", "ocr", "text"]
    assert "approved the new budget" in r.pages[1].text
    assert r.counts()["ocr"] == 1 and "1 read by OCR" in r.summary_line()


# 6. Poor-quality scan is flagged, not trusted
@needs_ocr
def test_poor_scan_flagged_low_confidence(tmp_path, pipe):
    scanned_pdf(tmp_path / "bad.pdf", [page_image(INVOICE, quality="poor", font_px=26)])
    r = pipe.read(tmp_path / "bad.pdf")
    p = r.pages[0]
    assert p.status in ("low_confidence", "empty"), (p.status, p.confidence)
    if p.status == "low_confidence":
        assert r.problem_pages() == [1]
        assert "LOW CONFIDENCE" in r.pages_text()


# 7. Encrypted and invalid PDFs
def test_encrypted_pdf_explained(tmp_path, pipe):
    make_pdf(tmp_path / "plain.pdf", "Secret salary figures for the whole company")
    encrypt(tmp_path / "plain.pdf", tmp_path / "locked.pdf", "pa55word")
    with pytest.raises(ToolError, match="password-protected"):
        pipe.read(tmp_path / "locked.pdf")
    r = pipe.read(tmp_path / "locked.pdf", password="pa55word")
    assert "salary figures" in r.pages[0].text


def test_invalid_pdf_explained(tmp_path, pipe):
    (tmp_path / "bad.pdf").write_bytes(b"%PDF-1.4 this is not really a pdf")
    with pytest.raises(ToolError, match="not a valid PDF|could not be opened"):
        pipe.read(tmp_path / "bad.pdf")
    (tmp_path / "empty.pdf").write_bytes(b"")
    with pytest.raises(ToolError):
        pipe.read(tmp_path / "empty.pdf")


# Engine missing: OCR pages fail clearly, text pages still work
def test_missing_ocr_engine(tmp_path):
    make_pdf(tmp_path / "t.pdf", "Typed page still readable without any OCR engine")
    scanned_pdf(tmp_path / "s.pdf", [page_image(MINUTES)])
    merge(tmp_path / "m.pdf", [tmp_path / "t.pdf", tmp_path / "s.pdf"])
    r = PdfPipeline(tmp_path / "c", TesseractEngine(exe="", tessdata=None)).read(tmp_path / "m.pdf")
    assert r.pages[0].source == "text" and r.pages[1].status == "failed"
    assert not r.ocr_available and "not installed" in r.ocr_note


@needs_ocr
def test_cache_avoids_second_ocr(tmp_path, monkeypatch):
    scanned_pdf(tmp_path / "s.pdf", [page_image(INVOICE)])
    engine = TesseractEngine()
    PdfPipeline(tmp_path / "c", engine).read(tmp_path / "s.pdf")
    monkeypatch.setattr(engine, "recognize", lambda *a, **k: pytest.fail("cached document was OCR'd again"))
    again = PdfPipeline(tmp_path / "c", engine).read(tmp_path / "s.pdf")
    assert "Adebayo" in again.pages[0].text


@needs_ocr
def test_cancel(tmp_path, pipe):
    scanned_pdf(tmp_path / "s.pdf", [page_image(INVOICE), page_image(MINUTES)])
    stop = threading.Event()
    stop.set()
    with pytest.raises(ToolError, match="cancelled"):
        pipe.read(tmp_path / "s.pdf", cancel=stop)


@needs_ocr
def test_search_and_chunks_keep_page_numbers(tmp_path, pipe):
    scanned_pdf(tmp_path / "m.pdf", [page_image(INVOICE), page_image(MINUTES)])
    r = pipe.read(tmp_path / "m.pdf")
    hits = search(r, "budget")
    assert [h["page"] for h in hits] == [2] and hits[0]["source"] == "ocr"
    parts = chunks(r, max_chars=200)
    assert parts[0][0] == 1 and parts[-1][1] == 2 and all(len(t) <= 200 for _, _, t in parts)


@needs_ocr
def test_searchable_pdf_copy(tmp_path, pipe):
    make_pdf(tmp_path / "t.pdf", "Typed cover page for the searchable copy test")
    scanned_pdf(tmp_path / "s.pdf", [page_image(INVOICE)])
    merge(tmp_path / "m.pdf", [tmp_path / "t.pdf", tmp_path / "s.pdf"])
    out = pipe.searchable_pdf(tmp_path / "m.pdf", tmp_path / "m (searchable).pdf")
    fresh = PdfPipeline(tmp_path / "other-cache", TesseractEngine(exe="", tessdata=None)).read(out)
    # The copy now has a real text layer: readable even with no OCR engine at all.
    assert [p.source for p in fresh.pages] == ["text", "text"]
    assert "Adebayo" in fresh.pages[1].text
    with pytest.raises(FileExistsError):
        pipe.searchable_pdf(tmp_path / "m.pdf", out)  # never overwrites


def test_parse_tsv_paragraphs():
    tsv = (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        "5\t1\t1\t1\t1\t1\t0\t0\t1\t1\t91\tHello\n"
        "5\t1\t1\t1\t1\t2\t0\t0\t1\t1\t89\tworld\n"
        "5\t1\t2\t1\t1\t1\t0\t0\t1\t1\t70\tNext\n"
    )
    r = parse_tsv(tsv)
    assert r.text == "Hello world\n\nNext" and r.words == 3 and r.confidence == 83.3


@needs_ocr
def test_incomplete_ocr_data_is_reported_not_shown_as_blank(tmp_path):
    """Bundled tessdata without configs/ makes Tesseract print plain text instead of TSV.
    That must surface as "OCR unavailable", never as an empty page."""
    import shutil as sh

    src = Path(ENGINE.tessdata or "/usr/share/tesseract-ocr/5/tessdata")
    if not (src / "eng.traineddata").is_file():
        pytest.skip("system tessdata not found")
    broken = tmp_path / "tessdata"
    broken.mkdir()
    for f in ("eng.traineddata", "osd.traineddata"):
        sh.copy(src / f, broken / f)
    eng = TesseractEngine(exe=ENGINE.exe)
    eng.tessdata = str(broken)
    ok, why = eng.available("eng")
    assert not ok and "incomplete" in why
    pdf = scanned_pdf(tmp_path / "s.pdf", [page_image(INVOICE)])
    r = PdfPipeline(tmp_path / "cache", engine=eng).read(pdf)
    assert not r.ocr_available and "incomplete" in r.ocr_note
    assert r.pages[0].status == "failed" and r.pages[0].text == ""
