"""A brain file you already have, kept where Claw can still find it tomorrow.

Reported from a second laptop: the person had already downloaded the brain and
wanted to use that file rather than spend the data again. Import existed, but
the manifest pointed at wherever the file happened to be sitting - a Downloads
folder, a USB stick - so the brain worked until that was tidied away and then
failed with the engine refusing to start and nothing saying why.

Importing copies the file into Claw's own folder now. These are one to six
gigabyte files, so it is a default rather than a rule: a person deliberately
keeping models on a second drive can still import in place.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from claw.runtime.store import ModelStore

GGUF = b"GGUF" + b"\x00" * 60      # enough for is_gguf; nothing here starts an engine


def _gguf(path: Path, size: int = 4096) -> Path:
    path.write_bytes(GGUF + b"\x00" * max(0, size - len(GGUF)))
    return path


@pytest.fixture
def store(tmp_path) -> ModelStore:
    return ModelStore(tmp_path / "data")


@pytest.fixture
def elsewhere(tmp_path) -> Path:
    """Somewhere outside Claw: a Downloads folder, or a stick."""
    d = tmp_path / "Downloads"
    d.mkdir()
    return d


def test_the_file_is_copied_into_claws_own_folder(store, elsewhere):
    src = _gguf(elsewhere / "S-CLAW-Brain-Light-2B.gguf")
    m = store.import_file(src)
    kept = Path(m.model_path)
    assert kept != src, "the manifest still points at the original file"
    assert kept.is_file() and kept.read_bytes() == src.read_bytes()
    assert store.root in kept.parents, f"copied somewhere unexpected: {kept}"


def test_the_brain_survives_the_original_being_deleted(store, elsewhere):
    """The whole point. This is what happens when Downloads is cleared."""
    src = _gguf(elsewhere / "mybrain.gguf")
    m = store.import_file(src)
    src.unlink()
    assert Path(m.model_path).is_file()
    again = store.get(m.id)
    assert again is not None and Path(again.model_path).is_file()


def test_the_persons_own_file_is_never_touched(store, elsewhere):
    src = _gguf(elsewhere / "mine.gguf")
    before = src.read_bytes()
    store.import_file(src)
    assert src.is_file() and src.read_bytes() == before


def test_importing_in_place_is_still_possible(store, elsewhere):
    """Somebody keeping six gigabytes on a second drive on purpose."""
    src = _gguf(elsewhere / "ondrive.gguf")
    m = store.import_file(src, copy_in=False)
    assert Path(m.model_path) == src
    assert not (store.root / m.id).exists()


def test_a_vision_file_comes_with_it(store, elsewhere):
    src = _gguf(elsewhere / "S-CLAW-Brain-Standard-4B.gguf")
    _gguf(elsewhere / "S-CLAW-Brain-Standard-4B-mmproj.gguf", 2048)
    m = store.import_file(src)
    assert m.mmproj_path and Path(m.mmproj_path).is_file()
    assert Path(m.mmproj_path).parent == Path(m.model_path).parent, \
        "llama.cpp wants them side by side"


def test_every_part_of_a_split_brain_is_copied(store, elsewhere):
    for i in (1, 2, 3):
        _gguf(elsewhere / f"big-{i:05d}-of-00003.gguf")
    m = store.import_file(elsewhere / "big-00001-of-00003.gguf")
    kept = Path(m.model_path).parent
    assert sorted(p.name for p in kept.glob("*.gguf")) == [
        "big-00001-of-00003.gguf", "big-00002-of-00003.gguf", "big-00003-of-00003.gguf"], \
        "llama.cpp reads the later parts from the same folder; they must all be there"


def test_a_copy_that_runs_out_of_room_says_so_and_leaves_nothing_behind(store, elsewhere, monkeypatch):
    import shutil as sh
    src = _gguf(elsewhere / "huge.gguf")
    monkeypatch.setattr(sh, "disk_usage", lambda p: type("U", (), {"free": 1024, "total": 0, "used": 0})())
    with pytest.raises(ValueError, match="not enough room"):
        store.import_file(src)
    assert store.list() == [], "a failed import left a brain behind"
    assert not any(store.root.glob("*/*.gguf")), "a half-copy was left on disk"


def test_removing_an_imported_brain_deletes_claws_copy_only(store, elsewhere):
    src = _gguf(elsewhere / "temp.gguf")
    m = store.import_file(src)
    copy = Path(m.model_path)
    note = store.remove(m.id)
    assert not copy.exists(), "Claw's own copy was left behind"
    assert src.is_file(), "the person's file was deleted"
    assert "not touched" in note


def test_progress_is_reported_while_copying(store, elsewhere):
    """A six gigabyte copy with no sign of life looks like a hang."""
    src = _gguf(elsewhere / "watched.gguf", size=40 << 20)
    seen: list[tuple[int, int]] = []
    store.import_file(src, on_progress=lambda done, total: seen.append((done, total)))
    assert seen, "no progress was reported at all"
    assert seen[-1][0] == seen[-1][1] == src.stat().st_size
