"""Pillow, loaded the first time it is actually used.

Importing Pillow costs about 0.4 s on an ordinary laptop, most of it in the
compiled `_imaging` and `_imagingft` extensions. Claw's tool registry imports
every tool module at start-up so the model can be told what exists, which meant
that cost was paid on every launch — before the window could accept a word —
even though most sessions never touch an image.

These stand-ins behave like the modules they replace for attribute access,
which is the only way Claw uses them (`Image.open`, `ImageOps.fit`,
`ImageFont.truetype`, `isinstance(x, Image.Image)`), so call sites are
unchanged. The real module is imported on first attribute access and kept.

Use the real import inside a function if you ever need the module object
itself, `from PIL.Image import something`, or a subclass of a Pillow class.
"""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any

__all__ = ["Image", "ImageDraw", "ImageEnhance", "ImageFont", "ImageOps"]


class _LazyModule:
    __slots__ = ("_name", "_module")

    def __init__(self, name: str) -> None:
        self._name = name
        self._module: ModuleType | None = None

    def _load(self) -> ModuleType:
        if self._module is None:
            self._module = importlib.import_module(self._name)
        return self._module

    def __getattr__(self, attr: str) -> Any:
        return getattr(self._load(), attr)

    def __dir__(self) -> list[str]:
        return dir(self._load())

    def __repr__(self) -> str:
        state = "loaded" if self._module is not None else "not loaded yet"
        return f"<lazy {self._name} ({state})>"


Image = _LazyModule("PIL.Image")
ImageDraw = _LazyModule("PIL.ImageDraw")
ImageEnhance = _LazyModule("PIL.ImageEnhance")
ImageFont = _LazyModule("PIL.ImageFont")
ImageOps = _LazyModule("PIL.ImageOps")
