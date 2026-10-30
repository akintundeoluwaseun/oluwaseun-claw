"""Does every brain in the catalogue actually exist, with the files it claims?

    python backend/packaging/check_catalog.py [extra/repo ...]

A catalogue entry is three guesses in a trench coat: a repository id, a regex
for the model file and a regex for the vision file. Nothing in the test suite
can check them, because the workspace that runs the tests cannot reach
huggingface.co - so a wrong repository or a pattern that matches nothing is
found by a build, forty minutes in, or by a person whose download fails.

This asks the Hugging Face API directly and reports, per entry, whether the
repository resolves and which files the patterns select. Extra repository ids
can be passed as arguments to try candidates that are not in the catalogue yet.

Exit code 1 if any catalogue entry does not resolve.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from claw.runtime import catalog  # noqa: E402

API = "https://huggingface.co/api/models/"


def files_in(repo: str) -> tuple[list[str], str]:
    """Every filename in a repository, or an empty list and why not."""
    try:
        with urllib.request.urlopen(API + repo, timeout=30) as r:
            data = json.load(r)
    except urllib.error.HTTPError as exc:
        return [], f"HTTP {exc.code}"
    except Exception as exc:  # network, DNS, JSON
        return [], f"{type(exc).__name__}: {exc}"
    names = [s.get("rfilename", "") for s in data.get("siblings", [])]
    return [n for n in names if n], ""


def matching(names: list[str], pattern: str | None) -> list[str]:
    if not pattern:
        return []
    rx = re.compile(pattern, re.I)
    return [n for n in names if rx.search(n)]


def main() -> int:
    bad = 0
    for entry in catalog.CATALOG:
        names, why = files_in(entry.repo)
        if not names:
            print(f"FAIL  {entry.id:14} {entry.repo}  -> {why or 'no files listed'}")
            bad += 1
            continue
        model = matching(names, entry.model_pattern)
        mmproj = matching(names, entry.mmproj_pattern)
        ok = len(model) == 1 and (entry.mmproj_pattern is None or len(mmproj) == 1)
        print(f"{'ok  ' if ok else 'FAIL'}  {entry.id:14} {entry.repo}")
        print(f"        model  /{entry.model_pattern}/ -> {model or 'NOTHING MATCHED'}")
        if entry.mmproj_pattern:
            print(f"        vision /{entry.mmproj_pattern}/ -> {mmproj or 'NOTHING MATCHED'}")
        else:
            print("        vision none (text-only entry)")
        if not ok:
            bad += 1
            ggufs = [n for n in names if n.lower().endswith(".gguf")]
            print(f"        .gguf files present: {ggufs[:25]}")

    for repo in sys.argv[1:]:
        names, why = files_in(repo)
        ggufs = [n for n in names if n.lower().endswith(".gguf")]
        print(f"candidate {repo} -> {why or f'{len(names)} files'}; gguf: {ggufs[:25]}")

    print(f"\n{bad} catalogue entr{'y' if bad == 1 else 'ies'} did not resolve")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
