"""Brains downloaded from the release page in parts (llama.cpp split naming) import as one brain."""

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
    assert m.name == "Standard brain (from the release page)"
    assert m.mmproj_file == str(vision) and m.size_bytes == (4 + 64) + (4 + 128) + (4 + 16)


def test_wrong_part_or_missing_part_is_explained(tmp_path):
    d = tmp_path / "dl"
    d.mkdir()
    second = gguf(d / "S-CLAW-Brain-Pro-8B-00002-of-00003.gguf")
    with pytest.raises(ValueError, match="-00001-of-00003"):
        ModelStore(tmp_path / "data").import_file(second)
    first = gguf(d / "S-CLAW-Brain-Pro-8B-00001-of-00003.gguf")
    with pytest.raises(ValueError, match="missing"):
        ModelStore(tmp_path / "data").import_file(first)
