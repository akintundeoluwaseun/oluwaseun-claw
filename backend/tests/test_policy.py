import os

import pytest

from claw.permissions.policy import Decision, PathNotAuthorized, PermissionPolicy, RiskLevel


@pytest.fixture
def policy(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    (tmp_path / "secret").mkdir()
    return PermissionPolicy({}, [str(allowed)]), tmp_path


def test_path_inside_is_allowed(policy):
    p, root = policy
    assert p.check_path(root / "allowed" / "a.txt").name == "a.txt"


def test_traversal_is_blocked(policy):
    p, root = policy
    with pytest.raises(PathNotAuthorized):
        p.check_path(str(root / "allowed" / ".." / "secret" / "x.txt"))


def test_sibling_prefix_is_blocked(policy):
    p, root = policy
    (root / "allowed-evil").mkdir()
    with pytest.raises(PathNotAuthorized):
        p.check_path(root / "allowed-evil" / "x.txt")


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="no symlinks")
def test_symlink_escape_is_blocked(policy):
    p, root = policy
    link = root / "allowed" / "link"
    try:
        os.symlink(root / "secret", link, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation not permitted")
    with pytest.raises(PathNotAuthorized):
        p.check_path(link / "x.txt")


def test_no_folders_means_no_access(tmp_path):
    with pytest.raises(PathNotAuthorized) as exc:
        PermissionPolicy({}, []).check_path(tmp_path)
    assert "no folders" in exc.value.reason


def test_null_byte_rejected(policy):
    p, root = policy
    with pytest.raises(PathNotAuthorized):
        p.check_path(str(root / "allowed") + "\x00.txt")


def test_destructive_floor_enforced():
    p = PermissionPolicy({RiskLevel.DESTRUCTIVE: Decision.ALLOW}, [])
    assert p.decide(RiskLevel.DESTRUCTIVE) == Decision.ASK


def test_defaults_match_settings_defaults():
    p = PermissionPolicy({}, [])
    assert p.decide(RiskLevel.READ_ONLY) == Decision.ALLOW
    assert p.decide(RiskLevel.EXTERNAL) == Decision.ASK
