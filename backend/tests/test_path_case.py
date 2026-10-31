"""Paths keep the case the person asked for.

check_path used to return os.path.normcase() of the resolved path. That is the
right spelling to COMPARE with - on Windows C:\\Users\\x and c:/users/x are one
file - but it is the wrong spelling to USE, and every file tool uses what
check_path hands back. On Windows that meant asking for a folder called
"Claw Test" created one called "claw test", and the summary reported the
lower-cased name as well.

Nothing here showed it, because os.path.normcase is the identity function on
Linux. These tests make the Windows behaviour explicit so the bug cannot come
back on a machine nobody runs the suite on.
"""

import os
from pathlib import Path

import pytest

from claw.permissions import policy as policy_mod
from claw.permissions.policy import PathNotAuthorized, PermissionPolicy
from claw.tools.base import RiskLevel
from claw.config import DEFAULT_MODES


@pytest.fixture
def windows_case(monkeypatch):
    """Make normcase behave the way it does on Windows."""
    monkeypatch.setattr(os.path, "normcase", lambda s: str(s).replace("/", os.sep).lower())
    return None


def _policy(root: Path) -> PermissionPolicy:
    return PermissionPolicy(dict(DEFAULT_MODES), [str(root)])


def test_case_is_preserved_in_what_comes_back(tmp_path, windows_case):
    root = tmp_path / "Saved"
    root.mkdir()
    pol = _policy(root)
    got = pol.check_path(root / "Claw Test", write=True)
    assert got.name == "Claw Test", (
        "check_path lower-cased the name; a folder created from this would be "
        f"called {got.name!r} instead of 'Claw Test'"
    )


def test_a_folder_created_through_the_policy_keeps_its_name(tmp_path, windows_case):
    root = tmp_path / "Saved"
    root.mkdir()
    pol = _policy(root)
    target = pol.check_path(root / "Quarterly Reports", write=True)
    target.mkdir()
    assert [p.name for p in root.iterdir()] == ["Quarterly Reports"]


def test_containment_still_ignores_case(tmp_path, windows_case):
    """The whole reason for folding: a differently-cased path is the same folder."""
    root = tmp_path / "Saved"
    root.mkdir()
    pol = _policy(root)
    odd = str(root).upper() + os.sep + "notes.txt"
    assert pol.check_path(odd, write=True).name == "notes.txt"


def test_a_path_outside_is_still_refused(tmp_path, windows_case):
    root = tmp_path / "Saved"
    root.mkdir()
    (tmp_path / "Elsewhere").mkdir()
    pol = _policy(root)
    with pytest.raises(PathNotAuthorized):
        pol.check_path(tmp_path / "Elsewhere" / "secret.txt", write=True)


def test_traversal_is_still_refused(tmp_path, windows_case):
    root = tmp_path / "Saved"
    root.mkdir()
    (tmp_path / "Elsewhere").mkdir()
    pol = _policy(root)
    with pytest.raises(PathNotAuthorized):
        pol.check_path(str(root / ".." / "Elsewhere" / "secret.txt"), write=True)
