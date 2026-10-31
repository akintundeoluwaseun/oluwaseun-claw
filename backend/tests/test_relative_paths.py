"""Relative folder names from the brain land in the authorized folder they name (seen on Windows: "Documents")."""

import pytest

from claw.permissions.policy import DEFAULT_MODES, PathNotAuthorized, PermissionPolicy


def test_relative_names_start_at_the_matching_authorized_folder(tmp_path):
    docs, desk = tmp_path / "Documents", tmp_path / "Desktop"
    docs.mkdir(); desk.mkdir()
    pol = PermissionPolicy(DEFAULT_MODES, [str(docs), str(desk)])
    assert pol.check_path("Documents") == docs.resolve()
    assert pol.check_path("documents/invoice.pdf") == (docs / "invoice.pdf").resolve()
    assert pol.check_path("Desktop\\notes.txt".replace("\\", "/")) == (desk / "notes.txt").resolve()
    assert pol.check_path("Backup") == (docs / "Backup").resolve()      # no match: the first folder
    assert pol.unattended().check_path("Desktop") == desk.resolve()


def test_relative_paths_cannot_climb_out(tmp_path):
    docs = tmp_path / "Documents"
    docs.mkdir()
    pol = PermissionPolicy(DEFAULT_MODES, [str(docs)])
    with pytest.raises(PathNotAuthorized):
        pol.check_path("../secret.txt")
    with pytest.raises(PathNotAuthorized):
        pol.check_path("Documents/../../secret.txt")


def test_rooted_paths_are_never_anchored(tmp_path):
    docs = tmp_path / "Documents"
    docs.mkdir()
    pol = PermissionPolicy(DEFAULT_MODES, [str(docs)])
    for raw in ("/etc/passwd", "\\Windows\\win.ini", "C:secret.txt"):
        assert docs not in pol._anchor(raw).parents and pol._anchor(raw) != docs, raw
