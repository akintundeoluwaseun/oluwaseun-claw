"""Do the v1.9 scenarios actually pass, when the real tools are run?

The same question as test_code_does_the_bench_jobs.py asks of run_script,
asked of the tools added since: can the app really open the supplier's zip,
join the month's invoices, shrink a folder of photographs, make a QR code
that scans, write a letter per customer and cut a clip?

This measures the TOOLS on this Linux container. It is not a Windows pass and
not a real-brain pass: whether the brain picks these tools is a separate
question, which tests/test_tool_routing.py covers from the other side.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import challenge_bench as cb  # noqa: E402

from claw.tools.registry import build_registry  # noqa: E402


def scenario(sid):
    return [s for s in cb.scenarios() if s["id"] == sid][0]


def build(ctx, sid):
    s = scenario(sid)
    folder = Path(ctx.settings.permissions.authorized_folders[0]) / cb.BENCH / s["folder"]
    folder.mkdir(parents=True, exist_ok=True)
    s["setup"](folder)
    return folder


def score(sid, folder, answer=""):
    s = scenario(sid)
    return [(name, bool(fn(folder, folder.parent, answer, {"steps": []})))
            for name, fn in s["checks"]]


async def run(ctx, name, **kw):
    spec = build_registry().get(name)
    return await spec.handler(spec.args_model(**kw), ctx)


def assert_passes(sid, folder, answer=""):
    results = score(sid, folder, answer)
    failed = [n for n, ok in results if not ok]
    assert not failed, f"{sid} failed its own checks: {failed}"


async def test_opening_the_suppliers_zip(tool_ctx):
    f = build(tool_ctx, "files-open-zip")
    look = await run(tool_ctx, "look_inside_archive", path=str(f / "from the supplier.zip"))
    r = await run(tool_ctx, "open_archive", path=str(f / "from the supplier.zip"))
    assert r.ok and r.verified
    assert_passes("files-open-zip", f, look.summary)


async def test_joining_the_months_invoices(tool_ctx):
    f = build(tool_ctx, "docs-join-pdfs")
    r = await run(tool_ctx, "combine_pdfs", folder=str(f),
                  files=["invoice 1.pdf", "invoice 2.pdf", "invoice 3.pdf"],
                  file_name="all invoices")
    assert r.ok and r.verified and r.data["pages"] == 3
    assert_passes("docs-join-pdfs", f, r.summary)


async def test_shrinking_the_shop_photos(tool_ctx):
    f = build(tool_ctx, "design-shrink-photos")
    r = await run(tool_ctx, "resize_photos", folder=str(f), size="whatsapp")
    assert r.ok and r.verified and r.data["count"] == 4
    assert r.data["bytes_after"] < r.data["bytes_before"]
    assert_passes("design-shrink-photos", f, r.summary)


async def test_a_qr_code_customers_can_scan(tool_ctx):
    pytest.importorskip("zxingcpp")
    f = build(tool_ctx, "design-qr-code")
    r = await run(tool_ctx, "make_qr_code",
                  content="https://adestationery.ng/catalogue", folder=str(f))
    assert r.ok and r.verified, "the code did not read back as what was asked for"
    assert_passes("design-qr-code", f, r.summary)


async def test_a_reminder_for_every_customer(tool_ctx):
    f = build(tool_ctx, "docs-mail-merge")
    r = await run(tool_ctx, "mail_merge", template=str(f / "reminder.txt"),
                  table=str(f / "customers.csv"))
    assert r.ok and r.verified and r.data["count"] == 3
    assert_passes("docs-mail-merge", f, r.summary)


async def test_cutting_the_first_three_seconds(tool_ctx):
    f = build(tool_ctx, "media-trim-clip")
    r = await run(tool_ctx, "trim_video", path=str(f / "advert.mp4"), start="0", end="3")
    assert r.ok
    assert_passes("media-trim-clip", f, r.summary)
