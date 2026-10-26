"""Automatic model choice and setup.

Claw picks models by role and by what this computer can carry, downloads them
through Ollama on its own, and keeps only what it needs loaded:

- "think": plans tasks and decides each step (always needed).
- "see": reads screenshots (needed only for some desktop steps; downloaded
  after the thinking model, and only on computers with enough memory).

Running several models at once would use several GB of memory each and make the
computer lag, so models are loaded one at a time and unloaded when Claw is idle.

The model sizes below are approximate download sizes from the Ollama library.
They have not yet been measured on real Windows laptops; if a download is not
available, Claw falls back to the next smaller option.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from claw.logging_setup import log_event
from claw.models.base import ModelError
from claw.models.hardware import Hardware, detect, worker_threads
from claw.models.ollama import OllamaAdapter

log = logging.getLogger("claw.models.auto")


@dataclass(frozen=True)
class Option:
    tag: str
    download_gb: float
    min_ram_gb: float  # system memory needed when running on the processor
    min_vram_gb: float  # or graphics memory needed when an NVIDIA GPU is present


THINK_OPTIONS = [
    Option("qwen2.5:14b", 9.0, 28, 12),
    Option("qwen2.5:7b", 4.7, 14, 7),
    Option("qwen2.5:3b", 1.9, 7, 3),
    Option("qwen2.5:1.5b", 1.0, 0, 0),
]
SEE_OPTIONS = [
    Option("qwen2.5vl:7b", 6.0, 22, 9),
    Option("qwen2.5vl:3b", 3.2, 11, 5),
]
ROLES = ("think", "see")


def fits(opt: Option, hw: Hardware) -> bool:
    if hw.gpu_vram_gb is not None and hw.gpu_vram_gb >= opt.min_vram_gb:
        return True
    ram = hw.total_ram_gb if hw.total_ram_gb is not None else 8.0  # unknown: assume a modest laptop
    return ram >= opt.min_ram_gb


def candidates(role: str, hw: Hardware) -> list[Option]:
    """Best option that fits first, then smaller fallbacks."""
    options = THINK_OPTIONS if role == "think" else SEE_OPTIONS
    fitting = [o for o in options if fits(o, hw)]
    return fitting


@dataclass
class RoleState:
    role: str
    options: list[Option]
    index: int = 0
    status: str = "unknown"  # unknown | installed | missing | downloading | failed | unavailable
    completed: int = 0
    total: int = 0
    error: str = ""

    @property
    def tag(self) -> str | None:
        return self.options[self.index].tag if self.index < len(self.options) else None

    @property
    def option(self) -> Option | None:
        return self.options[self.index] if self.index < len(self.options) else None

    def as_dict(self) -> dict[str, Any]:
        opt = self.option
        return {
            "role": self.role,
            "model": self.tag,
            "download_gb": opt.download_gb if opt else None,
            "status": self.status,
            "progress": round(self.completed / self.total, 3) if self.total else 0.0,
            "completed_bytes": self.completed,
            "total_bytes": self.total,
            "error": self.error,
        }


@dataclass
class ModelManager:
    base_url: str
    hardware: Hardware = field(default_factory=lambda: detect())
    roles: dict[str, RoleState] = field(default_factory=dict)
    ollama_reachable: bool | None = None
    _task: asyncio.Task | None = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def __post_init__(self) -> None:
        for role in ROLES:
            opts = candidates(role, self.hardware)
            self.roles[role] = RoleState(role, opts, status="unavailable" if not opts else "unknown")

    # ---------- what to use ----------
    def model_for(self, role: str) -> str | None:
        st = self.roles[role]
        return st.tag if st.status == "installed" else None

    def threads(self) -> int:
        return worker_threads(self.hardware.cpu_cores)

    def ready(self) -> bool:
        return self.roles["think"].status == "installed"

    def not_ready_message(self) -> tuple[str, str]:
        think = self.roles["think"]
        if self.ollama_reachable is False:
            return ("Claw's brain engine is not running.", "Restart Claw. If this keeps happening, reinstall Claw.")
        if think.status == "downloading":
            pct = int(100 * think.completed / think.total) if think.total else 0
            return (f"Claw is still setting up its brain ({pct}%).", "Tasks can start as soon as this finishes.")
        if think.status == "failed":
            return (f"Claw could not set up its brain: {think.error}", "Claw will try again.")
        return ("Claw is getting its model ready.", "This happens once, on first use.")

    def summary(self) -> dict[str, Any]:
        return {
            "hardware": self.hardware.as_dict(),
            "hardware_text": self.hardware.describe(),
            "ollama_reachable": self.ollama_reachable,
            "ready": self.ready(),
            "threads": self.threads(),
            "roles": {r: s.as_dict() for r, s in self.roles.items()},
        }

    # ---------- setup ----------
    def _adapter(self, tag: str = "") -> OllamaAdapter:
        return OllamaAdapter(self.base_url, tag, timeout_s=30, temperature=0)

    async def refresh(self) -> None:
        try:
            installed = {m.name for m in await self._adapter().list_models()}
            self.ollama_reachable = True
        except ModelError:
            self.ollama_reachable = False
            return
        for st in self.roles.values():
            if st.status in ("downloading", "unavailable"):
                continue
            tag = st.tag
            if tag and (tag in installed or f"{tag}:latest" in installed):
                st.status = "installed"
            elif st.status != "failed":
                st.status = "missing"

    def start(self) -> None:
        """Begin (or resume) background setup. Safe to call repeatedly."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._setup_loop(), name="claw-model-setup")

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def retry(self) -> None:
        for st in self.roles.values():
            if st.status == "failed":
                st.status, st.error = "missing", ""
        self.start()

    async def _setup_loop(self) -> None:
        delay = 5
        while True:
            async with self._lock:
                await self.refresh()
                if self.ollama_reachable:
                    for role in ROLES:  # thinking model first; seeing model only after it
                        st = self.roles[role]
                        if st.status == "missing":
                            await self._download(st)
                        if role == "think" and st.status != "installed":
                            break
            done = all(s.status in ("installed", "unavailable") for s in self.roles.values())
            if done:
                return
            await asyncio.sleep(delay)
            delay = min(delay * 2, 120)

    async def _download(self, st: RoleState) -> None:
        while st.option is not None:
            tag = st.tag
            st.status, st.completed, st.total, st.error = "downloading", 0, 0, ""
            log_event(log, "downloading model", role=st.role, model=tag)
            try:
                async for update in self._adapter(tag).pull():
                    if update.get("total"):
                        st.total = int(update["total"])
                        st.completed = int(update.get("completed") or 0)
                st.status = "installed"
                log_event(log, "model ready", role=st.role, model=tag)
                return
            except ModelError as exc:
                if "not found" in exc.message.lower() or "file does not exist" in exc.message.lower():
                    log_event(log, "model not in library; trying smaller option", model=tag)
                    st.index += 1
                    continue
                st.status, st.error = "failed", exc.message
                return
        st.status, st.error = "unavailable", "No suitable model could be downloaded."

    async def unload_all(self) -> None:
        """Free memory when Claw is idle."""
        for st in self.roles.values():
            if st.status == "installed" and st.tag:
                try:
                    await self._adapter(st.tag).unload()
                except ModelError:
                    pass
