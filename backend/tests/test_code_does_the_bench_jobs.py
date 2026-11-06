"""Can run_script actually do the v1.8 jobs? Scored by the bench's own checks.

This measures the TOOL, on this Linux container, with real files on disk - not
the brain, and not Windows. It answers "is the capability really there", which
is a different question from "does the brain reach for it"; that one needs a
real-brain run and is not answered here.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import challenge_bench as cb  # noqa: E402
from tests.test_phase_a import call


def scenario(sid):
    return [s for s in cb.scenarios() if s["id"] == sid][0]


def build(ctx, sid):
    folder = Path(ctx.settings.permissions.authorized_folders[0]) / cb.BENCH / scenario(sid)["folder"]
    folder.mkdir(parents=True, exist_ok=True)
    scenario(sid)["setup"](folder)
    return folder


def checks(sid, folder, answer=""):
    s = scenario(sid)
    return [(name, bool(fn(folder, folder.parent, answer, {"steps": []}))) for name, fn in s["checks"]]


RENAME = '''
import os, pathlib
d = pathlib.Path(r"{d}")
files = [p for p in d.iterdir() if p.is_file()]
files.sort(key=lambda p: p.stat().st_mtime)
for i, p in enumerate(files, 1):
    p.rename(d / f"Wedding {{i:03d}}{{p.suffix}}")
print("renamed", len(files))
'''

SPLIT = '''
import csv, pathlib
d = pathlib.Path(r"{d}")
rows = list(csv.reader((d / "sales.csv").read_text().splitlines()))
head, body = rows[0], rows[1:]
i = head.index("city")
groups = {{}}
for r in body:
    groups.setdefault(r[i], []).append(r)
for city, rs in groups.items():
    with open(d / f"{{city}}.csv", "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(head); w.writerows(rs)
print("wrote", len(groups), "files")
'''

SUMS = '''
import hashlib, pathlib
d = pathlib.Path(r"{d}")
lines = []
for p in sorted(d.iterdir()):
    if p.is_file():
        lines.append(f"{{p.name}}  {{hashlib.sha256(p.read_bytes()).hexdigest()}}")
(d / "checksums.txt").write_text("\\n".join(lines) + "\\n")
print("\\n".join(lines))
'''

TALLY = '''
import collections, pathlib, re
d = pathlib.Path(r"{d}")
stop = {{"the","and","a","to","of","is","was","we","it","from","again","not","needs","then"}}
c = collections.Counter()
for p in d.glob("*.txt"):
    for w in re.findall(r"[a-z]+", p.read_text().lower()):
        if w not in stop and len(w) > 2:
            c[w] += 1
print(c.most_common(5))
'''


@pytest.mark.parametrize("sid,code,needs_answer", [
    ("code-rename-sequence", RENAME, False),
    ("code-split-csv", SPLIT, False),
    ("code-checksum-manifest", SUMS, False),
    ("code-count-words", TALLY, True),
])
async def test_run_script_can_do_the_job(tool_ctx, sid, code, needs_answer):
    folder = build(tool_ctx, sid)
    r = await call(tool_ctx, "run_script", language="python",
                   purpose=sid.replace("-", " "), code=code.format(d=str(folder)))
    assert r.ok, f"{sid}: the script did not run: {r.untrusted_text[:400]}"

    results = checks(sid, folder, r.untrusted_text if needs_answer else "")
    failed = [name for name, passed in results if not passed]
    assert not failed, f"{sid} failed its own checks: {failed}\noutput was: {r.untrusted_text[:400]}"
