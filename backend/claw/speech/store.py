"""Where voice models live on disk, and whether they are really there.

One folder per model under <data dir>/voice-models/<id>, with a meta.json
recording what was installed. A model counts as installed only when every file
it needs is present and the size on disk matches what was downloaded, so a
half-finished or truncated download is reported as damaged rather than loaded.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

META_NAME = "meta.json"


@dataclass
class InstalledVoiceModel:
    id: str
    name: str
    engine: str
    folder: Path
    files: dict[str, str] = field(default_factory=dict)  # role -> file name inside folder
    sizes: dict[str, int] = field(default_factory=dict)  # role -> expected bytes
    languages: list[str] = field(default_factory=list)
    license: str = ""
    source: str = ""
    verified: bool = False  # a SHA-256 was checked for every file at download

    def path(self, role: str) -> Path:
        return self.folder / self.files[role]

    def missing(self) -> list[str]:
        """Roles whose file is absent or the wrong size."""
        bad = []
        for role, name in self.files.items():
            f = self.folder / name
            if not f.is_file():
                bad.append(role)
                continue
            want = self.sizes.get(role)
            if want and f.stat().st_size != want:
                bad.append(role)
        return bad

    def present(self) -> bool:
        return bool(self.files) and not self.missing()

    def size_bytes(self) -> int:
        return sum(f.stat().st_size for f in self.folder.glob("*") if f.is_file())

    def as_dict(self) -> dict:
        missing = self.missing()
        return {
            "id": self.id,
            "name": self.name,
            "engine": self.engine,
            "languages": list(self.languages),
            "license": self.license,
            "source": self.source,
            "verified": self.verified,
            "present": not missing,
            "damaged_parts": missing,
            "folder": str(self.folder),
            "size_mb": round(self.size_bytes() / 1024**2, 1),
        }


class VoiceModelStore:
    """The installed voice models in one folder."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def folder_for(self, model_id: str) -> Path:
        return self.root / model_id

    def list(self) -> list[InstalledVoiceModel]:
        if not self.root.is_dir():
            return []
        out = []
        for d in sorted(p for p in self.root.iterdir() if p.is_dir()):
            got = self.load(d.name)
            if got:
                out.append(got)
        return out

    def load(self, model_id: str) -> InstalledVoiceModel | None:
        meta = self.folder_for(model_id) / META_NAME
        if not meta.is_file():
            return None
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict) or not data.get("files"):
            return None
        return InstalledVoiceModel(
            id=model_id,
            name=str(data.get("name") or model_id),
            engine=str(data.get("engine") or ""),
            folder=self.folder_for(model_id),
            files={str(k): str(v) for k, v in (data.get("files") or {}).items()},
            sizes={str(k): int(v) for k, v in (data.get("sizes") or {}).items()},
            languages=[str(x) for x in (data.get("languages") or [])],
            license=str(data.get("license") or ""),
            source=str(data.get("source") or ""),
            verified=bool(data.get("verified")),
        )

    def save_meta(self, model: InstalledVoiceModel) -> None:
        model.folder.mkdir(parents=True, exist_ok=True)
        (model.folder / META_NAME).write_text(
            json.dumps(
                {
                    "name": model.name,
                    "engine": model.engine,
                    "files": model.files,
                    "sizes": model.sizes,
                    "languages": model.languages,
                    "license": model.license,
                    "source": model.source,
                    "verified": model.verified,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def remove(self, model_id: str) -> bool:
        folder = self.folder_for(model_id)
        if not folder.is_dir():
            return False
        shutil.rmtree(folder, ignore_errors=True)
        return not folder.exists()
