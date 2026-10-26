"""Documents the user opens in Claw's Documents view.

Reading (including OCR) runs in a worker thread with real progress; it does not
need the language model at all. A document the user opened through the file
dialog becomes readable by the agent's tools even if it isn't inside an
authorized folder (opening it was the user's explicit choice).
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from claw.documents.pdf_pipeline import DocumentResult, PdfPipeline, search
from claw.documents.readers import read_document
from claw.tools.base import ToolError


@dataclass
class DocJob:
    id: str
    path: str
    name: str
    status: str = "reading"  # reading | done | failed | cancelled
    stage: str = "checking"
    done: int = 0
    total: int = 0
    error: str = ""
    result: DocumentResult | None = None
    plain_text: str | None = None  # non-PDF documents
    cancel: threading.Event = field(default_factory=threading.Event)

    def status_dict(self, with_pages: bool = False) -> dict:
        d = {
            "id": self.id, "path": self.path, "name": self.name, "status": self.status, "stage": self.stage,
            "done": self.done, "total": self.total, "error": self.error,
        }
        if self.result is not None:
            d["summary"] = self.result.summary_line()
            d["counts"] = self.result.counts()
            d["page_count"] = self.result.page_count
            d["problem_pages"] = self.result.problem_pages()
            d["ocr_available"] = self.result.ocr_available
            d["ocr_note"] = self.result.ocr_note
            if with_pages:
                d["pages"] = [p.__dict__ for p in self.result.pages]
        elif self.plain_text is not None:
            d["summary"] = "Text document"
            if with_pages:
                d["pages"] = [{"number": 1, "text": self.plain_text, "source": "text", "status": "ok", "confidence": None, "rotation": 0, "note": ""}]
        return d


class DocumentService:
    def __init__(self, pipeline: PdfPipeline):
        self.pipeline = pipeline
        self.jobs: dict[str, DocJob] = {}
        self.opened_paths: set[str] = set()

    def open(self, path: Path) -> DocJob:
        path = path.resolve()
        if not path.is_file():
            raise ToolError("That file doesn't exist.")
        for job in self.jobs.values():  # same file already open: reuse
            if job.path == str(path) and job.status in ("reading", "done"):
                return job
        job = DocJob(uuid.uuid4().hex, str(path), path.name)
        self.jobs[job.id] = job
        self.opened_paths.add(str(path))
        asyncio.get_running_loop().run_in_executor(None, self._work, job)
        return job

    def _work(self, job: DocJob) -> None:
        def progress(stage, done, total):
            job.stage, job.done, job.total = stage, done, total

        try:
            if job.path.lower().endswith(".pdf"):
                job.result = self.pipeline.read(Path(job.path), progress=progress, cancel=job.cancel)
            else:
                job.plain_text = read_document(Path(job.path))
            job.status = "done"
        except ToolError as exc:
            job.status = "cancelled" if job.cancel.is_set() else "failed"
            job.error = exc.message
        except Exception as exc:  # noqa: BLE001 — a bad file must not take the backend down
            job.status, job.error = "failed", f"The document could not be read ({type(exc).__name__})."

    def get(self, doc_id: str) -> DocJob | None:
        return self.jobs.get(doc_id)

    def search(self, job: DocJob, query: str) -> list[dict]:
        if job.result is not None:
            return search(job.result, query)
        if job.plain_text is not None:
            from claw.documents.pdf_pipeline import PageResult

            fake = DocumentResult(job.path, "", [PageResult(1, job.plain_text, "text", "ok")], "", "", 0)
            return search(fake, query)
        return []
