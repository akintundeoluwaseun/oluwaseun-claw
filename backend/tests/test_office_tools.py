"""Milestone 5 (section 8): PowerPoint decks reopened and checked; Word reports with contents and real lists; PDF via LibreOffice."""

from pathlib import Path

import docx
import pytest
from pptx import Presentation

from claw.tools.office_tools import soffice
from tests.test_phase_a import call

SLIDES = [{"title": "The problem", "bullets": ["Shops lose track of repairs", "Customers wait without news"], "notes": "Open with a story."},
          {"heading": "Sales so far", "chart": {"labels": ["Jan", "Feb", "Mar"], "values": [120, 150, 210]}},
          {"title": "Next steps", "points": "- Hire two technicians\n- Open in Akure"}]


def out(tool_ctx):
    return Path(tool_ctx.settings.permissions.authorized_folders[0])


async def test_deck_is_built_and_checked(tool_ctx):
    r = await call(tool_ctx, "make_presentation", title="TechDesk investor update", subtitle="November 2026", slides=SLIDES, accent="gold")
    assert r.verified and r.data["slides"] == 4 and "titles match" in r.summary and "speaker notes match" in r.summary
    prs = Presentation(str(out(tool_ctx) / "TechDesk investor update.pptx"))
    s = list(prs.slides)
    assert [x.shapes.title.text for x in s] == ["TechDesk investor update", "The problem", "Sales so far", "Next steps"]
    assert any(sh.has_chart for sh in s[2].shapes)
    assert "Open in Akure" in s[3].placeholders[1].text_frame.text


async def test_word_report_has_contents_page_numbers_and_lists(tool_ctx):
    r = await call(tool_ctx, "save_report", title="Monthly report", contents=True,
                   sections=[{"heading": "Actions", "body": "- Fix login\n- Call printer"}, {"heading": "Steps", "body": "1. Plan\n2. Do"}])
    assert r.ok
    d = docx.Document(str(next(out(tool_ctx).glob("*.docx"))))
    xml = d.element.xml
    assert "TOC \\o" in xml and "PAGE" in d.sections[0].footer._element.xml
    styles = [(p.style.name, p.text) for p in d.paragraphs]
    assert ("List Bullet", "Fix login") in styles and ("List Number", "Do") in styles


@pytest.mark.skipif(soffice() is None, reason="LibreOffice is not installed here")
async def test_pdf_through_libreoffice(tool_ctx):
    r = await call(tool_ctx, "make_presentation", title="Short deck", slides=SLIDES[:1], pdf=True)
    assert r.verified and "Also saved Short deck.pdf (2 pages)" in r.summary
    r = await call(tool_ctx, "export_pdf", path=str(out(tool_ctx) / "Short deck.pptx"))
    assert r.verified and r.data["pages"] == 2
