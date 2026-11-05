"""Picking the wrong file as a brain, and being told which wrong file it is.

The owner downloaded a .bin from the release page, tried to load it as a brain,
and got "That file is not a GGUF model." The .bin files are parts of the
Windows installer. The message said what the file was not, which left him with
no way to work out what to pick instead.

Each of these is a mistake someone will actually make: the installer parts and
the installer itself sit on the same page as the brains, the vision file sits
in the same folder as the brain and is a .gguf too, and a half-finished
download looks like the real thing.
"""

from pathlib import Path

import pytest

from claw.runtime.store import ModelStore, why_not_a_brain


def make(tmp_path, name, data=b"not a brain", size=None):
    p = tmp_path / name
    p.write_bytes(data if size is None else data + b"\0" * (size - len(data)))
    return p


def test_an_installer_part_says_so(tmp_path):
    why = why_not_a_brain(make(tmp_path, "S-CLAW-0.5.0-Local-Standard-Setup-1.bin"))
    assert "part of the S-CLAW installer" in why and ".gguf" in why


def test_the_installer_itself_says_so(tmp_path):
    assert "installer" in why_not_a_brain(make(tmp_path, "S-CLAW-Windows-Setup.exe"))


def test_a_zip_says_unpack_it(tmp_path):
    assert "Unpack it first" in why_not_a_brain(make(tmp_path, "brains.zip"))


def test_an_unfinished_download_says_so(tmp_path):
    assert "has not finished" in why_not_a_brain(make(tmp_path, "brain.gguf.part"))


def test_anything_else_names_what_a_brain_looks_like(tmp_path):
    why = why_not_a_brain(make(tmp_path, "notes.txt"))
    assert ".gguf" in why and "S-CLAW-Brain-Standard-4B-00001-of-00002.gguf" in why


def test_a_small_gguf_reads_as_an_incomplete_download(tmp_path):
    why = why_not_a_brain(make(tmp_path, "S-CLAW-Brain-Light-2B.gguf", size=5 * 1024 * 1024))
    assert "incomplete download" in why


def test_a_large_gguf_with_wrong_contents_reads_as_damaged(tmp_path):
    why = why_not_a_brain(make(tmp_path, "big.gguf", size=200 * 1024 * 1024))
    assert "damaged" in why


# ---------- through the importer ----------
def test_importing_an_installer_part_explains_itself(tmp_path):
    store = ModelStore(tmp_path / "data")
    bad = make(tmp_path, "S-CLAW-0.5.0-Local-Standard-Setup-2.bin")
    with pytest.raises(ValueError) as exc:
        store.import_file(bad)
    assert "part of the S-CLAW installer" in str(exc.value)


def test_picking_the_vision_file_instead_of_the_brain(tmp_path):
    # It is a real .gguf, in the same folder, named almost the same. The old
    # code would have accepted it and installed a brain that cannot think.
    store = ModelStore(tmp_path / "data")
    vision = tmp_path / "S-CLAW-Brain-Standard-4B-mmproj.gguf"
    vision.write_bytes(b"GGUF" + b"\0" * 1024)
    with pytest.raises(ValueError) as exc:
        store.import_file(vision)
    assert "vision file" in str(exc.value) and "without -mmproj" in str(exc.value)


def test_a_file_that_vanished_says_that_and_not_something_about_gguf(tmp_path):
    store = ModelStore(tmp_path / "data")
    with pytest.raises(ValueError) as exc:
        store.import_file(tmp_path / "gone.gguf")
    assert "could not be opened" in str(exc.value)


def test_a_real_brain_still_imports(tmp_path):
    store = ModelStore(tmp_path / "data")
    good = tmp_path / "S-CLAW-Brain-Light-2B.gguf"
    good.write_bytes(b"GGUF" + b"\0" * 2048)
    m = store.import_file(good)
    assert m.name == "S-CLAW Light brain"
