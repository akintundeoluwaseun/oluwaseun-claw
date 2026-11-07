"""Every tracked file must be checkout-able on Windows.

S-CLAW is a Windows application whose installer is built by checking this
repository out on a Windows machine. Linux will happily store a file called
`hat(?:.?s| is) in)|`; Windows cannot create it, so `git checkout` fails with
"invalid path" and the build dies at step two, before a line of code runs.

That is not hypothetical. A mangled sed command wrote exactly that file, it
was committed by a `git add -A`, and every Windows build from the branch
failed at checkout until it was found - the error says nothing about the
commit that introduced it, so it costs a build cycle to track down.

Windows forbids < > : " | ? * in a file name, the control characters, a
trailing space or dot, and a short list of device names.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

FORBIDDEN = set('<>:"|?*') | {chr(c) for c in range(32)}
#: Reserved whatever the extension: CON.txt is refused too.
DEVICES = {"con", "prn", "aux", "nul",
           *(f"com{n}" for n in range(1, 10)), *(f"lpt{n}" for n in range(1, 10))}


def tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True, text=True,
                         check=True).stdout
    return [p for p in out.split("\0") if p]


def why_windows_refuses(path: str) -> str | None:
    for part in Path(path).parts:
        bad = sorted(FORBIDDEN & set(part))
        if bad:
            shown = ", ".join(repr(c) for c in bad)
            return f"the name {part!r} contains {shown}, which Windows does not allow"
        if part != part.rstrip(" ."):
            return f"the name {part!r} ends with a space or a dot"
        if part.split(".")[0].lower() in DEVICES:
            return f"{part!r} is a reserved device name on Windows"
    return None


def test_no_tracked_file_breaks_a_windows_checkout():
    offenders = [(p, why) for p in tracked() if (why := why_windows_refuses(p))]
    assert not offenders, "these files stop `git checkout` on Windows:\n" + "\n".join(
        f"  {p}: {why}" for p, why in offenders)


def test_no_two_files_differ_only_by_capitals():
    """Windows file names are case-insensitive, so both cannot exist at once.

    One of the pair silently overwrites the other at checkout, which is
    harder to spot than a failure: the build succeeds with the wrong file.
    """
    seen: dict[str, str] = {}
    clashes = []
    for p in tracked():
        key = p.lower()
        if key in seen and seen[key] != p:
            clashes.append((seen[key], p))
        seen[key] = p
    assert not clashes, "these differ only in capitals:\n" + "\n".join(
        f"  {a} / {b}" for a, b in clashes)


@pytest.mark.parametrize("name,ok", [
    ("backend/claw/tools/pdf_tools.py", True),
    ("docs/USER GUIDE.md", True),                       # a space is fine
    ("desktop/src/assets/tray-idle@2x.png", True),      # so is @
    ("backend/hat(?:.?s| is) in)|", False),             # the one that happened
    ("a/what?.txt", False),
    ("a/report:final.md", False),
    ("a/trailing .txt", True),                          # space before the dot is fine
    ("a/trailing.", False),
    ("a/CON.txt", False),
    ("a/console.txt", True),
])
def test_the_rule_matches_what_windows_actually_refuses(name, ok):
    assert (why_windows_refuses(name) is None) is ok, f"{name}: {why_windows_refuses(name)}"
