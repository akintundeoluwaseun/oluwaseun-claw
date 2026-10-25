"""Measure this computer so Claw can choose models that fit without slowing it down."""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass


@dataclass
class Hardware:
    total_ram_gb: float | None
    available_ram_gb: float | None
    cpu_cores: int
    gpu_name: str | None
    gpu_vram_gb: float | None

    def as_dict(self) -> dict:
        return asdict(self)

    def describe(self) -> str:
        parts = []
        if self.total_ram_gb:
            parts.append(f"{self.total_ram_gb:.0f} GB memory")
        parts.append(f"{self.cpu_cores} processor cores")
        if self.gpu_name:
            parts.append(f"{self.gpu_name} ({self.gpu_vram_gb:.0f} GB)" if self.gpu_vram_gb else self.gpu_name)
        return ", ".join(parts)


def _ram_windows() -> tuple[float, float] | None:
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):  # type: ignore[attr-defined]
        return None
    return stat.ullTotalPhys / 1024**3, stat.ullAvailPhys / 1024**3


def _ram_linux() -> tuple[float, float] | None:
    try:
        info = {}
        with open("/proc/meminfo", encoding="ascii") as fh:
            for line in fh:
                key, _, rest = line.partition(":")
                info[key] = int(rest.split()[0]) * 1024
        return info["MemTotal"] / 1024**3, info.get("MemAvailable", info["MemFree"]) / 1024**3
    except (OSError, KeyError, ValueError):
        return None


def _nvidia() -> tuple[str, float] | None:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    best = None
    for line in out.stdout.strip().splitlines():
        try:
            name, mem = [p.strip() for p in line.rsplit(",", 1)]
            gb = float(mem) / 1024
        except ValueError:
            continue
        if best is None or gb > best[1]:
            best = (name, gb)
    return best


def detect() -> Hardware:
    ram = None
    try:
        ram = _ram_windows() if sys.platform == "win32" else _ram_linux()
    except Exception:  # noqa: BLE001 — detection must never crash startup
        ram = None
    gpu = None
    try:
        gpu = _nvidia()
    except Exception:  # noqa: BLE001
        gpu = None
    return Hardware(
        total_ram_gb=round(ram[0], 1) if ram else None,
        available_ram_gb=round(ram[1], 1) if ram else None,
        cpu_cores=os.cpu_count() or 2,
        gpu_name=gpu[0] if gpu else None,
        gpu_vram_gb=round(gpu[1], 1) if gpu else None,
    )


def worker_threads(cores: int) -> int:
    """Leave cores free for the user so the computer stays responsive."""
    if cores <= 2:
        return 1
    if cores <= 4:
        return cores - 1
    return cores - 2
