"""Installed brains on this computer.

Three kinds, each described by a manifest.json:
- downloaded: in <data>/models/<id>/ — removable (files deleted)
- bundled:    in <resources>/models/<id>/ — shipped with the installer, not removable
- imported:   a GGUF the user picked; the manifest points at it, the file is never
              moved or deleted by Claw (removing only forgets it)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from claw.runtime.engine import APP_ROOT

GGUF_MAGIC = b"GGUF"


@dataclass
class InstalledModel:
    id: str
    name: str
    kind: str  # downloaded | bundled | imported
    model_file: str
    mmproj_file: str | None
    size_bytes: int
    license: str
    verified: bool  # SHA-256 matched the library's published checksum
    source: str
    added_at: float

    @property
    def model_path(self) -> Path:
        return Path(self.model_file)

    @property
    def mmproj_path(self) -> Path | None:
        return Path(self.mmproj_file) if self.mmproj_file else None

    @property
    def vision(self) -> bool:
        return self.mmproj_file is not None

    def present(self) -> bool:
        return self.model_path.is_file() and (self.mmproj_path is None or self.mmproj_path.is_file())

    def as_dict(self) -> dict:
        d = asdict(self)
        d.update(vision=self.vision, present=self.present(), size_gb=round(self.size_bytes / 1024**3, 2))
        return d


def is_gguf(path: Path) -> bool:
    try:
        with open(path, "rb") as fh:
            return fh.read(4) == GGUF_MAGIC
    except OSError:
        return False


def _bundled_root() -> Path:
    if os.environ.get("CLAW_RESOURCES"):
        return Path(os.environ["CLAW_RESOURCES"]) / "models"
    return APP_ROOT / "resources" / "models"


class ModelStore:
    def __init__(self, data_dir: Path):
        self.root = data_dir / "models"
        self.imported = self.root / "_imported"

    def _read(self, manifest: Path, kind: str) -> InstalledModel | None:
        try:
            d = json.loads(manifest.read_text(encoding="utf-8"))
            base = manifest.parent
            for key in ("model_file", "mmproj_file"):
                if d.get(key) and kind != "imported":
                    d[key] = str(base / d[key])  # stored relative to the model folder
            d["kind"] = kind
            return InstalledModel(**d)
        except (OSError, ValueError, TypeError):
            return None

    def list(self) -> list[InstalledModel]:
        out: list[InstalledModel] = []
        bundled = _bundled_root()
        if bundled.is_dir():
            for m in sorted(bundled.glob("*/manifest.json")):
                if (im := self._read(m, "bundled")) is not None:
                    out.append(im)
        if self.root.is_dir():
            for m in sorted(self.root.glob("*/manifest.json")):
                if m.parent == self.imported:
                    continue
                if (im := self._read(m, "downloaded")) is not None:
                    out.append(im)
        if self.imported.is_dir():
            for m in sorted(self.imported.glob("*.json")):
                if (im := self._read(m, "imported")) is not None:
                    out.append(im)
        return out

    def get(self, model_id: str) -> InstalledModel | None:
        return next((m for m in self.list() if m.id == model_id), None)

    def folder_for(self, model_id: str) -> Path:
        return self.root / model_id

    def save_downloaded(self, model_id: str, name: str, model_file: Path, mmproj_file: Path | None,
                        license: str, verified: bool, source: str) -> InstalledModel:
        folder = self.folder_for(model_id)
        size = model_file.stat().st_size + (mmproj_file.stat().st_size if mmproj_file else 0)
        manifest = {
            "id": model_id, "name": name, "model_file": model_file.name,
            "mmproj_file": mmproj_file.name if mmproj_file else None, "size_bytes": size,
            "license": license, "verified": verified, "source": source, "added_at": time.time(),
        }
        (folder / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return self.get(model_id)  # type: ignore[return-value]

    def import_file(self, path: Path, mmproj: Path | None = None) -> InstalledModel:
        if not path.is_file() or not is_gguf(path):
            raise ValueError("That file is not a GGUF model.")
        if mmproj is not None and (not mmproj.is_file() or not is_gguf(mmproj)):
            raise ValueError("The vision file is not a GGUF file.")
        slug = re.sub(r"[^a-z0-9]+", "-", path.stem.lower()).strip("-")[:50] or "model"
        model_id = f"local-{slug}"
        self.imported.mkdir(parents=True, exist_ok=True)
        manifest = {
            "id": model_id, "name": path.stem, "model_file": str(path), "mmproj_file": str(mmproj) if mmproj else None,
            "size_bytes": path.stat().st_size + (mmproj.stat().st_size if mmproj else 0),
            "license": "unknown (your own file)", "verified": False, "source": "chosen from this computer",
            "added_at": time.time(),
        }
        (self.imported / f"{model_id}.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return self.get(model_id)  # type: ignore[return-value]

    def remove(self, model_id: str) -> str:
        m = self.get(model_id)
        if m is None:
            raise ValueError("That brain is not installed.")
        if m.kind == "bundled":
            raise ValueError("This brain came with Claw and can't be removed. Uninstall Claw to remove it.")
        if m.kind == "imported":
            (self.imported / f"{model_id}.json").unlink(missing_ok=True)
            return "Claw no longer uses this file. The file itself was not deleted."
        shutil.rmtree(self.folder_for(model_id), ignore_errors=True)
        return "The brain was deleted from this computer."
