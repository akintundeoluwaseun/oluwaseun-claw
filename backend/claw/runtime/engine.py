"""Start, watch and stop llama.cpp's `llama-server` (MIT).

- Binary lookup: CLAW_LLAMA_SERVER → bundled resources/engine → backend/runtime/llama
  (put there by scripts/setup.ps1) → llama-server on PATH.
- Always binds 127.0.0.1 on a free port, with a random API key per launch, so
  nothing else on the network or the computer can use it.
- Refuses to start when the model clearly won't fit in free memory.
- Waits for the model to load, reports crashes with the engine's own last
  messages, and stops gracefully (terminate → wait → kill).
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from claw.logging_setup import log_event, register_secret
from claw.models.hardware import detect, worker_threads

log = logging.getLogger("claw.runtime")

APP_ROOT = Path(__file__).resolve().parents[3]
EXE = "llama-server.exe" if sys.platform == "win32" else "llama-server"
LOAD_TIMEOUT_S = 300
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class EngineError(Exception):
    def __init__(self, message: str, hint: str = ""):
        super().__init__(message)
        self.message = message
        self.hint = hint


def _die_with_parent() -> None:  # pragma: no cover - runs in the child before exec
    """Linux: if the Claw backend is killed outright, the kernel stops the engine too."""
    try:
        import ctypes
        import signal

        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG
    except Exception:  # noqa: BLE001
        pass


def _windows_kill_on_close(proc: subprocess.Popen):
    """Windows: put the engine in a job object that is closed (and the engine killed)
    when the backend process ends for any reason, including being terminated."""
    try:
        import win32api
        import win32con
        import win32job

        job = win32job.CreateJobObject(None, "")
        info = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
        info["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, info)
        handle = win32api.OpenProcess(win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE, False, proc.pid)
        win32job.AssignProcessToJobObject(job, handle)
        return job  # keep a reference: closing it kills the engine
    except Exception as exc:  # noqa: BLE001 - never block starting the engine on this
        log_event(log, "engine job object unavailable", error=type(exc).__name__)
        return None


def find_engine() -> Path | None:
    if os.environ.get("CLAW_LLAMA_SERVER"):
        p = Path(os.environ["CLAW_LLAMA_SERVER"])
        return p if p.is_file() else None
    candidates = []
    if os.environ.get("CLAW_RESOURCES"):
        candidates.append(Path(os.environ["CLAW_RESOURCES"]) / "engine" / EXE)
    candidates += [APP_ROOT / "resources" / "engine" / EXE, APP_ROOT / "backend" / "runtime" / "llama" / EXE]
    for c in candidates:
        if c.is_file():
            return c
    found = shutil.which("llama-server")
    return Path(found) if found else None


def memory_needed_gb(model_bytes: int, mmproj_bytes: int = 0, ctx: int = 8192) -> float:
    """Rough need: weights + ~15% working memory + KV cache for the context (≈0.6 GB at 8k for 4–8B models)."""
    return round((model_bytes + mmproj_bytes) * 1.15 / 1024**3 + 0.6 * ctx / 8192, 1)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@dataclass
class EngineStatus:
    state: str = "stopped"  # stopped | starting | ready | failed
    message: str = ""
    model_id: str | None = None
    started_at: float | None = None
    restarts: int = 0


@dataclass
class LlamaServer:
    binary: Path | None = field(default_factory=find_engine)
    ctx_size: int = 8192
    status: EngineStatus = field(default_factory=EngineStatus)
    port: int | None = None
    api_key: str = ""
    _proc: subprocess.Popen | None = None
    _tail: deque = field(default_factory=lambda: deque(maxlen=40))
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _reader: asyncio.Task | None = None
    last_used: float = field(default_factory=time.monotonic)
    _launch: tuple | None = None
    _job: object | None = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def available(self) -> tuple[bool, str]:
        if self.binary is None or not self.binary.is_file():
            return False, "Claw's AI engine is missing from this installation."
        return True, ""

    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    async def ensure(self, model_id: str, model_path: Path, mmproj_path: Path | None = None) -> None:
        """Start the engine with this model unless it's already running it."""
        async with self._lock:
            self.last_used = time.monotonic()
            if self.running() and self.status.state == "ready" and self.status.model_id == model_id:
                return
            if self.running():
                await self._stop()
            await self._start(model_id, model_path, mmproj_path)

    async def _start(self, model_id: str, model_path: Path, mmproj_path: Path | None) -> None:
        ok, why = self.available()
        if not ok:
            self.status = EngineStatus("failed", why)
            raise EngineError(why, "Reinstall Claw, or run scripts\\setup.ps1 for a development copy.")
        if not model_path.is_file():
            raise EngineError(f"The model file is missing: {model_path.name}", "Download it again in Settings → Claw's brain.")
        need = memory_needed_gb(model_path.stat().st_size, mmproj_path.stat().st_size if mmproj_path else 0, self.ctx_size)
        hw = detect()
        if hw.available_ram_gb is not None and hw.available_ram_gb + 0.5 < need:
            msg = f"Not enough free memory for this brain: it needs about {need} GB, and {hw.available_ram_gb} GB is free."
            self.status = EngineStatus("failed", msg, model_id)
            raise EngineError(msg, "Close some apps and try again, or choose a smaller brain in Settings.")

        self.port = _free_port()
        self.api_key = secrets.token_urlsafe(24)
        register_secret(self.api_key)
        args = [
            str(self.binary), "-m", str(model_path),
            "--host", "127.0.0.1", "--port", str(self.port), "--api-key", self.api_key,
            "-c", str(self.ctx_size), "-t", str(worker_threads(hw.cpu_cores)),
            "--jinja", "--no-webui", "--parallel", "1",
        ]
        if mmproj_path:
            args += ["--mmproj", str(mmproj_path)]
        self._tail.clear()
        self.status = EngineStatus("starting", "Loading Claw's brain…", model_id, time.time(), self.status.restarts)
        log_event(log, "engine starting", model=model_id, port=self.port, need_gb=need)
        env = dict(os.environ)
        if sys.platform != "win32":  # the engine's shared libraries sit next to it
            env["LD_LIBRARY_PATH"] = os.pathsep.join(filter(None, [str(self.binary.parent), env.get("LD_LIBRARY_PATH")]))
        try:
            self._proc = subprocess.Popen(
                args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                creationflags=_NO_WINDOW, cwd=str(self.binary.parent), env=env,
                preexec_fn=_die_with_parent if sys.platform.startswith("linux") else None,
            )
            if sys.platform == "win32":
                self._job = _windows_kill_on_close(self._proc)
        except OSError as exc:
            self.status = EngineStatus("failed", f"The AI engine could not start: {exc.strerror}", model_id)
            raise EngineError(self.status.message) from exc
        self._launch = (model_id, model_path, mmproj_path)
        self._reader = asyncio.create_task(self._read_output(self._proc))
        await self._wait_ready()

    async def _read_output(self, proc: subprocess.Popen) -> None:
        loop = asyncio.get_running_loop()
        while True:
            line = await loop.run_in_executor(None, proc.stdout.readline)
            if not line:
                return
            self._tail.append(line.decode("utf-8", "replace").rstrip())

    def _crash_reason(self) -> str:
        tail = "\n".join(self._tail)
        if re.search(r"failed to allocate|out of memory|cannot allocate|bad_alloc", tail, re.I):
            return "The computer ran out of memory while loading the brain."
        if re.search(r"failed to load model|invalid magic|gguf_init|unknown model architecture", tail, re.I):
            return "The model file could not be loaded (it may be damaged or not supported)."
        last = [l for l in self._tail if l.strip()][-1:] or ["no output"]
        return f"The AI engine stopped: {last[0][:200]}"

    async def _wait_ready(self) -> None:
        deadline = time.monotonic() + LOAD_TIMEOUT_S
        async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
            while time.monotonic() < deadline:
                if self._proc.poll() is not None:
                    await asyncio.sleep(0.2)  # let the reader collect the last lines
                    msg = self._crash_reason()
                    self.status = EngineStatus("failed", msg, self.status.model_id)
                    log_event(log, "engine failed to start", reason=msg)
                    raise EngineError(msg, "Try a smaller brain in Settings, or restart Claw.")
                try:
                    r = await client.get(f"{self.base_url}/health")
                    if r.status_code == 200:
                        self.status.state, self.status.message = "ready", "Ready"
                        log_event(log, "engine ready", model=self.status.model_id, seconds=round(time.time() - self.status.started_at, 1))
                        return
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.3)
        await self._stop()
        self.status = EngineStatus("failed", f"The brain did not finish loading within {LOAD_TIMEOUT_S // 60} minutes.")
        raise EngineError(self.status.message, "This computer may be too slow for this brain; choose a smaller one.")

    async def check_alive(self) -> bool:
        """Notice a crash after start; restart once automatically."""
        if self.status.state != "ready" or self.running():
            return self.running()
        reason = self._crash_reason()
        log_event(log, "engine crashed", reason=reason)
        self.status = EngineStatus("failed", reason, self.status.model_id, restarts=self.status.restarts)
        if self._launch and self.status.restarts < 2:
            self.status.restarts += 1
            try:
                await self.ensure(*self._launch)
                return True
            except EngineError:
                return False
        return False

    async def stop(self) -> None:
        async with self._lock:
            await self._stop()

    async def _stop(self) -> None:
        proc, self._proc = self._proc, None
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                await asyncio.get_running_loop().run_in_executor(None, proc.wait, 10)
            except subprocess.TimeoutExpired:
                proc.kill()
                await asyncio.get_running_loop().run_in_executor(None, proc.wait, 5)
            log_event(log, "engine stopped", model=self.status.model_id)
        if self._reader:
            self._reader.cancel()
            self._reader = None
        self.status = EngineStatus("stopped", "", None, restarts=self.status.restarts)

    async def stop_if_idle(self, idle_s: float) -> bool:
        if self.running() and time.monotonic() - self.last_used > idle_s:
            await self.stop()
            return True
        return False

    def stop_now(self) -> None:
        """Synchronous last-resort stop (process exit)."""
        if self._proc is not None and self._proc.poll() is None:
            self._proc.kill()
