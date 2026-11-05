"""Challenge 9.06: documents from several websites, gathered and organised.

The thing worth testing is not that files arrive. It is what happens to the
ones that do not. A link ending .pdf that answers 200 with an HTML "that report
has moved" page is the ordinary case on a real site, and a collector that
believes the address will save that page as annual-report.pdf and report it
among the documents it collected. That is a false completion the person only
discovers when they open the folder.

So these check the refusals as hard as the successes: the error page is not
saved, the installer is never fetched, the same document linked from two pages
is downloaded once, and the summary names what failed and why.

Real Chromium against the local fixture site; no internet.
"""

from pathlib import Path

import pytest

from claw.tools.research_tools import DOCUMENT_KINDS, _looks_like
from tests.test_phase_a import call


# ---------- the check that does the work ----------
def test_bytes_must_be_what_the_extension_promised():
    assert _looks_like(b"%PDF-1.7\nstuff", ".pdf") == ""
    assert _looks_like(b"PK\x03\x04junk", ".docx") == ""
    assert "web page" in _looks_like(b"<!doctype html><html><body>gone", ".pdf")
    assert "web page" in _looks_like(b"  \n<HTML><body>gone</body>", ".pdf")
    assert "not PDF" in _looks_like(b"just some text", ".pdf")
    assert _looks_like(b"", ".pdf") == "the file was empty"


def test_a_kind_we_cannot_identify_is_still_refused_an_error_page():
    # .csv has no magic bytes, so anything goes - except a web page.
    assert _looks_like(b"item,price\nCharger,3500\n", ".csv") == ""
    assert "web page" in _looks_like(b"<!doctype html><title>404</title>", ".csv")


def test_every_collectable_kind_declares_what_it_starts_with_or_says_it_cannot():
    for ext, magic in DOCUMENT_KINDS.items():
        assert ext.startswith(".") and ext == ext.lower()
        assert magic is None or (isinstance(magic, tuple) and all(isinstance(m, bytes) for m in magic))


# ---------- the whole tool, against a real browser ----------
async def test_documents_are_collected_sorted_and_the_dead_link_is_reported(tool_ctx, site):
    r = await call(tool_ctx, "collect_documents",
                   urls=[f"{site.base_url}/library", f"{site.base_url}/library/second"],
                   sort_into="kind")
    root = Path(tool_ctx.settings.permissions.authorized_folders[0])

    # four real documents: a PDF, a CSV, a DOCX and an XLSX
    kinds = sorted(s["kind"] for s in r.data["saved"])
    assert kinds == ["csv", "docx", "pdf", "xlsx"], f"collected {kinds}"
    assert r.ok and r.verified

    # sorted into subfolders by type, and the bytes on disk are the real thing
    assert (root / "PDF" / "annual-report.pdf").read_bytes().startswith(b"%PDF")
    assert (root / "DOCX" / "staff-handbook.docx").read_bytes().startswith(b"PK\x03\x04")
    assert (root / "XLSX" / "budget-2026.xlsx").is_file()
    assert (root / "CSV" / "price-list.csv").read_text().startswith("item,price")

    # the dead .pdf was NOT saved, and the person is told why
    assert not list(root.rglob("moved-report*")), "an HTML error page was saved as a PDF"
    why = [f["why"] for f in r.data["failed"] if "moved-report" in f.get("url", "")]
    assert why and "web page" in why[0], r.data["failed"]
    assert "moved-report.pdf" in r.summary and "did not come through" in r.summary

    # the installer was never even requested
    assert not list(root.rglob("*.exe")) and not any("setup.exe" in f.get("url", "") for f in r.data["failed"])

    # linked from both pages, downloaded once
    assert sum(1 for s in r.data["saved"] if s["kind"] == "pdf") == 1

    # every file carries the page it was found on, which is what makes it citable
    pages = {s["page"] for s in r.data["saved"]}
    assert pages <= {f"{site.base_url}/library", f"{site.base_url}/library/second"}
    assert all(s["verified"] and s["bytes"] > 0 for s in r.data["saved"])


async def test_only_the_asked_for_kinds_are_taken(tool_ctx, site):
    r = await call(tool_ctx, "collect_documents", urls=[f"{site.base_url}/library"], kinds="pdf")
    assert [s["kind"] for s in r.data["saved"]] == ["pdf"]
    root = Path(tool_ctx.settings.permissions.authorized_folders[0])
    assert not list(root.rglob("*.csv")) and not list(root.rglob("*.docx"))


async def test_sorting_by_site_puts_each_site_in_its_own_folder(tool_ctx, site):
    r = await call(tool_ctx, "collect_documents", urls=[f"{site.base_url}/library"],
                   kinds=["pdf", "csv"], sort_into="site")
    root = Path(tool_ctx.settings.permissions.authorized_folders[0])
    host = [p for p in root.iterdir() if p.is_dir()]
    assert len(host) == 1 and "127.0.0.1" in host[0].name, [p.name for p in host]
    assert len(list(host[0].glob("*"))) == 2 and r.ok


async def test_no_subfolders_when_not_asked_for(tool_ctx, site):
    await call(tool_ctx, "collect_documents", urls=[f"{site.base_url}/library"],
               kinds="pdf", sort_into="none")
    root = Path(tool_ctx.settings.permissions.authorized_folders[0])
    assert (root / "annual-report.pdf").is_file()


async def test_a_page_with_no_documents_says_so_rather_than_claiming_success(tool_ctx, site):
    r = await call(tool_ctx, "collect_documents", urls=[f"{site.base_url}/articles/cooking"])
    assert not r.ok and r.data["saved"] == [] and "No" in r.summary
    assert "Nothing was downloaded" in r.summary


async def test_one_unreachable_page_does_not_lose_the_others(tool_ctx, site):
    r = await call(tool_ctx, "collect_documents",
                   urls=[f"{site.base_url}/library", f"{site.base_url}/does-not-exist"],
                   kinds="pdf")
    assert [s["kind"] for s in r.data["saved"]] == ["pdf"], "a 404 page stopped the run"


async def test_a_kind_claw_does_not_collect_is_refused_by_name(tool_ctx, site):
    with pytest.raises(Exception) as exc:
        await call(tool_ctx, "collect_documents", urls=[f"{site.base_url}/library"], kinds="exe")
    assert "exe" in str(exc.value)


async def test_the_limit_is_honoured(tool_ctx, site):
    r = await call(tool_ctx, "collect_documents", urls=[f"{site.base_url}/library"], limit=1)
    assert len(r.data["saved"]) == 1


async def test_nothing_is_written_outside_an_authorized_folder(tool_ctx, site):
    r = await call(tool_ctx, "collect_documents", urls=[f"{site.base_url}/library"], kinds="pdf")
    allowed = Path(tool_ctx.settings.permissions.authorized_folders[0]).resolve()
    for s in r.data["saved"]:
        assert Path(s["path"]).resolve().is_relative_to(allowed)
