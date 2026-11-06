"""One letter, fifty customers.

The manual version is open-change-save-repeat, which is exactly the work a
computer should take off somebody.

These tests are mostly about the two ways a mail merge produces output that
looks finished and is not: a letter that goes out saying "Dear {Name}", and a
placeholder Word has quietly split into several runs so a naive replacement
misses it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claw.tools.base import ToolError
from claw.tools.merge_tools import placeholders_in
from tests.test_phase_a import call


def folder(ctx, name="Letters"):
    d = Path(ctx.settings.permissions.authorized_folders[0]) / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def customers(d: Path, name="customers.csv") -> Path:
    p = d / name
    p.write_text("Name,Amount,Due date\n"
                 "Ade Stores,\"N15,000\",5 January\n"
                 "Bola Ventures,\"N7,500\",9 January\n"
                 "Chidi Ltd,\"N45,500\",11 January\n", encoding="utf-8")
    return p


def docx_template(path: Path, paragraphs: list[str]) -> None:
    import docx
    doc = docx.Document()
    for text in paragraphs:
        doc.add_paragraph(text)
    doc.save(str(path))


def split_placeholder_docx(path: Path) -> None:
    """A template where {Name} is stored as several runs, as Word really does.

    Typing the line and then correcting a letter in the middle leaves Word
    holding "{Na", "m", "e}" as separate runs. A template typed in one go
    does not reproduce this, which is why it is built by hand here.
    """
    import docx
    doc = docx.Document()
    p = doc.add_paragraph()
    for piece in ("Dear ", "{Na", "m", "e},", " your balance is ", "{Amo", "unt}", "."):
        p.add_run(piece)
    doc.save(str(path))


# ---------- finding the placeholders ----------
def test_placeholders_are_picked_out_of_the_text():
    assert placeholders_in("Dear {Name}, you owe {Amount} by {Due date}.") == [
        "Name", "Amount", "Due date"]
    assert placeholders_in("{Name} and {name} again") == ["Name"]      # same column
    assert placeholders_in("no placeholders here") == []
    # A stray brace must not swallow the rest of the letter.
    assert placeholders_in("the total { is\nnot a placeholder }") == []


# ---------- text templates ----------
async def test_a_letter_per_row(tool_ctx):
    d = folder(tool_ctx)
    customers(d)
    (d / "reminder.txt").write_text(
        "Dear {Name},\n\nYour balance of {Amount} is due on {Due date}.\n\nAde Stationery\n",
        encoding="utf-8")

    r = await call(tool_ctx, "mail_merge", template="reminder.txt",
                   table="customers.csv", folder="Letters")
    assert r.ok and r.verified and r.data["count"] == 3

    out = Path(r.data["folder"])
    names = sorted(p.name for p in out.iterdir())
    assert names == ["Ade Stores.txt", "Bola Ventures.txt", "Chidi Ltd.txt"]

    bola = (out / "Bola Ventures.txt").read_text()
    assert "Dear Bola Ventures," in bola
    assert "N7,500" in bola and "9 January" in bola
    assert "{" not in bola, "a placeholder was left in the letter"
    # And each letter has its OWN details, not the first row's.
    assert "Ade Stores" not in bola and "15,000" not in bola


async def test_files_are_named_from_a_chosen_column(tool_ctx):
    d = folder(tool_ctx)
    customers(d)
    (d / "note.txt").write_text("{Name} owes {Amount}\n", encoding="utf-8")
    r = await call(tool_ctx, "mail_merge", template="note.txt", table="customers.csv",
                   folder="Letters", name_from="Due date")
    names = sorted(p.stem for p in Path(r.data["folder"]).iterdir())
    assert names == ["11 January", "5 January", "9 January"]


async def test_a_missing_column_writes_nothing_at_all(tool_ctx):
    """The important one. Half a merge is found by the customer, not by us."""
    d = folder(tool_ctx)
    customers(d)
    (d / "bad.txt").write_text("Dear {Name}, your account {Account Number} is overdue.\n",
                               encoding="utf-8")
    with pytest.raises(ToolError) as exc:
        await call(tool_ctx, "mail_merge", template="bad.txt", table="customers.csv",
                   folder="Letters")
    assert "Account Number" in str(exc.value)
    assert "Name" in str(exc.value) and "Amount" in str(exc.value), "it should list the columns it has"
    assert not list(d.glob("bad filled in*")), "it wrote letters anyway"


async def test_a_template_with_no_placeholders_says_so(tool_ctx):
    d = folder(tool_ctx)
    customers(d)
    (d / "plain.txt").write_text("Dear customer, please pay your bill.\n", encoding="utf-8")
    with pytest.raises(ToolError, match="no placeholders"):
        await call(tool_ctx, "mail_merge", template="plain.txt", table="customers.csv",
                   folder="Letters")


async def test_only_the_first_few_can_be_done_as_a_check(tool_ctx):
    d = folder(tool_ctx)
    customers(d)
    (d / "r.txt").write_text("Dear {Name}, you owe {Amount}.\n", encoding="utf-8")
    r = await call(tool_ctx, "mail_merge", template="r.txt", table="customers.csv",
                   folder="Letters", limit=1)
    assert r.data["count"] == 1


# ---------- Word templates ----------
async def test_a_word_letter_per_row(tool_ctx):
    import docx
    d = folder(tool_ctx)
    customers(d)
    docx_template(d / "letter.docx",
                  ["Ade Stationery", "Dear {Name},",
                   "Your balance of {Amount} is due on {Due date}.", "Thank you."])

    r = await call(tool_ctx, "mail_merge", template="letter.docx",
                   table="customers.csv", folder="Letters")
    assert r.ok and r.verified and r.data["count"] == 3

    out = Path(r.data["folder"]) / "Chidi Ltd.docx"
    body = "\n".join(p.text for p in docx.Document(str(out)).paragraphs)
    assert "Dear Chidi Ltd," in body and "N45,500" in body and "11 January" in body
    assert "{" not in body


async def test_a_placeholder_word_has_split_up_is_still_filled(tool_ctx):
    """The quiet one: works on a freshly typed template, fails on a real one."""
    import docx
    d = folder(tool_ctx)
    customers(d)
    split_placeholder_docx(d / "split.docx")

    # The placeholder is genuinely split in the fixture.
    runs = [r.text for p in docx.Document(str(d / "split.docx")).paragraphs for r in p.runs]
    assert "{Name}" not in runs, "the fixture is not actually split across runs"

    r = await call(tool_ctx, "mail_merge", template="split.docx",
                   table="customers.csv", folder="Letters")
    assert r.ok and r.verified
    body = "\n".join(p.text for p in
                     docx.Document(str(Path(r.data["folder"]) / "Ade Stores.docx")).paragraphs)
    assert "Dear Ade Stores," in body, f"the split placeholder was not filled: {body!r}"
    assert "N15,000" in body
    assert "{" not in body


async def test_the_original_template_is_not_touched(tool_ctx):
    import hashlib
    d = folder(tool_ctx)
    customers(d)
    docx_template(d / "letter.docx", ["Dear {Name},", "You owe {Amount}."])
    before = hashlib.sha256((d / "letter.docx").read_bytes()).hexdigest()
    await call(tool_ctx, "mail_merge", template="letter.docx", table="customers.csv",
               folder="Letters")
    assert hashlib.sha256((d / "letter.docx").read_bytes()).hexdigest() == before


async def test_two_customers_with_the_same_name_both_get_a_letter(tool_ctx):
    d = folder(tool_ctx)
    (d / "dup.csv").write_text("Name,Amount\nAde Stores,100\nAde Stores,200\n", encoding="utf-8")
    (d / "n.txt").write_text("Dear {Name}, you owe {Amount}.\n", encoding="utf-8")
    r = await call(tool_ctx, "mail_merge", template="n.txt", table="dup.csv", folder="Letters")
    assert r.data["count"] == 2, "one letter overwrote the other"
    bodies = sorted(p.read_text() for p in Path(r.data["folder"]).iterdir())
    assert "100" in bodies[0] and "200" in bodies[1]
