"""Narrow, read-only search of Chromium-family browsing history.

Privacy rules enforced here:
- Only the `History` database file is copied (to a temp folder, then deleted).
  Cookies, Login Data, Web Data and other profile files are never opened.
- Only the `urls` table is queried, and only url, title and last-visit time
  are returned, limited to a time window and a search phrase.

Support status:
- "claw" (the agent's own browser profile): tested with real Chromium.
- "chrome" / "edge" on Windows: reads the Default profile. The schema matches
  the agent's own Chromium profile, but this has not yet been tested against an
  installed Chrome or Edge on Windows.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from claw.tools.base import ToolError

# Chromium stores times as microseconds since 1601-01-01 UTC.
_CHROME_EPOCH = datetime(1601, 1, 1, tzinfo=UTC)

HISTORY_SOURCES = ("claw", "chrome", "edge")


def chrome_time(dt: datetime) -> int:
    return int((dt - _CHROME_EPOCH).total_seconds() * 1_000_000)


def from_chrome_time(value: int) -> datetime:
    return _CHROME_EPOCH + timedelta(microseconds=value)


def history_path(source: str, data_dir: Path) -> Path:
    if source == "claw":
        return data_dir / "browser-profile" / "Default" / "History"
    if sys.platform != "win32":
        raise ToolError("Reading Chrome or Edge history is only supported on Windows in this version.")
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    if source == "chrome":
        return local / "Google" / "Chrome" / "User Data" / "Default" / "History"
    if source == "edge":
        return local / "Microsoft" / "Edge" / "User Data" / "Default" / "History"
    raise ToolError(f"Unknown history source '{source}'.")


def search_history(db_path: Path, phrase: str, days: int, limit: int = 30) -> list[dict]:
    if not db_path.exists():
        raise ToolError("No browsing history was found for that browser on this computer.")
    tmpdir = Path(tempfile.mkdtemp(prefix="claw-hist-"))
    try:
        copy = tmpdir / "History"
        try:
            shutil.copyfile(db_path, copy)  # the live file is locked while the browser runs
        except OSError as exc:
            raise ToolError(f"The history file could not be read: {exc.strerror}") from exc
        since = chrome_time(datetime.now(UTC) - timedelta(days=days))
        like = "%" + phrase.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        conn = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
        try:
            rows = conn.execute(
                "SELECT url, title, last_visit_time FROM urls "
                "WHERE last_visit_time >= ? AND (title LIKE ? ESCAPE '\\' OR url LIKE ? ESCAPE '\\') "
                "ORDER BY last_visit_time DESC LIMIT ?",
                (since, like, like, limit),
            ).fetchall()
        except sqlite3.DatabaseError as exc:
            raise ToolError("The history file is in a format this version cannot read.") from exc
        finally:
            conn.close()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return [
        {"url": url, "title": title or "", "last_visit": from_chrome_time(ts).isoformat(timespec="seconds")}
        for url, title, ts in rows
        if url.startswith(("http://", "https://"))
    ]
