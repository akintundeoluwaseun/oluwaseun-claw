"""Mistakes in the build scripts that no Python test would otherwise see.

The packaging scripts are PowerShell and only ever run on Windows, so a syntax
error in them survives every test here and fails the build instead - after the
suite has run and the brain has downloaded, seven minutes in.

One did exactly that:

    Write-Host "S-CLAW $Edition: $($built.Count) file(s) ..."

PowerShell reads `$Name:` as a scope or drive qualifier, the way `$env:PATH`
works, so `$Edition:` is not a variable followed by a colon - it is a parse
error, and a parse error kills the whole script before its first statement.

This does not need PowerShell: the mistake is visible in the text.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = sorted((ROOT / "scripts").glob("*.ps1"))
#: The workflows run most of their steps in pwsh, so the same mistake is just as
#: fatal there - and costs more, because it is found mid-build. (I made it twice:
#: once in build-release.ps1, and again in the very step added to catch it.)
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))

#: Qualifiers PowerShell really does define. Anything else before a colon is
#: almost certainly a variable someone meant to interpolate.
KNOWN_QUALIFIERS = {"env", "script", "global", "local", "using", "private", "variable",
                    "function", "alias", "workflow"}

#: `$name:` where the name is not a known qualifier.
SCOPE_LIKE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*):")


def test_there_are_scripts_to_check():
    assert SCRIPTS, "no .ps1 files found; this guard is checking nothing"
    assert WORKFLOWS, "no workflows found; this guard is checking nothing"


def scope_mistakes(text: str, label: str) -> list[str]:
    bad = []
    for number, line in enumerate(text.splitlines(), 1):
        # A URL inside a string is not this mistake, nor is a GitHub expression,
        # which begins "${" and so never matches the pattern anyway.
        hunt = re.sub(r"https?://\S*", "", line)
        for name in SCOPE_LIKE.findall(hunt):
            if name.lower() not in KNOWN_QUALIFIERS:
                bad.append(f"{label}:{number}  ${name}:  ->  use ${{{name}}}:")
    return bad


@pytest.mark.parametrize("path", SCRIPTS + WORKFLOWS, ids=lambda p: p.name)
def test_no_variable_is_followed_by_a_bare_colon(path: Path):
    bad = scope_mistakes(path.read_text(encoding="utf-8"), path.name)
    assert not bad, (
        "PowerShell reads $name: as a scope qualifier, so these are parse errors "
        "that kill the whole script:\n  " + "\n  ".join(bad)
    )
