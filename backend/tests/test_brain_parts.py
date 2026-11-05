"""Brains downloaded from the release page in parts (llama.cpp split naming) import as one brain."""

from pathlib import Path

import pytest

from claw.runtime.store import ModelStore


def gguf(path, size=64):
    path.write_bytes(b"GGUF" + b"\0" * size)
    return path


def test_split_brain_with_its_vision_file(tmp_path):
    d = tmp_path / "downloads"
    d.mkdir()
    first = gguf(d / "S-CLAW-Brain-Standard-4B-00001-of-00002.gguf")
    gguf(d / "S-CLAW-Brain-Standard-4B-00002-of-00002.gguf", 128)
    vision = gguf(d / "S-CLAW-Brain-Standard-4B-mmproj.gguf", 16)
    m = ModelStore(tmp_path / "data").import_file(first)
    assert m.name == "S-CLAW Standard brain"
    assert m.size_bytes == (4 + 64) + (4 + 128) + (4 + 16)
    # Importing copies into Claw's folder now (test_brain_import.py), so the
    # path is no longer the download's. What this test is really about is that
    # the vision file was recognised and kept with the model, which llama.cpp
    # requires to be in the same directory as the first part.
    assert m.mmproj_file is not None
    kept = Path(m.mmproj_file)
    assert kept.name == vision.name and kept.is_file()
    assert kept.parent == Path(m.model_file).parent


def test_wrong_part_or_missing_part_is_explained(tmp_path):
    d = tmp_path / "dl"
    d.mkdir()
    second = gguf(d / "S-CLAW-Brain-Pro-8B-00002-of-00003.gguf")
    with pytest.raises(ValueError, match="-00001-of-00003"):
        ModelStore(tmp_path / "data").import_file(second)
    first = gguf(d / "S-CLAW-Brain-Pro-8B-00001-of-00003.gguf")
    with pytest.raises(ValueError, match="missing"):
        ModelStore(tmp_path / "data").import_file(first)


def test_each_brain_finds_its_own_vision_file_in_a_shared_folder(tmp_path):
    d = tmp_path / "Downloads"
    d.mkdir()
    for n in ("Light-2B", "Standard-4B"):
        gguf(d / f"S-CLAW-Brain-{n}-mmproj.gguf")
    gguf(d / "S-CLAW-Brain-Light-2B.gguf")
    first = gguf(d / "S-CLAW-Brain-Standard-4B-00001-of-00002.gguf")
    gguf(d / "S-CLAW-Brain-Standard-4B-00002-of-00002.gguf")
    store = ModelStore(tmp_path / "data")
    assert store.import_file(first).mmproj_file.endswith("S-CLAW-Brain-Standard-4B-mmproj.gguf")
    assert store.import_file(d / "S-CLAW-Brain-Light-2B.gguf").mmproj_file.endswith("S-CLAW-Brain-Light-2B-mmproj.gguf")
