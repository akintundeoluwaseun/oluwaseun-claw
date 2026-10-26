"""Claw's brain: which model to use, setting it up, and running it.

Choice: the user's explicit pick (Settings), otherwise the best installed brain
that fits this computer, otherwise nothing (the app offers the recommended
download — it never starts a multi-GB download without the user's click).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from claw.logging_setup import log_event
from claw.models.base import ModelNotFound
from claw.models.hardware import Hardware, detect
from claw.models.openai_compat import OpenAICompatAdapter
from claw.runtime import catalog, hub
from claw.runtime.engine import EngineError, LlamaServer, memory_needed_gb
from claw.runtime.store import InstalledModel, ModelStore

log = logging.getLogger("claw.brain")


@dataclass
class DownloadState:
    id: str | None = None
    status: str = "idle"  # idle | resolving | downloading | verifying | done | failed | cancelled
    done_bytes: int = 0
    total_bytes: int = 0
    message: str = ""
    started: float = 0

    def as_dict(self) -> dict:
        pct = round(self.done_bytes / self.total_bytes, 3) if self.total_bytes else 0.0
        return {**self.__dict__, "progress": pct}


@dataclass
class Brain:
    store: ModelStore
    engine: LlamaServer = field(default_factory=LlamaServer)
    hardware: Hardware = field(default_factory=lambda: detect())
    download: DownloadState = field(default_factory=DownloadState)
    _dl_task: asyncio.Task | None = None
    _dl_cancel: asyncio.Event = field(default_factory=asyncio.Event)

    # ---------- choosing ----------
    def active_model(self, selected: str | None) -> InstalledModel | None:
        installed = [m for m in self.store.list() if m.present()]
        if selected:
            chosen = next((m for m in installed if m.id == selected), None)
            if chosen:
                return chosen
        fitting = [m for m in installed if self._fits(m)]
        pool = fitting or installed
        return max(pool, key=lambda m: m.size_bytes) if pool else None

    def _fits(self, m: InstalledModel) -> bool:
        entry = catalog.get(m.id)
        if entry:
            return catalog.fits(entry, self.hardware)
        need = memory_needed_gb(m.size_bytes)
        return (self.hardware.total_ram_gb or 8) >= need + 2

    def summary(self, selected: str | None) -> dict:
        installed = self.store.list()
        active = self.active_model(selected)
        rec = catalog.recommended(self.hardware)
        ok, why = self.engine.available()
        return {
            "hardware": self.hardware.as_dict(),
            "hardware_text": self.hardware.describe(),
            # status first: when the engine is missing, that explanation must win over an empty status message
            "engine": {**self.engine.status.__dict__, "available": ok, "message": why or self.engine.status.message},
            "ready": bool(ok and active),
            "active": active.as_dict() if active else None,
            "selected": selected,
            "recommended": rec.id,
            "installed": [m.as_dict() for m in installed],
            "catalog": [
                {
                    **e.as_dict(),
                    "fits": catalog.fits(e, self.hardware),
                    "installed": any(m.id == e.id and m.present() for m in installed),
                    "recommended": e.id == rec.id,
                }
                for e in catalog.CATALOG
            ],
            "download": self.download.as_dict(),
        }

    def not_ready(self, selected: str | None) -> tuple[str, str]:
        ok, why = self.engine.available()
        if not ok:
            return why, "Reinstall Claw. Developers: run scripts\\setup.ps1."
        if self.download.status in ("resolving", "downloading", "verifying"):
            pct = int(100 * self.download.as_dict()["progress"])
            return f"Claw's brain is still downloading ({pct}%).", "Tasks can start when it finishes."
        return "Claw doesn't have a brain on this computer yet.", "Open Settings → Claw's brain and download the recommended one."

    # ---------- running ----------
    async def adapter(self, selected: str | None, timeout_s: float, temperature: float) -> OpenAICompatAdapter:
        m = self.active_model(selected)
        if m is None:
            raise ModelNotFound(*self.not_ready(selected))
        await self.engine.check_alive()
        try:
            await self.engine.ensure(m.id, m.model_path, m.mmproj_path)
        except EngineError as exc:
            raise ModelNotFound(exc.message, exc.hint) from exc
        a = OpenAICompatAdapter(self.engine.base_url, m.id, timeout_s=timeout_s, temperature=temperature)
        a.api_key = self.engine.api_key
        a.vision = m.vision
        return a

    def touch(self) -> None:
        self.engine.last_used = time.monotonic()

    # ---------- downloading ----------
    def start_download(self, entry_id: str) -> None:
        entry = catalog.get(entry_id)
        if entry is None:
            raise ValueError("Unknown brain.")
        if self._dl_task and not self._dl_task.done():
            raise ValueError("A download is already running.")
        self._dl_cancel = asyncio.Event()
        self.download = DownloadState(entry_id, "resolving", started=time.time(), message="Checking the model library…")
        self._dl_task = asyncio.create_task(self._download(entry))

    def cancel_download(self) -> bool:
        if self._dl_task and not self._dl_task.done():
            self._dl_cancel.set()
            return True
        return False

    async def _download(self, entry: catalog.CatalogEntry) -> None:
        st = self.download
        try:
            resolved = await hub.resolve(entry)
            folder = self.store.folder_for(entry.id)
            hub.check_disk(folder, resolved.total_bytes)
            st.status, st.total_bytes = "downloading", resolved.total_bytes
            st.message = f"Downloading {entry.name} ({resolved.total_bytes / 1024**3:.1f} GB, licence {resolved.license})"
            log_event(log, "brain download started", id=entry.id, bytes=resolved.total_bytes)
            files = [resolved.model] + ([resolved.mmproj] if resolved.mmproj else [])
            base = 0
            verified_all = True
            for f in files:
                def prog(done, _total, base=base):
                    st.done_bytes = base + done

                ok = await hub.download_file(entry.repo, f, folder / f.name, prog, self._dl_cancel)
                verified_all = verified_all and ok
                base += f.size
            st.status, st.message = "verifying", "Checking the files…"
            self.store.save_downloaded(
                entry.id, entry.name, folder / resolved.model.name,
                folder / resolved.mmproj.name if resolved.mmproj else None,
                resolved.license, verified_all, f"huggingface.co/{entry.repo}",
            )
            st.status, st.done_bytes = "done", st.total_bytes
            st.message = "Ready" + ("" if verified_all else " (the library published no checksum for some files)")
            log_event(log, "brain download finished", id=entry.id, verified=verified_all)
        except hub.DownloadError as exc:
            st.status = "cancelled" if self._dl_cancel.is_set() else "failed"
            st.message = f"{exc.message} {exc.hint}".strip()
            log_event(log, "brain download stopped", id=entry.id, status=st.status, reason=exc.message)
        except Exception:  # noqa: BLE001 — never crash the backend
            log.exception("brain download crashed")
            st.status, st.message = "failed", "The download stopped because of an unexpected error. See the log file."

    async def shutdown(self) -> None:
        self.cancel_download()
        if self._dl_task:
            try:
                await asyncio.wait_for(self._dl_task, 5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
        await self.engine.stop()
