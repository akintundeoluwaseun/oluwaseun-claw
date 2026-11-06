"""Does the brain get SHOWN the tool that fits what was asked?

fitting_tools decides which tools are described in full to the brain. A tool
it never names is, from the brain's side, a tool that does not exist - which
is most of the gap between "the app can do this" and "the app does this".

Sixteen tools were added without touching that list, and the general patterns
actively mis-routed around them: "make my photos smaller" matched
\\b(?:picture|photo|image)\\b and landed on edit_image, which does one file at
a time. These tests are the guard against adding the seventeenth the same way.

The phrasings are the ones a person would actually type, not the tool's own
name - nobody asks for "resize_photos".
"""

from __future__ import annotations

import pytest

from claw.agent.executor import fitting_tools
from claw.tools.registry import build_registry


@pytest.fixture(scope="module")
def registry():
    return build_registry()


ASKED = [
    # Archives
    ("unzip the file the supplier sent me", "open_archive"),
    ("unpack this", "open_archive"),
    ("what is in the archive", "look_inside_archive"),
    ("open the zip from the bank", "open_archive"),
    # Changing a PDF
    ("join these invoices into one pdf", "combine_pdfs"),
    ("combine the three pdfs into one file", "combine_pdfs"),
    ("split this 40 page pdf into separate files", "split_pdf"),
    ("just pages 2 to 5 out of the contract pdf", "extract_pages"),
    ("the scan is sideways, turn the pages the right way up", "rotate_pdf"),
    ("stamp PAID on the invoice", "stamp_pdf"),
    ("this pdf is too big to email", "shrink_pdf"),
    ("compress the pdf", "shrink_pdf"),
    # Folders of photographs
    ("make my photos smaller for whatsapp", "resize_photos"),
    ("resize all the pictures for the website", "resize_photos"),
    ("put my shop name on the product pictures", "watermark_photos"),
    ("watermark the photos", "watermark_photos"),
    ("make a QR code for my catalogue", "make_qr_code"),
    # Video
    ("cut the first 30 seconds of the video", "trim_video"),
    ("get the audio out of this mp4", "extract_audio"),
    ("save the video's sound to mp3", "extract_audio"),
    ("grab a thumbnail from the video", "grab_frame"),
    ("the video is too big to send on whatsapp", "shrink_video"),
    # One document per row
    ("send one reminder letter to each customer", "mail_merge"),
    ("mail merge the certificates", "mail_merge"),

    # --- Tools that existed but nothing pointed at ---------------------------
    # An audit found 62 tools no pattern ever named. Several were worse than
    # unnamed: a general pattern claimed the words and sent the brain
    # elsewhere. These are the ones a person asks for by name.
    ("make an invoice for Ade Stores for 20 exercise books at N500", "make_document"),
    ("write a quotation for Bola Ventures", "make_document"),
    ("prepare a receipt", "make_document"),
    ("write a python script to rename these files", "run_script"),
    ("run ffmpeg on this", "run_command"),
    ("find which files mention the word refund", "search_in_folder"),
    ("make a pivot table of sales by city", "pivot_table"),
    ("total sales by branch", "pivot_table"),
    ("show me anything unusual in the amounts", "find_outliers"),
    ("reconcile the bank statement against my records", "reconcile_tables"),
    ("make a passport photo", "passport_photo"),
    ("this photo is too dark, brighten it", "brighten_photo"),
    ("put these photos into one collage", "make_collage"),
    ("design a bracket 60 by 40 mm", "make_part"),
    ("what is taking up my disk space", "disk_space"),
]


@pytest.mark.parametrize("asked,tool", ASKED)
def test_the_fitting_tool_is_offered(asked, tool, registry):
    found = fitting_tools(asked, registry)
    assert tool in found, f"{asked!r} offered {found} - not {tool}"


@pytest.mark.parametrize("asked,tool", ASKED)
def test_the_fitting_tool_is_near_the_front(asked, tool, registry):
    """Being in the list is not enough: the brain reads the first few.

    The new patterns are placed before the general ones for this reason -
    otherwise 'too big to send on whatsapp' leads with the WhatsApp tools and
    the one that actually shrinks the video comes third.
    """
    found = fitting_tools(asked, registry)
    assert found.index(tool) == 0, f"{asked!r} put {found[0]} ahead of {tool}: {found}"


def test_packing_and_opening_are_told_apart(registry):
    """Both are "zip". Only one of them makes an archive."""
    assert "archive_folder" in fitting_tools("archive the project folder", registry)
    assert "archive_folder" in fitting_tools("zip up my website folder", registry)
    assert "open_archive" not in fitting_tools("archive the project folder", registry)
    assert "open_archive" in fitting_tools("unzip the attachment", registry)


def test_one_picture_and_a_folder_of_pictures_are_told_apart(registry):
    """edit_image does one; resize_photos does the folder."""
    one = fitting_tools("crop this picture", registry)
    many = fitting_tools("make all the photos smaller for whatsapp", registry)
    assert "edit_image" in one
    assert many[0] == "resize_photos", f"a folder job led with {many[0]}"


def test_reading_a_pdf_still_beats_changing_one(registry):
    """The new patterns must not have stolen the ordinary 'read it' case."""
    found = fitting_tools("read the invoice pdf and tell me the total", registry)
    assert "read_document_pages" in found
    assert found[0] in ("read_document_pages", "summarize_document"), found


def test_making_an_invoice_is_not_confused_with_reading_one(registry):
    """The worst of the mis-routes: both say "invoice".

    "Make an invoice" was answered with the tool that reads a PDF, which
    cannot make anything, so the request failed with the capability sitting
    right there.
    """
    making = fitting_tools("make an invoice for Ade Stores", registry)
    reading = fitting_tools("read the invoice pdf and tell me the total", registry)
    assert making[0] == "make_document", making
    assert reading[0] in ("read_document_pages", "summarize_document"), reading


def test_writing_a_program_reaches_the_code_tools(registry):
    """The general capability was unreachable by the words people use."""
    for asked in ("write a python script to tidy these files",
                  "write a little program to work out the totals",
                  "run a command on this computer"):
        found = fitting_tools(asked, registry)
        assert found and found[0] in ("run_script", "run_command"), f"{asked!r} -> {found}"


def test_searching_inside_files_is_not_searching_for_files(registry):
    """find_files looks at names; search_in_folder looks at contents."""
    by_name = fitting_tools("find all the pdf files in Documents", registry)
    by_content = fitting_tools("which files mention the word refund", registry)
    assert "find_files" in by_name
    assert by_content[0] == "search_in_folder", by_content


def test_every_tool_named_in_the_list_exists(registry):
    """A pattern pointing at a renamed tool silently offers nothing."""
    from claw.agent.executor import _FITTING
    have = set(registry.names())
    missing = sorted({n for _, names in _FITTING for n in names} - have)
    assert not missing, f"the fitting list names tools that do not exist: {missing}"
