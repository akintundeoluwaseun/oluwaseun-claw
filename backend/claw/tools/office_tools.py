"""Milestone 5 (challenge section 8): PowerPoint decks, and PDF export through LibreOffice when it is installed.

python-pptx (MIT) writes the .pptx; S-CLAW reopens it and checks the slide count, every title and the
speaker notes before saying it is done. When LibreOffice is installed (it is optional, never bundled),
the deck or a Word file can also be exported to PDF, and the PDF's page count is checked. Without
LibreOffice the PDF step says so plainly instead of pretending.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from claw.agent.schemas import Capability
from claw.integrations import images as im
from claw.permissions.policy import RiskLevel
from claw.tools.base import ToolArgs, ToolContext, ToolError, ToolRegistry, ToolResult, ToolSpec
from claw.tools.file_tools import existing_folder, safe_file_name, unique_path


class Chart(BaseModel):
    labels: list[str] = Field(min_length=1, max_length=24)
    values: list[float] = Field(min_length=1, max_length=24)
    kind: Literal["bar", "line", "pie"] = "bar"

    @model_validator(mode="after")
    def _same(self):
        if len(self.labels) != len(self.values):
            raise ValueError("labels and values must be the same length")
        return self


class Slide(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    bullets: list[str] = Field(default_factory=list, max_length=10)
    notes: str = Field(default="", max_length=3000)
    chart: Chart | None = None

    @model_validator(mode="before")
    @classmethod
    def _names(cls, v):
        if isinstance(v, dict):
            v = dict(v)
            for want, alts in (("title", ("heading", "name")), ("bullets", ("points", "content", "body", "text")),
                               ("notes", ("speaker_notes", "note"))):
                for a in alts:
                    if want not in v and a in v:
                        v[want] = v.pop(a)
            if isinstance(v.get("bullets"), str):
                v["bullets"] = [b.strip(" -•*") for b in v["bullets"].split("\n") if b.strip(" -•*")]
        return v


class DeckArgs(ToolArgs):
    title: str = Field(min_length=1, max_length=120)
    subtitle: str = Field(default="", max_length=200)
    slides: list[Slide] = Field(min_length=1, max_length=60)
    file_name: str = Field(default="", max_length=100)
    folder: str | None = Field(default=None, max_length=500)
    accent: str = Field(default="#3cc2aa", max_length=20, description="A colour code or name")
    pdf: bool = Field(default=False, description="Also save a PDF (needs LibreOffice)")

    @field_validator("accent", mode="before")
    @classmethod
    def _colour(cls, v):
        from claw.tools.image_tools import _COLOURS  # noqa: PLC0415
        t = str(v or "").strip().lower()
        return t if t.startswith("#") and len(t) in (4, 7) else _COLOURS.get(t, "#3cc2aa")


# ---------- LibreOffice (optional) ----------
def soffice() -> str | None:
    found = shutil.which("soffice") or shutil.which("libreoffice")
    if found:
        return found
    if sys.platform == "win32":
        for base in (os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", "")):
            p = Path(base) / "LibreOffice" / "program" / "soffice.exe"
            if p.is_file():
                return str(p)
    return None


def to_pdf(src: Path, timeout: float = 180) -> Path:
    exe = soffice()
    if not exe:
        raise ToolError("Saving as PDF needs LibreOffice (free), which is not installed. The file itself was saved.")
    out_dir = Path(tempfile.mkdtemp(prefix="claw-pdf-"))
    profile = Path(tempfile.mkdtemp(prefix="claw-lo-"))
    try:
        subprocess.run([exe, f"-env:UserInstallation=file:///{profile.as_posix().lstrip('/')}", "--headless", "--norestore",
                        "--convert-to", "pdf", "--outdir", str(out_dir), str(src)],
                       capture_output=True, timeout=timeout, check=False,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired as exc:
        raise ToolError("LibreOffice took too long to make the PDF.") from exc
    made = out_dir / (src.stem + ".pdf")
    if not made.is_file():
        raise ToolError("LibreOffice ran but did not make a PDF.")
    final = unique_path(src.with_suffix(".pdf"))
    shutil.move(str(made), final)
    shutil.rmtree(profile, ignore_errors=True)
    return final


def pdf_pages(path: Path) -> int:
    from pypdf import PdfReader  # noqa: PLC0415
    return len(PdfReader(str(path)).pages)


# ---------- make_presentation ----------
def _build_deck(args: DeckArgs, out: Path) -> None:
    from pptx import Presentation  # noqa: PLC0415
    from pptx.chart.data import CategoryChartData  # noqa: PLC0415
    from pptx.dml.color import RGBColor  # noqa: PLC0415
    from pptx.enum.chart import XL_CHART_TYPE  # noqa: PLC0415
    from pptx.util import Inches, Pt  # noqa: PLC0415

    from pptx.enum.shapes import MSO_SHAPE  # noqa: PLC0415
    from pptx.enum.text import PP_ALIGN  # noqa: PLC0415

    accent = RGBColor(*im.hex_rgb(args.accent))
    dark = RGBColor(0x16, 0x1B, 0x22)
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)       # 16:9
    W, M = prs.slide_width, Inches(0.7)

    def fit(shape, top, height):
        # The default template's boxes are laid out for 4:3; stretch them to the 16:9 page.
        shape.left, shape.top, shape.width, shape.height = M, top, W - 2 * M, height

    def style_title(slide, size):
        t = slide.shapes.title
        fit(t, Inches(0.45), Inches(1.0))
        para = t.text_frame.paragraphs[0]
        para.alignment = PP_ALIGN.LEFT
        para.runs[0].font.size, para.runs[0].font.bold, para.runs[0].font.color.rgb = Pt(size), True, dark
        bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, M, Inches(1.45), Inches(1.2), Inches(0.08))
        bar.fill.solid()
        bar.fill.fore_color.rgb = accent
        bar.line.fill.background()

    cover = prs.slides.add_slide(prs.slide_layouts[0])
    cover.background.fill.solid()
    cover.background.fill.fore_color.rgb = dark
    cover.shapes.title.text = args.title
    fit(cover.shapes.title, Inches(2.4), Inches(1.6))
    run = cover.shapes.title.text_frame.paragraphs[0].runs[0]
    run.font.size, run.font.bold, run.font.color.rgb = Pt(44), True, RGBColor(0xFF, 0xFF, 0xFF)
    cover.shapes.title.text_frame.paragraphs[0].alignment = PP_ALIGN.LEFT
    sub_box = cover.placeholders[1]
    sub_box.text = args.subtitle or ""
    fit(sub_box, Inches(4.1), Inches(1.0))
    if sub_box.text_frame.paragraphs[0].runs:
        r = sub_box.text_frame.paragraphs[0].runs[0]
        r.font.size, r.font.color.rgb = Pt(22), accent
        sub_box.text_frame.paragraphs[0].alignment = PP_ALIGN.LEFT
    for s in args.slides:
        layout = prs.slide_layouts[5] if s.chart else prs.slide_layouts[1]
        slide = prs.slides.add_slide(layout)
        slide.shapes.title.text = s.title
        style_title(slide, 34)
        if s.chart:
            data = CategoryChartData()
            data.categories = s.chart.labels
            data.add_series(s.title[:40], s.chart.values)
            kind = {"bar": XL_CHART_TYPE.COLUMN_CLUSTERED, "line": XL_CHART_TYPE.LINE_MARKERS, "pie": XL_CHART_TYPE.PIE}[s.chart.kind]
            gf = slide.shapes.add_chart(kind, M, Inches(1.8), W - 2 * M, Inches(5.2), data)
            gf.chart.has_legend = s.chart.kind == "pie"
            if s.chart.kind != "pie":
                gf.chart.plots[0].series[0].format.fill.solid()
                gf.chart.plots[0].series[0].format.fill.fore_color.rgb = accent
        else:
            fit(slide.placeholders[1], Inches(1.8), Inches(5.2))
            body = slide.placeholders[1].text_frame
            body.clear()
            for i, b in enumerate(s.bullets or [""]):
                p = body.paragraphs[0] if i == 0 else body.add_paragraph()
                p.text = b
                p.font.size = Pt(24 if len(s.bullets) <= 5 else 20)
        if s.notes:
            slide.notes_slide.notes_text_frame.text = s.notes
    with open(out, "xb") as fh:                                          # never overwrite
        prs.save(fh)


def _check_deck(out: Path, args: DeckArgs) -> tuple[bool, str]:
    from pptx import Presentation  # noqa: PLC0415
    prs = Presentation(str(out))
    slides = list(prs.slides)
    titles = [sl.shapes.title.text if sl.shapes.title is not None else "" for sl in slides]
    want = [args.title] + [s.title for s in args.slides]
    notes_ok = all((not s.notes) or slides[i + 1].notes_slide.notes_text_frame.text.strip() == s.notes.strip()
                   for i, s in enumerate(args.slides))
    charts = sum(1 for sl in slides for sh in sl.shapes if sh.has_chart)
    ok = len(slides) == len(want) and titles == want and notes_ok and charts == sum(1 for s in args.slides if s.chart)
    return ok, f"reopened: {len(slides)} slides, titles {'match' if titles == want else 'DO NOT match'}" \
               f"{', speaker notes match' if any(s.notes for s in args.slides) and notes_ok else ''}" \
               f"{f', {charts} chart(s)' if charts else ''}"


async def make_presentation(args: DeckArgs, ctx: ToolContext) -> ToolResult:
    folder = existing_folder(ctx, args.folder, write=True)
    out = unique_path(folder / safe_file_name(args.file_name or args.title, ".pptx"))
    ctx.policy.check_path(out, write=True)
    await asyncio.to_thread(_build_deck, args, out)
    ok, how = await asyncio.to_thread(_check_deck, out, args)
    extra = ""
    if args.pdf:
        try:
            pdf = await asyncio.to_thread(to_pdf, out)
            n = await asyncio.to_thread(pdf_pages, pdf)
            ok = ok and n == len(args.slides) + 1
            extra = f" Also saved {pdf.name} ({n} pages)."
            ctx.memory.outputs.append({"path": str(pdf), "kind": "pdf", "verified": n == len(args.slides) + 1, "note": ""})
        except ToolError as exc:
            extra = f" No PDF: {exc.message}"
    ctx.memory.outputs.append({"path": str(out), "kind": "presentation", "verified": ok, "note": "" if ok else how})
    return ToolResult(True, f"Saved {out.name} with {len(args.slides) + 1} slides (title slide included); {how}.{extra}",
                      {"path": str(out), "slides": len(args.slides) + 1}, verified=ok)


# ---------- export_pdf ----------
class PdfArgs(ToolArgs):
    path: str = Field(min_length=1, max_length=500, description="A .docx, .pptx, .xlsx or .odt file")


async def export_pdf(args: PdfArgs, ctx: ToolContext) -> ToolResult:
    from claw.tools.table_tools import find_table  # noqa: PLC0415 - same loose lookup by name
    try:
        src = ctx.policy.check_path(args.path)
        if not src.is_file():
            raise FileNotFoundError
    except Exception:  # noqa: BLE001
        src = find_table(ctx, args.path) if Path(args.path).suffix.lower() in (".xlsx", ".csv") else None
        if src is None:
            raise ToolError(f"There is no file '{args.path}'.") from None
    if src.suffix.lower() not in (".docx", ".pptx", ".xlsx", ".odt", ".odp", ".ods", ".doc", ".ppt", ".xls", ".rtf"):
        raise ToolError("Only office documents can be exported to PDF this way.")
    ctx.policy.check_path(src.with_suffix(".pdf"), write=True)
    pdf = await asyncio.to_thread(to_pdf, src)
    n = await asyncio.to_thread(pdf_pages, pdf)
    ctx.memory.outputs.append({"path": str(pdf), "kind": "pdf", "verified": n > 0, "note": ""})
    return ToolResult(n > 0, f"Saved {pdf.name} ({n} page(s)) next to {src.name}, made by LibreOffice. The original is untouched.",
                      {"path": str(pdf), "pages": n}, verified=n > 0)


def register_office_tools(reg: ToolRegistry) -> None:
    D, W = Capability.DOCUMENTS, RiskLevel.LOCAL_WRITE
    reg.register(ToolSpec("make_presentation", "Make a PowerPoint deck (slides, bullets, speaker notes, charts).", D, W, DeckArgs, make_presentation))
    reg.register(ToolSpec("export_pdf", "Save a Word/PowerPoint/Excel file as PDF (needs LibreOffice).", D, W, PdfArgs, export_pdf))
