"""Freeze the backend into one folder (PyInstaller) so the installed app needs no Python.

    python packaging/build_backend.py [--out DIR]

Produces DIR/claw-backend/claw-backend(.exe). Run on Windows to get the Windows build
(PyInstaller does not cross-compile).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import PyInstaller.__main__

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(BACKEND / "dist"))
    args = ap.parse_args()
    out = Path(args.out)
    PyInstaller.__main__.run([
        "--noconfirm", "--clean", "--onedir", "--name", "claw-backend",
        "--distpath", str(out), "--workpath", str(out / "_build"), "--specpath", str(out / "_build"),
        "--paths", str(BACKEND),
        "--collect-submodules", "claw",
        "--collect-all", "playwright", "--collect-all", "pypdfium2", "--collect-all", "pypdfium2_raw",
        "--collect-data", "docx", "--collect-data", "openpyxl",
        *[x for m in ("uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto",
                      "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on") for x in ("--hidden-import", m)],
        # Windows desktop control: pywinauto + comtypes (COM) + pywin32 pieces loaded at run time.
        *(["--collect-submodules", "pywinauto", "--collect-submodules", "comtypes", "--hidden-import", "win32timezone",
           "--hidden-import", "win32job", "--hidden-import", "win32com.client"] if sys.platform == "win32" else []),
        *(["--console"] if sys.platform != "win32" else ["--noconsole"]),
        str(HERE / "entry.py"),
    ])
    exe = out / "claw-backend" / ("claw-backend.exe" if sys.platform == "win32" else "claw-backend")
    print(f"built {exe}" if exe.is_file() else "build failed: no executable")
    return 0 if exe.is_file() else 1


if __name__ == "__main__":
    raise SystemExit(main())
