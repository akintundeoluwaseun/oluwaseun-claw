"""Read PDFs page by page, using OCR only where a page has no usable text.

1. Open with pdfium (pypdfium2). Encrypted or broken files fail with a clear message.
2. For each page, take the embedded text. If it has enough real characters, use it.
3. Otherwise render the page at 300 DPI and recognise it with the OCR engine
   (turning it upright first if it was scanned sideways or upside down).
4. Keep page order and boundaries; label each page with where its text came
   from and how confident the OCR was.
5. Cache the result by file content, so a document is only recognised once.

Recognised text is untrusted content: it is shown to the model as data only.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from claw.documents.ocr import OcrUnavailable, TesseractEngine, default_engine
from claw.tools.base import ToolError

MIN_TEXT_CHARS = 25  # fewer letters/digits than this on a page → treat as scanned
LOW_CONFIDENCE = 60.0
RENDER_DPI = 300
MAX_PAGES = 500
CACHE_VERSION = 2

Progress = Callable[[str, int, int], None]  # (stage, done, total)


@dataclass
class PageResult:
    number: int
    text: str
    source: str  # "text" (from the PDF) | "ocr" | "empty"
    status: str  # "ok" | "low_confidence" | "failed" | "empty"
    confidence: float | None = None
    rotation: int = 0
    note: str = ""


@dataclass
class DocumentResult:
    path: str
    sha256: str
    pages: list[PageResult]
    engine: str
    language: str
    seconds: float
    ocr_available: bool = True
    ocr_note: str = ""
    errors: list[str] = field(default_factory=list)

    @property
    def page_count(self) -> int:
        return len(self.pages)

    def counts(self) -> dict[str, int]:
        c = {"text": 0, "ocr": 0, "failed": 0, "low_confidence": 0, "empty": 0}
        for p in self.pages:
            if p.source == "text":
                c["text"] += 1
            elif p.source == "ocr":
                c["ocr"] += 1
            if p.status in ("failed", "low_confidence", "empty"):
                c[p.status] += 1
        return c

    def summary_line(self) -> str:
        c = self.counts()
        parts = [f"{self.page_count} page" + ("" if self.page_count == 1 else "s")]
        if c["text"]:
            parts.append(f"{c['text']} with text in the file")
        if c["ocr"]:
            parts.append(f"{c['ocr']} read by OCR")
        if c["low_confidence"]:
            parts.append(f"{c['low_confidence']} low-confidence")
        if c["failed"]:
            parts.append(f"{c['failed']} could not be read")
        if c["empty"]:
            parts.append(f"{c['empty']} blank")
        return ", ".join(parts)

    def problem_pages(self) -> list[int]:
        return [p.number for p in self.pages if p.status in ("failed", "low_confidence")]

    def to_json(self) -> dict:
        d = asdict(self)
        d["counts"] = self.counts()
        d["summary"] = self.summary_line()
        return d

    @classmethod
    def from_json(cls, d: dict) -> "DocumentResult":
        d = dict(d)
        d.pop("counts", None)
        d.pop("summary", None)
        d["pages"] = [PageResult(**p) for p in d["pages"]]
        return cls(**d)

    def page_text(self, p: PageResult) -> str:
        label = {"text": "text from the PDF", "ocr": "recognised by OCR", "empty": "blank page"}[p.source]
        extra = f", confidence {p.confidence:.0f}%" if p.confidence is not None else ""
        warn = " — LOW CONFIDENCE, may contain errors" if p.status == "low_confidence" else ""
        warn = " — COULD NOT BE READ" if p.status == "failed" else warn
        return f"[Page {p.number} · {label}{extra}{warn}]\n{p.text}".rstrip()

    def pages_text(self, first: int = 1, last: int | None = None) -> str:
        last = last or self.page_count
        return "\n\n".join(self.page_text(p) for p in self.pages if first <= p.number <= last)


def _usable(text: str) -> bool:
    return len(re.findall(r"[A-Za-z0-9]", text)) >= MIN_TEXT_CHARS


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _open(path: Path, password: str | None):
    import pypdfium2 as pdfium

    try:
        return pdfium.PdfDocument(str(path), password=password)
    except pdfium.PdfiumError as exc:
        text = str(exc).lower()
        if "password" in text:
            raise ToolError("This PDF is password-protected. Claw can't read it without the password.") from exc
        if "format" in text or "file" in text or "data" in text:
            raise ToolError("This file is not a valid PDF, or it is damaged.") from exc
        raise ToolError(f"The PDF could not be opened: {exc}") from exc


def _render(page, out: Path) -> None:
    bitmap = page.render(scale=RENDER_DPI / 72, grayscale=True)
    bitmap.to_pil().save(out)


class PdfPipeline:
    def __init__(self, cache_dir: Path, engine: TesseractEngine | None = None, language: str = "eng"):
        self.cache_dir = cache_dir
        self.engine = engine or default_engine()
        self.language = language
        self._locks: dict[str, threading.Lock] = {}

    def _cache_file(self, sha: str) -> Path:
        return self.cache_dir / f"{sha}-{self.engine.name}-{self.language}-v{CACHE_VERSION}.json"

    def cached(self, path: Path) -> DocumentResult | None:
        f = self._cache_file(file_sha256(path))
        if f.exists():
            try:
                res = DocumentResult.from_json(json.loads(f.read_text(encoding="utf-8")))
                res.path = str(path)
                return res
            except (ValueError, TypeError, KeyError):
                return None
        return None

    def read(self, path: Path, progress: Progress | None = None, password: str | None = None,
             cancel: threading.Event | None = None) -> DocumentResult:
        """Blocking; run it in a worker thread."""
        progress = progress or (lambda *_: None)
        path = Path(path)
        if not path.is_file():
            raise ToolError(f"'{path}' is not a file.")
        sha = file_sha256(path)
        lock = self._locks.setdefault(sha, threading.Lock())
        with lock:  # two requests for the same file share one OCR run
            hit = self.cached(path)
            if hit is not None:
                progress("done", hit.page_count, hit.page_count)
                return hit
            result = self._read(path, sha, progress, password, cancel)
            if not result.errors or result.page_count:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                self._cache_file(sha).write_text(json.dumps(result.to_json()), encoding="utf-8")
            return result

    def _read(self, path, sha, progress, password, cancel) -> DocumentResult:
        started = time.monotonic()
        doc = _open(path, password)
        try:
            total = len(doc)
            if total == 0:
                raise ToolError("This PDF has no pages.")
            if total > MAX_PAGES:
                raise ToolError(f"This PDF has {total} pages; Claw reads up to {MAX_PAGES}.")
            pages: list[PageResult] = []
            needs_ocr: list[int] = []
            progress("checking", 0, total)
            for i in range(total):
                page = doc[i]
                try:
                    tp = page.get_textpage()
                    text = tp.get_text_bounded().replace("\r\n", "\n").replace("\r", "\n").strip()
                    tp.close()
                except Exception:  # noqa: BLE001 — a page with a broken text layer goes to OCR
                    text = ""
                if _usable(text):
                    pages.append(PageResult(i + 1, text, "text", "ok"))
                else:
                    pages.append(PageResult(i + 1, "", "empty", "empty"))
                    needs_ocr.append(i)
                progress("checking", i + 1, total)

            ok, why = self.engine.available(self.language) if needs_ocr else (True, "")
            result = DocumentResult(str(path), sha, pages, self.engine.name, self.language, 0.0, ok, why)
            if needs_ocr and not ok:
                for i in needs_ocr:
                    pages[i].status, pages[i].note = "failed", why
                result.errors.append(why)
            elif needs_ocr:
                self._ocr_pages(doc, pages, needs_ocr, progress, cancel, result)
            result.seconds = round(time.monotonic() - started, 2)
            progress("done", total, total)
            return result
        finally:
            doc.close()

    def _ocr_pages(self, doc, pages, needs_ocr, progress, cancel, result) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="claw-ocr-"))
        has_osd = self.engine.has_osd()
        try:
            for n, i in enumerate(needs_ocr, 1):
                if cancel is not None and cancel.is_set():
                    raise ToolError("Reading the document was cancelled.")
                progress("ocr", n - 1, len(needs_ocr))
                page = pages[i]
                img = tmp / f"p{i + 1}.png"
                try:
                    _render(doc[i], img)
                    ocr = self.engine.recognize(img, self.language)
                    # Sideways or upside-down scans read badly: turn upright and try again.
                    if has_osd and (ocr.confidence is None or ocr.confidence < 75 or ocr.words < 5):
                        rot = self.engine.detect_rotation(img)
                        if rot:
                            from PIL import Image

                            with Image.open(img) as im:
                                im.rotate(-rot, expand=True).save(img)
                            again = self.engine.recognize(img, self.language)
                            if (again.confidence or 0) >= (ocr.confidence or 0):
                                again.rotation = rot
                                ocr = again
                except OcrUnavailable as exc:
                    page.status, page.note = "failed", exc.message
                    result.errors.append(exc.message)
                    continue
                except ToolError as exc:
                    page.status, page.note = "failed", exc.message
                    continue
                if not ocr.text.strip():
                    page.source, page.status, page.note = "empty", "empty", "No text was found on this page."
                    continue
                page.text, page.source, page.confidence, page.rotation = ocr.text, "ocr", ocr.confidence, ocr.rotation
                page.status = "low_confidence" if (ocr.confidence or 0) < LOW_CONFIDENCE else "ok"
                if ocr.rotation:
                    page.note = f"Page was turned {ocr.rotation}° before reading."
            progress("ocr", len(needs_ocr), len(needs_ocr))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def searchable_pdf(self, path: Path, out: Path, password: str | None = None, progress: Progress | None = None) -> Path:
        """A copy where scanned pages get an invisible text layer. Text pages are kept as they are."""
        from pypdf import PdfReader, PdfWriter

        progress = progress or (lambda *_: None)
        result = self.read(path, password=password)
        if not result.ocr_available:
            raise ToolError(result.ocr_note)
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            if not reader.decrypt(password or ""):
                raise ToolError("This PDF is password-protected.")
        writer = PdfWriter()
        tmp = Path(tempfile.mkdtemp(prefix="claw-spdf-"))
        doc = _open(path, password)
        try:
            ocr_pages = [p for p in result.pages if p.source == "ocr"]
            done = 0
            for p in result.pages:
                if p.source != "ocr":
                    writer.add_page(reader.pages[p.number - 1])
                    continue
                img = tmp / f"p{p.number}.png"
                _render(doc[p.number - 1], img)
                if p.rotation:
                    from PIL import Image

                    with Image.open(img) as im:
                        im.rotate(-p.rotation, expand=True).save(img)
                single = self.engine.searchable_pdf(img, tmp / f"p{p.number}", self.language)
                writer.add_page(PdfReader(str(single)).pages[0])
                done += 1
                progress("searchable", done, len(ocr_pages))
            with open(out, "xb") as fh:  # never overwrite
                writer.write(fh)
        finally:
            doc.close()
            shutil.rmtree(tmp, ignore_errors=True)
        return out


def search(result: DocumentResult, query: str, limit: int = 50) -> list[dict]:
    q = query.strip().lower()
    if not q:
        return []
    hits = []
    for p in result.pages:
        low = p.text.lower()
        start = 0
        while (i := low.find(q, start)) != -1 and len(hits) < limit:
            a, b = max(0, i - 80), min(len(p.text), i + len(q) + 80)
            hits.append({
                "page": p.number, "source": p.source, "status": p.status,
                "snippet": (("…" if a else "") + p.text[a:b].replace("\n", " ") + ("…" if b < len(p.text) else "")),
            })
            start = i + len(q)
    return hits


def chunks(result: DocumentResult, max_chars: int = 6000) -> list[tuple[int, int, str]]:
    """Bounded, page-aware chunks: (first_page, last_page, text). Long pages are split."""
    out: list[tuple[int, int, str]] = []
    buf, first, last = [], None, None
    size = 0
    for p in result.pages:
        block = result.page_text(p)
        if len(block) > max_chars:
            if buf:
                out.append((first, last, "\n\n".join(buf)))
                buf, first, size = [], None, 0
            for k in range(0, len(block), max_chars):
                out.append((p.number, p.number, block[k : k + max_chars]))
            continue
        if size + len(block) > max_chars and buf:
            out.append((first, last, "\n\n".join(buf)))
            buf, first, size = [], None, 0
        buf.append(block)
        first = first or p.number
        last = p.number
        size += len(block) + 2
    if buf:
        out.append((first, last, "\n\n".join(buf)))
    return out
