"""Least-privilege permission model.

Every tool declares a risk level. The user's settings map each risk level to a
decision (allow / ask / deny). Destructive actions can never be auto-allowed.
File access is limited to folders the user has explicitly authorized.
"""

from __future__ import annotations

import os
from enum import StrEnum
from pathlib import Path


class RiskLevel(StrEnum):
    READ_ONLY = "read_only"  # looking at things: reading a page, listing a folder, screenshots
    LOCAL_WRITE = "local_write"  # creating/editing files in authorized folders, typing into apps
    EXTERNAL = "external"  # changes outside this computer: submitting forms, posting
    DESTRUCTIVE = "destructive"  # deleting, sending messages, purchases, account changes


class Decision(StrEnum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


DEFAULT_MODES: dict[RiskLevel, Decision] = {
    RiskLevel.READ_ONLY: Decision.ALLOW,
    RiskLevel.LOCAL_WRITE: Decision.ASK,
    RiskLevel.EXTERNAL: Decision.ASK,
    RiskLevel.DESTRUCTIVE: Decision.ASK,
}


class PathNotAuthorized(Exception):
    def __init__(self, path: str, reason: str):
        super().__init__(f"Access to '{path}' is not allowed: {reason}")
        self.path = path
        self.reason = reason


class PermissionPolicy:
    def __init__(self, modes: dict[RiskLevel, Decision], authorized_folders: list[str], extra_files: set[str] | None = None):
        self.modes = {level: modes.get(level, DEFAULT_MODES[level]) for level in RiskLevel}
        # Safety floor, enforced here as well as in settings validation.
        if self.modes[RiskLevel.DESTRUCTIVE] == Decision.ALLOW:
            self.modes[RiskLevel.DESTRUCTIVE] = Decision.ASK
        self.authorized_roots = [_canonical(Path(p)) for p in authorized_folders]
        # Individual files the user opened through Claw's file dialog (read access only).
        self.extra_files = {_canonical(Path(p)) for p in (extra_files or set())}

    def decide(self, risk: RiskLevel) -> Decision:
        return self.modes[risk]

    def check_path(self, candidate: str | os.PathLike[str], write: bool = False) -> Path:
        """Return the canonical path if it lies inside an authorized folder.

        Symlinks and '..' segments are resolved before the check, so a path
        cannot escape an authorized folder by traversal.
        """
        raw = str(candidate)
        if not raw or "\x00" in raw:
            raise PathNotAuthorized(raw, "the path is empty or contains invalid characters")
        resolved = _canonical(Path(raw))
        if resolved in self.extra_files and not write:
            return resolved
        if not self.authorized_roots:
            raise PathNotAuthorized(raw, "no folders have been authorized in Settings")
        for root in self.authorized_roots:
            if _is_within(resolved, root):
                return resolved
        raise PathNotAuthorized(raw, "it is outside the folders you authorized")


def _canonical(path: Path) -> Path:
    return Path(os.path.normcase(str(path.expanduser().resolve(strict=False))))


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
