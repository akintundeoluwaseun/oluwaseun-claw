"""The challenge benchmark's own checks: each passes for a correct result and fails for a wrong one.
(The benchmark itself runs on Windows with a real brain; this only proves the ruler is straight.)"""

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import challenge_bench as cb  # noqa: E402


def by_id():
    return {s["id"]: s for s in cb.scenarios()}


def run_checks(s, folder, docs, answer, result=None):
    return [bool(fn(folder, docs, answer, result or {"steps": []})) for _, fn in s["checks"]]


def fresh(tmp_path, s):
    f = tmp_path / cb.BENCH / s["folder"]
    f.mkdir(parents=True)
    s["setup"](f)
    return f


def test_the_handmade_pdf_reads_back():
    from pypdf import PdfReader
    import io
    text = PdfReader(io.BytesIO(cb.tiny_pdf(["INVOICE INV-001", "Total due: 45,000 (paid)"]))).pages[0].extract_text()
    assert "INV-001" in text and "45,000 (paid)" in text


def test_answer_checks_tell_right_from_wrong(tmp_path):
    S = by_id()
    f = fresh(tmp_path, S["files-duplicates"])
    assert all(run_checks(S["files-duplicates"], f, tmp_path, "IMG_0041.jpg and beach copy.jpg are the same; family.png and family (final).png too."))
    assert not all(run_checks(S["files-duplicates"], f, tmp_path, "No duplicates found."))
    assert all(run_checks(S["data-total"], f, tmp_path, "The total is ₦48,500."))
    assert not all(run_checks(S["data-total"], f, tmp_path, "The total is 47,000."))
    assert all(run_checks(S["stress-missing-info"], f, tmp_path, "Which client, and what is their email address?"))
    assert not all(run_checks(S["stress-missing-info"], f, tmp_path, "The invoice has been sent to your client."))
    assert all(run_checks(S["stress-contradiction"], f, tmp_path, "No: 200,000 + 50,000 = 250,000, not 300,000."))
    assert not all(run_checks(S["stress-contradiction"], f, tmp_path, "Yes, the total of 300,000 is right."))


def test_file_checks_tell_right_from_wrong(tmp_path):
    S = by_id()
    s = S["files-organize"]
    f = fresh(tmp_path, s)
    assert not all(run_checks(s, f, tmp_path, ""))
    for sub, names in (("Documents", ("invoice 12.pdf", "cv.docx", "receipt.pdf")), ("Images", ("photo1.jpg", "screenshot.png")),
                       ("Spreadsheets", ("prices.xlsx", "stock.csv"))):
        (f / sub).mkdir()
        for n in names:
            shutil.move(f / n, f / sub / n)
    assert all(run_checks(s, f, tmp_path, ""))

    s = S["data-dedupe"]
    f = fresh(tmp_path, s)
    (f / "customers clean.csv").write_text("name,phone,email\nAdaeze Okafor,1,a\nTunde Bello,2,t\nKemi Adeyemi,3,k\n")
    assert all(run_checks(s, f, tmp_path, ""))
    (f / "customers clean.csv").write_text("name\nA\nB\nC\nD\n")
    assert not all(run_checks(s, f, tmp_path, ""))

    s = S["data-combine-csv"]
    f = fresh(tmp_path, s)
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["branch", "date", "product", "amount"])
    for row in (["Lagos", "2026-01-03", "Rice", 12000], ["Lagos", "2026-01-05", "Beans", 8000], ["Abuja", "2026-01-04", "Rice", 15000],
                ["Abuja", "2026-01-09", "Garri", 4000], ["Abuja", "2026-01-11", "Beans", 6000], ["Ibadan", "2026-01-02", "Garri", 3500]):
        ws.append(row)
    wb.save(f / "all branches.xlsx")
    assert all(run_checks(s, f, tmp_path, ""))


def test_score_flags_a_false_completion():
    r = {"steps": [{"tool": "x", "outcome": "verified"}], "seconds": 30}
    good = cb.score(3, 3, "completed", r)
    bad = cb.score(1, 3, "completed", r)
    assert good["verdict"] == "PASS" and good["score"] == 100 and not good["false_completion"]
    assert bad["false_completion"] and bad["parts"]["honesty"] == 0 and bad["verdict"] == "PARTIAL"
    honest_fail = cb.score(0, 2, "failed", {"steps": [], "seconds": 10})
    assert honest_fail["verdict"] == "FAIL" and honest_fail["parts"]["honesty"] == 20


def test_baseline_set_is_frozen_at_sixteen():
    ids = [s["id"] for s in cb.scenarios() if s["set"] == cb.BASELINE_SET]
    assert len(ids) == 16 and ids[0] == "files-duplicates" and ids[-1] == "creative-flyer"


def test_infeasible_tasks_pass_only_when_s_claw_says_so(tmp_path):
    S = by_id()
    s = S["infeasible-missing-file"]
    f = fresh(tmp_path, s)
    assert all(run_checks(s, f, tmp_path, "I could not find 'Q3 forecast.xlsx' in the Forecasts folder; only Q2 is there."))
    assert not all(run_checks(s, f, tmp_path, "The Q3 total is 1,250,000."))


def test_input_hashes_spot_a_changed_file(tmp_path):
    (tmp_path / "a.txt").write_text("one")
    before = cb._hashes(tmp_path)
    (tmp_path / "a.txt").write_text("two")
    assert cb._hashes(tmp_path)["a.txt"] != before["a.txt"]


def test_web_scenario_serves_its_pages(tmp_path):
    import urllib.request
    s = by_id()["web-compare"]
    f = fresh(tmp_path, s)
    srv, base = cb._serve(f)
    try:
        assert "FixIt Laptops" in urllib.request.urlopen(f"{base}/fixit.html", timeout=5).read().decode()
    finally:
        srv.shutdown()


# --- v1.8: the program-writing scenarios ------------------------------------
#
# Same job as the checks above: prove the ruler is straight before trusting a
# number it produces. These four scenarios have no tool of their own, so a
# pass genuinely means S-CLAW wrote a program and ran it. That makes a
# too-lenient check expensive: it would report a general capability the app
# does not have, which is the one thing the benchmark exists to prevent.

import hashlib
import os
import time


def _utime(p, day):
    t = time.mktime(time.strptime(day, "%Y-%m-%d"))
    os.utime(p, (t, t))


def test_rename_check_wants_date_order_not_just_tidy_names(tmp_path):
    s = by_id()["files-rename-in-order"]
    f = fresh(tmp_path, s)
    taken = sorted(f.iterdir(), key=lambda q: q.stat().st_mtime)

    # Nothing renamed yet.
    assert not all(run_checks(s, f, tmp_path, ""))

    # Correct: numbered in the order the photos were taken.
    for i, q in enumerate(taken, 1):
        q.rename(f / f"Wedding {i:03d}{q.suffix}")
    assert all(run_checks(s, f, tmp_path, "Renamed 7 photos.")), "a correct rename was marked wrong"


def test_rename_check_rejects_alphabetical_order(tmp_path):
    """The trap: renaming by name is tidy, looks right, and is wrong."""
    s = by_id()["files-rename-in-order"]
    f = fresh(tmp_path, s)
    for i, q in enumerate(sorted(f.iterdir(), key=lambda x: x.name.lower()), 1):
        q.rename(f / f"Wedding {i:03d}{q.suffix}")
    assert not all(run_checks(s, f, tmp_path, "Renamed 7 photos.")), \
        "photos renamed in the wrong order passed"


def test_rename_check_rejects_unpadded_numbers(tmp_path):
    s = by_id()["files-rename-in-order"]
    f = fresh(tmp_path, s)
    for i, q in enumerate(sorted(f.iterdir(), key=lambda q: q.stat().st_mtime), 1):
        q.rename(f / f"Wedding {i}{q.suffix}")   # 1, not 001
    assert not all(run_checks(s, f, tmp_path, "Renamed 7 photos."))


def _split_correctly(f, header=True, mixed=False):
    import csv as _csv
    rows = list(_csv.reader((f / "sales.csv").read_text().splitlines()))
    head, body = rows[0], rows[1:]
    city = head.index("city")
    groups = {}
    for r in body:
        groups.setdefault(r[city], []).append(r)
    names = list(groups)
    for name, rs in groups.items():
        if mixed and name == names[0]:
            rs = rs + groups[names[1]][:1]      # one file holding two cities
        out = ([head] if header else []) + rs
        (f / f"{name}.csv").write_text("\n".join(",".join(r) for r in out) + "\n")


def test_split_check_passes_a_correct_split(tmp_path):
    s = by_id()["code-split-csv"]
    f = fresh(tmp_path, s)
    assert not all(run_checks(s, f, tmp_path, "")), "unsplit folder passed"
    _split_correctly(f)
    assert all(run_checks(s, f, tmp_path, "Split into 4 files.")), "a correct split was marked wrong"


def test_split_check_rejects_a_missing_header(tmp_path):
    s = by_id()["code-split-csv"]
    f = fresh(tmp_path, s)
    _split_correctly(f, header=False)
    assert not all(run_checks(s, f, tmp_path, "Split into 4 files."))


def test_split_check_rejects_a_file_that_mixes_cities(tmp_path):
    s = by_id()["code-split-csv"]
    f = fresh(tmp_path, s)
    _split_correctly(f, mixed=True)
    assert not all(run_checks(s, f, tmp_path, "Split into 4 files."))


def test_checksum_check_wants_the_real_hashes(tmp_path):
    s = by_id()["code-checksum-manifest"]
    f = fresh(tmp_path, s)
    assert not all(run_checks(s, f, tmp_path, "")), "no manifest passed"

    names = ["contract.pdf", "logo.png", "notes.txt"]
    real = {n: hashlib.sha256((f / n).read_bytes()).hexdigest() for n in names}
    (f / "checksums.txt").write_text("\n".join(f"{n}  {real[n]}" for n in names) + "\n")
    assert all(run_checks(s, f, tmp_path, "Saved checksums.txt.")), \
        "a correct manifest was marked wrong"


def test_checksum_check_rejects_invented_hashes(tmp_path):
    """The failure this is really guarding: a brain that writes plausible hex."""
    s = by_id()["code-checksum-manifest"]
    f = fresh(tmp_path, s)
    names = ["contract.pdf", "logo.png", "notes.txt"]
    (f / "checksums.txt").write_text(
        "\n".join(f"{n}  {hashlib.sha256(n.encode()).hexdigest()}" for n in names) + "\n")
    assert not all(run_checks(s, f, tmp_path, "Saved checksums.txt.")), \
        "made-up checksums passed"


def test_checksum_check_rejects_a_partial_manifest(tmp_path):
    s = by_id()["code-checksum-manifest"]
    f = fresh(tmp_path, s)
    q = f / "contract.pdf"
    (f / "checksums.txt").write_text(f"contract.pdf  {hashlib.sha256(q.read_bytes()).hexdigest()}\n")
    assert not all(run_checks(s, f, tmp_path, "Saved checksums.txt."))


def test_word_tally_check_tells_a_real_theme_from_a_stop_word(tmp_path):
    s = by_id()["code-count-words"]
    f = fresh(tmp_path, s)
    assert all(run_checks(s, f, tmp_path,
                          "The most common words are 'generator' (4) and 'power' (4)."))
    assert not all(run_checks(s, f, tmp_path, "The most common word is 'shift'."))
    assert not all(run_checks(s, f, tmp_path,
                              "Most common: 'the' appears 9 times, then generator and power."))


# --- v1.9: the everyday jobs ------------------------------------------------
#
# Same discipline as above: a check that only ever says yes measures nothing.
# Each of these is shown rejecting the wrong answer as well as accepting the
# right one, and the wrong answers are the plausible ones - the folder left
# unpacked, three separate PDFs instead of one, the originals overwritten
# instead of copied, a letter still saying {Name}.

async def _run(ctx, name, **kw):
    from claw.tools.registry import build_registry
    spec = build_registry().get(name)
    return await spec.handler(spec.args_model(**kw), ctx)


def test_zip_check_wants_the_files_out(tmp_path):
    s = by_id()["files-open-zip"]
    f = fresh(tmp_path, s)
    assert not all(run_checks(s, f, tmp_path, "There is a price list and some photos."))
    import zipfile
    with zipfile.ZipFile(f / "from the supplier.zip") as z:
        z.extractall(f / "out")
    assert all(run_checks(s, f, tmp_path, "A price list, a photo and the terms."))


def test_join_pdfs_check_rejects_three_separate_files(tmp_path):
    """Copying the invoices somewhere is not joining them."""
    from pypdf import PdfReader, PdfWriter
    s = by_id()["docs-join-pdfs"]
    f = fresh(tmp_path, s)
    assert not all(run_checks(s, f, tmp_path, "Done."))

    # A wrong answer: one PDF per invoice, renamed.
    for n in (1, 2, 3):
        w = PdfWriter()
        w.append(PdfReader(str(f / f"invoice {n}.pdf")))
        with open(f / f"combined {n}.pdf", "wb") as fh:
            w.write(fh)
    assert not all(run_checks(s, f, tmp_path, "Done.")), "three files passed as one"

    w = PdfWriter()
    for n in (1, 2, 3):
        w.append(PdfReader(str(f / f"invoice {n}.pdf")))
    with open(f / "all invoices.pdf", "wb") as fh:
        w.write(fh)
    assert all(run_checks(s, f, tmp_path, "Joined into one PDF."))


def test_photo_check_rejects_overwriting_the_originals(tmp_path):
    """Shrinking in place destroys the only copy. It must not count as done."""
    from PIL import Image
    s = by_id()["design-shrink-photos"]
    f = fresh(tmp_path, s)
    assert not all(run_checks(s, f, tmp_path, "Done."))

    for q in list(f.glob("IMG_*.jpg")):
        with Image.open(q) as im:
            im.resize((1600, 1200)).save(q, "JPEG", quality=82)
    assert not all(run_checks(s, f, tmp_path, "Done.")), "overwriting the originals passed"


def test_mail_merge_check_rejects_a_letter_still_holding_a_placeholder(tmp_path):
    s = by_id()["docs-mail-merge"]
    f = fresh(tmp_path, s)
    out = f / "letters"
    out.mkdir()
    # The failure that reaches the customer.
    for name in ("Ade Stores", "Bola Ventures", "Chidi Ltd"):
        (out / f"{name}.txt").write_text(
            "Dear {Name},\n\nYour balance of {Amount} is due on {Due date}.\n", encoding="utf-8")
    assert not all(run_checks(s, f, tmp_path, "Done.")), "unfilled letters passed"

    for name, amount, due in (("Ade Stores", "N15,000", "5 January"),
                              ("Bola Ventures", "N7,500", "9 January"),
                              ("Chidi Ltd", "N45,500", "11 January")):
        (out / f"{name}.txt").write_text(
            f"Dear {name},\n\nYour balance of {amount} is due on {due}.\n", encoding="utf-8")
    assert all(run_checks(s, f, tmp_path, "Made three letters."))


def test_qr_check_needs_a_code_that_really_scans(tmp_path):
    """A PNG in the folder is not a QR code."""
    import pytest as _pytest
    try:
        import zxingcpp  # noqa: F401
    except Exception:  # noqa: BLE001
        _pytest.skip("no QR reader installed")
    import segno
    from PIL import Image

    s = by_id()["design-qr-code"]
    f = fresh(tmp_path, s)
    Image.new("RGB", (400, 400), (255, 255, 255)).save(f / "not a qr.png")
    assert not all(run_checks(s, f, tmp_path, "Made it.")), "a blank picture passed as a QR code"

    segno.make("https://example.com/wrong", error="h").save(str(f / "wrong.png"), scale=8, border=4)
    assert not all(run_checks(s, f, tmp_path, "Made it.")), "a code for the wrong address passed"

    segno.make("https://adestationery.ng/catalogue", error="h").save(
        str(f / "catalogue.png"), scale=8, border=4)
    assert all(run_checks(s, f, tmp_path, "Made it."))
