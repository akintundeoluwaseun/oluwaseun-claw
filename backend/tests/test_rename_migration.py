"""The rename to S-CLAW must not cost anyone their settings or task history.

The old product was "Oluwaseun Claw" and kept everything in %APPDATA%\\OluwaseunClaw
(or ~/.oluwaseun-claw). These tests cover what happens to that folder.
"""

import os
import sys
from pathlib import Path

import pytest

from claw import config


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A pretend home directory, on this platform's rules."""
    monkeypatch.delenv("CLAW_DATA_DIR", raising=False)
    if sys.platform == "win32":
        monkeypatch.setenv("APPDATA", str(tmp_path))
    else:
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    return tmp_path


def names():
    if sys.platform == "win32":
        return config.APP_DIR_WINDOWS, config.LEGACY_DIR_WINDOWS[0]
    return config.APP_DIR_UNIX, config.LEGACY_DIR_UNIX[0]


def make_old(home: Path) -> Path:
    """A previous install, with the things a person would hate to lose."""
    _, legacy = names()
    old = home / legacy
    (old / "models" / "qwen3-vl-4b").mkdir(parents=True)
    (old / "settings.json").write_text('{"version": 3}', encoding="utf-8")
    (old / "tasks.db").write_bytes(b"SQLite format 3\x00task history")
    (old / "models" / "qwen3-vl-4b" / "manifest.json").write_text('{"verified": true}', encoding="utf-8")
    return old


def test_a_previous_install_is_carried_over(home):
    old = make_old(home)
    new_name, _ = names()
    data = config.default_data_dir()
    assert data == home / new_name
    assert data.is_dir(), "the old folder was not carried over"
    assert (data / "settings.json").read_text(encoding="utf-8") == '{"version": 3}'
    assert (data / "tasks.db").read_bytes() == b"SQLite format 3\x00task history"
    assert (data / "models" / "qwen3-vl-4b" / "manifest.json").exists(), "a downloaded brain was lost"
    assert not old.exists(), "the rename should have moved it, not copied it"


def test_a_fresh_install_just_uses_the_new_name(home):
    new_name, _ = names()
    data = config.default_data_dir()
    assert data == home / new_name
    assert not data.exists()          # nothing is created until something is saved


def test_an_existing_new_folder_wins_and_nothing_is_merged(home):
    """Both folders present: the new one is the live one, the old is left alone."""
    old = make_old(home)
    new_name, _ = names()
    new = home / new_name
    new.mkdir()
    (new / "settings.json").write_text('{"version": 4}', encoding="utf-8")

    data = config.default_data_dir()
    assert data == new
    assert (new / "settings.json").read_text(encoding="utf-8") == '{"version": 4}'
    assert not (new / "tasks.db").exists(), "folders must not be silently merged"
    assert old.is_dir() and (old / "tasks.db").exists(), "the old folder must be left intact"


def test_when_the_move_fails_the_original_is_kept(home, monkeypatch):
    """A rename can fail across drives or on a locked file. Nothing may be lost."""
    old = make_old(home)

    def refuse(*a, **kw):
        raise OSError("cross-device link")

    monkeypatch.setattr(config.os, "replace", refuse)
    data = config.default_data_dir()
    assert (data / "tasks.db").read_bytes() == b"SQLite format 3\x00task history"
    assert old.is_dir() and (old / "tasks.db").exists(), "the original must survive a copy"
    assert (data / "MOVED-FROM.txt").exists(), "the copy should say where it came from"


def test_an_explicit_data_dir_still_wins(home, monkeypatch):
    make_old(home)
    chosen = home / "somewhere-else"
    monkeypatch.setenv("CLAW_DATA_DIR", str(chosen))
    assert config.default_data_dir() == chosen


def test_nothing_is_carried_over_from_a_file_with_the_old_name(home):
    """A *file* called OluwaseunClaw is not a data folder."""
    _, legacy = names()
    (home / legacy).write_text("not a folder", encoding="utf-8")
    new_name, _ = names()
    assert config.default_data_dir() == home / new_name
    assert (home / legacy).is_file()
