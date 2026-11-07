"""Changing the same thing in many files, and joining Word documents.

A find-and-replace across a folder is the easiest way there is to destroy an
afternoon's work, so the shape of the tool matters as much as the matching:
corrected COPIES in a new folder, originals untouched, and a refusal when the
text is not there rather than a copied folder reported as done.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from claw.tools.base import ToolError
from tests.test_phase_a import call


def folder(ctx, name="Quotes"):
    d = Path(ctx.settings.permissions.authorized_folders[0]) / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def digests(d: Path) -> dict:
    return {str(p.relative_to(d)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in d.rglob("*") if p.is_file()}


def docx_with(path: Path, lines: list[str]) -> None:
    import docx
    doc = docx.Document()
    for line in lines:
        doc.add_paragraph(line)
    doc.save(str(path))


# ---------- replacing across a folder ----------
async def test_the_old_number_is_changed_everywhere(tool_ctx):
    d = folder(tool_ctx)
    (d / "quote 1.txt").write_text("Call us on 0803 111 2233 for details.\n", encoding="utf-8")
    (d / "quote 2.txt").write_text("0803 111 2233 is our line. Ask for Ade.\n", encoding="utf-8")
    (d / "notes.md").write_text("No phone number here.\n", encoding="utf-8")
    before = digests(d)

    r = await call(tool_ctx, "replace_in_files", folder="Quotes",
                   find="0803 111 2233", replace_with="0701 444 5566")
    assert r.ok and r.verified
    assert r.data["files"] == 2 and r.data["changes"] == 2

    out = Path(r.data["folder"])
    assert "0701 444 5566" in (out / "quote 1.txt").read_text()
    assert "0803 111 2233" not in (out / "quote 2.txt").read_text()
    # The file that did not contain it is not copied: the folder holds the
    # files that changed, which is what you want to look through.
    assert not (out / "notes.md").exists()
    assert digests(d) == before, "the originals were modified"


async def test_text_that_is_not_there_is_refused(tool_ctx):
    """Copying the folder and reporting success would be the worst outcome:
    the person believes the change was made."""
    d = folder(tool_ctx)
    (d / "a.txt").write_text("nothing relevant here\n", encoding="utf-8")
    with pytest.raises(ToolError, match="does not appear"):
        await call(tool_ctx, "replace_in_files", folder="Quotes",
                   find="0803 111 2233", replace_with="0701 444 5566")
    assert not list(d.parent.glob("Quotes corrected*")), "it wrote a folder anyway"


async def test_a_preview_changes_nothing(tool_ctx):
    d = folder(tool_ctx)
    (d / "a.txt").write_text("Ade Stationary sells books. Ade Stationary is open.\n",
                             encoding="utf-8")
    before = digests(d)
    r = await call(tool_ctx, "replace_in_files", folder="Quotes", find="Stationary",
                   replace_with="Stationery", preview=True)
    assert r.ok and r.data["occurrences"] == 2
    assert "preview" in r.summary
    assert digests(d) == before
    assert not list(d.parent.glob("Quotes corrected*"))


async def test_case_and_whole_words_are_respected(tool_ctx):
    d = folder(tool_ctx)
    (d / "a.txt").write_text("cat CAT catalogue\n", encoding="utf-8")

    plain = await call(tool_ctx, "replace_in_files", folder="Quotes", find="cat",
                       replace_with="dog", preview=True)
    assert plain.data["occurrences"] == 2          # "cat" and the one inside "catalogue"

    word = await call(tool_ctx, "replace_in_files", folder="Quotes", find="cat",
                      replace_with="dog", whole_word=True, preview=True)
    assert word.data["occurrences"] == 1           # not "catalogue"

    any_case = await call(tool_ctx, "replace_in_files", folder="Quotes", find="cat",
                          replace_with="dog", whole_word=True, ignore_case=True, preview=True)
    assert any_case.data["occurrences"] == 2       # "cat" and "CAT"


async def test_a_word_document_is_rewritten_too(tool_ctx):
    import docx
    d = folder(tool_ctx)
    docx_with(d / "terms.docx", ["Ade Stationary Ltd", "Payment to Ade Stationary within 30 days."])
    before = digests(d)

    r = await call(tool_ctx, "replace_in_files", folder="Quotes",
                   find="Stationary", replace_with="Stationery")
    assert r.ok and r.verified and r.data["changes"] == 2
    body = "\n".join(p.text for p in
                     docx.Document(str(Path(r.data["folder"]) / "terms.docx")).paragraphs)
    assert "Ade Stationery Ltd" in body and "Stationary" not in body
    assert digests(d) == before


async def test_a_phrase_word_split_across_runs_is_still_replaced(tool_ctx):
    """Word stores an edited line as several runs; matching run by run misses it."""
    import docx
    d = folder(tool_ctx)
    doc = docx.Document()
    p = doc.add_paragraph()
    for piece in ("Call ", "08", "03 111 ", "2233", " today"):
        p.add_run(piece)
    doc.save(str(d / "split.docx"))

    runs = [r.text for par in docx.Document(str(d / "split.docx")).paragraphs for r in par.runs]
    assert "0803 111 2233" not in runs, "the fixture is not split"

    r = await call(tool_ctx, "replace_in_files", folder="Quotes",
                   find="0803 111 2233", replace_with="0701 444 5566")
    body = "\n".join(x.text for x in
                     docx.Document(str(Path(r.data["folder"]) / "split.docx")).paragraphs)
    assert "0701 444 5566" in body, f"split phrase not replaced: {body!r}"


async def test_binary_files_are_left_well_alone(tool_ctx):
    d = folder(tool_ctx)
    (d / "a.txt").write_text("replace me\n", encoding="utf-8")
    (d / "photo.jpg").write_bytes(b"\xff\xd8 replace me \xff\xd9")
    r = await call(tool_ctx, "replace_in_files", folder="Quotes",
                   find="replace me", replace_with="done")
    assert r.data["files"] == 1
    assert not (Path(r.data["folder"]) / "photo.jpg").exists()


# ---------- joining Word documents ----------
async def test_three_documents_become_one(tool_ctx):
    import docx
    d = folder(tool_ctx, "Report")
    docx_with(d / "1 intro.docx", ["Introduction", "This is the opening."])
    docx_with(d / "2 body.docx", ["The middle part", "With detail."])
    docx_with(d / "3 close.docx", ["Conclusion", "And that is the end."])
    before = digests(d)

    r = await call(tool_ctx, "merge_documents", folder="Report", file_name="full report")
    assert r.ok and r.verified
    body = "\n".join(p.text for p in docx.Document(r.data["path"]).paragraphs)
    for line in ("Introduction", "The middle part", "And that is the end."):
        assert line in body, f"{line!r} missing from the joined document"
    # In order, not just present.
    assert body.index("Introduction") < body.index("The middle part") < body.index("And that is the end.")
    # Only the three originals: the joined file is written beside them, and
    # comparing the whole folder would count that as a change.
    after = digests(d)
    assert {k: after[k] for k in before} == before, "an original was modified"


async def test_joining_one_document_is_refused(tool_ctx):
    d = folder(tool_ctx, "Solo")
    docx_with(d / "only.docx", ["Just the one"])
    with pytest.raises(ToolError, match="at least two"):
        await call(tool_ctx, "merge_documents", folder="Solo")


async def test_a_non_word_file_is_refused(tool_ctx):
    d = folder(tool_ctx, "Mixed")
    docx_with(d / "a.docx", ["One"])
    (d / "b.txt").write_text("two", encoding="utf-8")
    with pytest.raises(ToolError, match="not a Word"):
        await call(tool_ctx, "merge_documents", folder="Mixed", files=["a.docx", "b.txt"])
