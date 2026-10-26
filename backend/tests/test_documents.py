"""Document reading and writing tools (real files, real libraries)."""

import csv

import docx
import pytest
from openpyxl import Workbook, load_workbook

from claw.documents.readers import read_document
from claw.tools.base import ToolError
from claw.tools.registry import build_registry

REG = build_registry()


async def call(ctx, tool_name, **args):
    spec = REG.get(tool_name)
    parsed = spec.parse_args(args)
    if spec.precheck:
        spec.precheck(parsed, ctx)
    return await spec.handler(parsed, ctx)


def make_pdf(path, text):
    """Minimal one-page PDF with real text (no extra libraries)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    path.write_bytes(bytes(out))


@pytest.fixture
def folder(tool_ctx, tmp_path):
    return tmp_path / "saved"


def test_read_pdf_docx_xlsx(tmp_path):
    make_pdf(tmp_path / "a.pdf", "Invoice total 45000 naira")
    assert "Invoice total 45000 naira" in read_document(tmp_path / "a.pdf")
    d = docx.Document()
    d.add_paragraph("Meeting notes for Monday")
    t = d.add_table(rows=1, cols=2)
    t.rows[0].cells[0].text, t.rows[0].cells[1].text = "Item", "Owner"
    d.save(tmp_path / "b.docx")
    text = read_document(tmp_path / "b.docx")
    assert "Meeting notes for Monday" in text and "Item | Owner" in text
    wb = Workbook()
    wb.active.append(["Name", "Phone"])
    wb.active.append(["Ade", "0803"])
    wb.save(tmp_path / "c.xlsx")
    assert "Ade,0803" in read_document(tmp_path / "c.xlsx")
    (tmp_path / "d.exe").write_bytes(b"MZ")
    with pytest.raises(ToolError, match="isn't supported"):
        read_document(tmp_path / "d.exe")


async def test_read_file_tool_records_seen(tool_ctx, folder):
    make_pdf(folder / "report.pdf", "Quarterly sales grew 12 percent")
    r = await call(tool_ctx, "read_file", path=str(folder / "report.pdf"))
    assert "12 percent" in r.untrusted_text and str(folder / "report.pdf") in tool_ctx.memory.seen_files


async def test_write_text_file_never_overwrites(tool_ctx, folder):
    a = await call(tool_ctx, "write_text_file", file_name="summary.md", text="# Hi")
    b = await call(tool_ctx, "write_text_file", file_name="summary.md", text="# Again")
    assert a.verified and b.data["path"].endswith("summary (2).md")
    assert (folder / "summary.md").read_text() == "# Hi"
    with pytest.raises(ToolError):
        REG.get("write_text_file").parse_args({"file_name": "run.bat", "text": "x"})


async def test_report_only_cites_opened_sources(tool_ctx, folder, site):
    url = site.base_url + "/articles/motion-templates"
    args = dict(title="Motion templates", sections=[{"heading": "Findings", "body": "Two good free packs."}],
                sources=[{"title": "Free templates", "location": url}])
    with pytest.raises(ToolError, match="not opened"):
        await call(tool_ctx, "save_report", **args)
    await call(tool_ctx, "open_url", url=url)
    r = await call(tool_ctx, "save_report", **args)
    assert r.verified and r.data["path"].endswith("Motion templates.docx")
    doc = docx.Document(r.data["path"])
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "Findings" in text and url in text and "Sources" in text
    md = await call(tool_ctx, "save_report", **{**args, "format": "md"})
    assert url in open(md.data["path"], encoding="utf-8").read()
    assert [o["kind"] for o in tool_ctx.memory.outputs] == ["report", "report"]


async def test_spreadsheet_provenance_and_formula_safety(tool_ctx, folder):
    tool_ctx.memory.seen_text.append("Ekiti Grand Hotel  0803 111 2233  info@ekitigrand.example")
    r = await call(tool_ctx, "create_spreadsheet", file_name="hotels", columns=["Name", "Phone", "Email"],
                   rows=[["Ekiti Grand Hotel", "0803 111 2233", "info@ekitigrand.example"],
                         ["Made Up Hotel", "0800 000 0000", "=HYPERLINK(\"http://evil\")"]])
    assert r.verified and r.data["rows"] == 2
    assert r.data["checked"] == 6 and r.data["found"] == 3
    note = tool_ctx.memory.outputs[-1]["note"]
    assert "3 of 6" in note and "Made Up Hotel" in note
    ws = load_workbook(r.data["path"]).active
    assert ws["A1"].value == "Name" and ws["A1"].font.bold
    assert ws["C3"].value.startswith("'=")  # stored as text, not a formula
    c = await call(tool_ctx, "create_spreadsheet", file_name="hotels", format="csv", columns=["Name"], rows=[["Ekiti Grand Hotel"]])
    with open(c.data["path"], encoding="utf-8-sig", newline="") as fh:
        assert list(csv.reader(fh)) == [["Name"], ["Ekiti Grand Hotel"]]


def test_spreadsheet_row_width_checked():
    with pytest.raises(ToolError, match="row 1 has 3 values"):
        REG.get("create_spreadsheet").parse_args({"file_name": "x", "columns": ["a", "b"], "rows": [[1, 2, 3]]})


async def test_edit_keeps_backup(tool_ctx, folder):
    f = folder / "todo.txt"
    f.write_text("buy rice\nbuy beans\n", encoding="utf-8")
    with pytest.raises(ToolError, match="appears 2 times"):
        await call(tool_ctx, "edit_text_file", path=str(f), find="buy", replace_with="get")
    with pytest.raises(ToolError, match="not found"):
        await call(tool_ctx, "edit_text_file", path=str(f), find="yam", replace_with="x")
    r = await call(tool_ctx, "edit_text_file", path=str(f), find="buy rice", replace_with="buy ofada rice")
    assert r.verified and f.read_text() == "buy ofada rice\nbuy beans\n"
    assert open(r.data["backup"]).read() == "buy rice\nbuy beans\n"
