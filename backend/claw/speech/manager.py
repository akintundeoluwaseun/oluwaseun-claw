"""Setting up a voice model: download, verify, repair, remove.

Reuses claw.runtime.hub, so a voice model gets the same treatment as a brain:
the file list and checksums come from the public API, disk space is checked
first, downloads resume from a .part file, SHA-256 is verified where the API
publishes one, and the user can cancel.

Nothing downloads on its own. A download starts only when the user asks for one.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

from claw.logging_setup import log_event
from claw.runtime.hub import DownloadError, check_disk, download_file, resolve_many
from claw.speech import catalog
from claw.speech.store import InstalledVoiceModel, VoiceModelStore

log = logging.getLogger("claw.speech")


@dataclass
class VoiceDownload:
    id: str | None = None
    status: str = "idle"  # idle | resolving | downloading | verifying | done | failed | cancelled
    done_bytes: int = 0
    total_bytes: int = 0
    message: str = ""

    def as_dict(self) -> dict:
        pct = round(self.done_bytes / self.total_bytes, 3) if self.total_bytes else 0.0
        return {**asdict(self), "progress": pct}


class VoiceModels:
    """The catalogue, what is installed, and getting one installed."""

    def __init__(self, store: VoiceModelStore):
        self.store = store
        self.download = VoiceDownload()
        self._task: asyncio.Task | None = None
        self._cancel = asyncio.Event()

    # ---------- reading ----------
    def installed(self) -> list[InstalledVoiceModel]:
        return self.store.list()

    def get_installed(self, model_id: str) -> InstalledVoiceModel | None:
        got = self.store.load(model_id)
        return got if got and got.present() else None

    def active(self, selected: str | None) -> InstalledVoiceModel | None:
        """The user's pick if it is installed and whole, otherwise any installed model."""
        usable = [m for m in self.installed() if m.present()]
        if selected:
            chosen = next((m for m in usable if m.id == selected), None)
            if chosen:
                return chosen
        return usable[0] if usable else None

    def catalogue(self, total_ram_gb: float | None) -> list[dict]:
        by_id = {m.id: m for m in self.installed()}
        out = []
        for entry in catalog.CATALOG:
            got = by_id.get(entry.id)
            out.append(
                {
                    **entry.as_dict(),
                    "fits": catalog.fits(entry, total_ram_gb),
                    "installed": bool(got and got.present()),
                    "damaged": bool(got and not got.present()),
                    "recommended": entry.id == catalog.recommended(total_ram_gb).id,
                }
            )
        return out

    # ---------- changing ----------
    def start_download(self, model_id: str) -> None:
        """Begin a download in the background. Raises DownloadError if it cannot start."""
        if self._task and not self._task.done():
            raise DownloadError("Claw is already setting up a voice model.")
        entry = catalog.get(model_id)
        if entry is None:
            raise DownloadError(f"There is no voice model called '{model_id}'.")
        self._cancel = asyncio.Event()
        self.download = VoiceDownload(id=model_id, status="resolving")
        self._task = asyncio.create_task(self._run(entry))

    def cancel(self) -> None:
        self._cancel.set()

    def remove(self, model_id: str) -> bool:
        gone = self.store.remove(model_id)
        if gone:
            log_event(log, "voice model removed", model=model_id)
        return gone

    async def _run(self, entry: catalog.VoiceModel) -> None:
        folder = self.store.folder_for(entry.id)
        try:
            lic, files = await resolve_many(
                entry.repo, entry.files, label=entry.name, allowed=catalog.ALLOWED_LICENSES
            )
            total = sum(f.size for f in files.values())
            self.download.total_bytes = total
            check_disk(folder, total)
            self.download.status = "downloading"
            folder.mkdir(parents=True, exist_ok=True)

            done_before = 0
            names: dict[str, str] = {}
            sizes: dict[str, int] = {}
            all_verified = True
            for role, remote in files.items():
                dest = folder / Path(remote.name).name

                def progress(done: int, _total: int, _base: int = done_before) -> None:
                    self.download.done_bytes = _base + done

                verified = await download_file(entry.repo, remote, dest, progress, self._cancel)
                all_verified = all_verified and verified
                done_before += remote.size
                self.download.done_bytes = done_before
                names[role] = dest.name
                sizes[role] = remote.size

            self.download.status = "verifying"
            model = InstalledVoiceModel(
                id=entry.id,
                name=entry.name,
                engine=entry.engine,
                folder=folder,
                files=names,
                sizes=sizes,
                languages=list(entry.languages),
                license=lic,
                source=f"huggingface.co/{entry.repo}",
                verified=all_verified,
            )
            bad = model.missing()
            if bad:
                raise DownloadError(f"{entry.name} did not download completely ({', '.join(bad)}). Try again.")
            self.store.save_meta(model)
            self.download.status = "done"
            self.download.message = (
                f"{entry.name} is ready." if all_verified else f"{entry.name} is ready (the library published no checksum)."
            )
            log_event(log, "voice model installed", model=entry.id, verified=all_verified, license=lic)
        except asyncio.CancelledError:
            self.download.status = "cancelled"
            self.download.message = "Setup cancelled."
            self._cleanup_partial(folder)
            raise
        except DownloadError as exc:
            self.download.status = "failed"
            self.download.message = exc.args[0] if exc.args else "The download failed."
            self._cleanup_partial(folder)
            log_event(log, "voice model download failed", model=entry.id, reason=self.download.message)
        except Exception as exc:  # noqa: BLE001 - never leave the UI on "downloading"
            self.download.status = "failed"
            self.download.message = "The download failed unexpectedly."
            self._cleanup_partial(folder)
            log.exception("voice model download crashed: %s", exc)

    def _cleanup_partial(self, folder: Path) -> None:
        """A cancelled or failed download must not look like an installed model."""
        if not folder.is_dir():
            return
        for part in folder.glob("*.part"):
            part.unlink(missing_ok=True)
        got = self.store.load(folder.name)
        if got is None or not got.present():
            self.store.remove(folder.name)
