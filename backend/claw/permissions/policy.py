"""Least-privilege permission model.

Every tool declares a risk level. The user's settings map each risk level to a
decision (allow / ask / deny). Destructive actions can never be auto-allowed.
File access is limited to folders the user has explicitly authorized.
"""

from __future__ import annotations

import os
import re
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
        self.root_paths = [Path(p).expanduser() for p in authorized_folders]
        # Individual files the user opened through Claw's file dialog (read access only).
        self.extra_files = {_canonical(Path(p)) for p in (extra_files or set())}

    def decide(self, risk: RiskLevel) -> Decision:
        return self.modes[risk]

    def unattended(self) -> "PermissionPolicy":
        """The same policy, for work nobody is watching.

        A scheduled job runs with no one there to answer, so every "ask"
        becomes "no". Waiting ten minutes for an approval that will never come,
        and then carrying on, is how an unattended agent does something nobody
        agreed to. Destructive work is refused outright, whatever the settings
        say: approval cannot be given by an empty room.
        """
        modes = {level: (Decision.DENY if decision == Decision.ASK else decision)
                 for level, decision in self.modes.items()}
        modes[RiskLevel.DESTRUCTIVE] = Decision.DENY
        clone = PermissionPolicy(modes, [], None)
        clone.modes = modes
        clone.authorized_roots = list(self.authorized_roots)
        clone.root_paths = list(self.root_paths)
        clone.extra_files = set(self.extra_files)
        return clone

    def check_path(self, candidate: str | os.PathLike[str], write: bool = False) -> Path:
        """Return the path, as the person spelled it, if it lies inside an authorized folder.

        Symlinks and '..' segments are resolved before the check, so a path
        cannot escape an authorized folder by traversal. The containment check
        is done on the case-folded form; what comes back keeps its real case,
        because the caller is about to create or move a file with it.
        """
        raw = str(candidate)
        if not raw or "\x00" in raw:
            raise PathNotAuthorized(raw, "the path is empty or contains invalid characters")
        # Two spellings of the same path, and they do different jobs. The folded
        # one answers "is this inside a folder you authorized?", because Windows
        # considers C:\\Users\\x and c:/users/x the same file. The real one is what
        # gets created, moved and shown. Returning the folded one - which is what
        # this used to do - meant every file tool on Windows worked on a path
        # whose case had been destroyed: asking for a folder called "Claw Test"
        # produced one called "claw test", and the summary said so too. On Linux
        # normcase does nothing, so nothing here showed it.
        real = self._anchor(raw).resolve(strict=False)
        folded = _canonical(real)
        if folded in self.extra_files and not write:
            return real
        if not self.authorized_roots:
            raise PathNotAuthorized(raw, "no folders have been authorized in Settings")
        for root in self.authorized_roots:
            if _is_within(folded, root):
                return real
        raise PathNotAuthorized(raw, "it is outside the folders you authorized")


    def _anchor(self, raw: str) -> Path:
        """Where a path the brain wrote without a drive letter actually points.

        The 2B brain on Windows asked for "Documents" and "Documents\\invoice.pdf".
        Resolved against the backend's working folder those were "outside the folders
        you authorized", though Documents was authorized. A relative path now starts
        at the authorized folder whose name it begins with, else at the first one.
        It is still checked against the authorized folders below like any other.
        """
        p = Path(raw).expanduser()
        # "/etc/passwd" is not absolute on Windows (no drive) but it means the root of
        # the drive, never "inside Documents". Only bare names are anchored.
        if p.is_absolute() or raw.startswith(("/", "\\", "~")) or re.match(r"^[A-Za-z]:", raw) or not self.root_paths:
            return p
        parts = re.split(r"[\\/]+", raw.strip())
        head = parts[0].strip().lower()
        for root in self.root_paths:
            if root.name.lower() == head:
                return root.joinpath(*parts[1:]) if parts[1:] else root
        return self.root_paths[0].joinpath(*parts)


def canonical_path(path: str | os.PathLike[str]) -> Path:
    """One spelling per file.

    Resolves '~', '..' and symlinks, and on Windows also folds case and slashes
    (os.path.normcase), because 'C:\\Users\\x' and 'c:/users/x' are the same file there.
    Anything that needs to recognise a path it has seen before must key on this.
    """
    return Path(os.path.normcase(str(Path(path).expanduser().resolve(strict=False))))


_canonical = canonical_path  # internal alias


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
