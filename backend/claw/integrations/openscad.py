"""OpenSCAD: a dimensioned part, rendered to STL and measured.

OpenSCAD is free, scriptable and headless, which makes it the one CAD package
S-CLAW can both drive and PROVE on any machine. The script is generated here
from numbers, never from text the brain wrote, so a request cannot inject
OpenSCAD code; and the result is checked by measuring the STL that came out,
not by trusting the script that went in.
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path


def binary() -> str | None:
    """OpenSCAD, if this computer has it."""
    return os.environ.get("CLAW_OPENSCAD") or shutil.which("openscad")


def bounding_box(stl: Path) -> tuple[float, float, float] | None:
    """The part's size in mm, read back out of the STL it exported.

    Independent of the script: whatever OpenSCAD actually produced is what
    gets measured. Handles both the ASCII form OpenSCAD writes and the binary
    form other tools do.
    """
    data = stl.read_bytes()
    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []
    if data[:5] == b"solid" and b"facet normal" in data[:2048]:
        for line in data.decode("utf-8", "replace").splitlines():
            parts = line.split()
            if len(parts) == 4 and parts[0] == "vertex":
                try:
                    x, y, z = (float(p) for p in parts[1:])
                except ValueError:
                    continue
                xs.append(x); ys.append(y); zs.append(z)
    else:
        count = struct.unpack("<I", data[80:84])[0]
        for i in range(count):
            off = 84 + i * 50 + 12          # skip the normal
            for v in range(3):
                x, y, z = struct.unpack("<fff", data[off + v * 12:off + v * 12 + 12])
                xs.append(x); ys.append(y); zs.append(z)
    if not xs:
        return None
    return (round(max(xs) - min(xs), 3), round(max(ys) - min(ys), 3), round(max(zs) - min(zs), 3))


def render(script: str, out: Path, timeout: int = 180) -> None:
    """Run OpenSCAD on a generated script and write `out` (.stl or .png)."""
    exe = binary()
    if not exe:
        raise RuntimeError("OpenSCAD is not installed")
    with tempfile.TemporaryDirectory() as tmp:
        scad = Path(tmp) / "part.scad"
        scad.write_text(script, encoding="utf-8")
        proc = subprocess.run([exe, "-o", str(out), str(scad)],
                              capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        raise RuntimeError(detail[-1][:200] if detail else "OpenSCAD produced nothing")
