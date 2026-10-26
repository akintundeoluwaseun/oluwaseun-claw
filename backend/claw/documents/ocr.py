"""OCR engines. Tesseract (Apache-2.0) is the default and runs as a separate
process, so a crash or hang in OCR can't take the agent down with it.

Engine lookup order: CLAW_TESSERACT environment variable → Tesseract bundled
with the app (resources/tesseract) → Tesseract on PATH. Language data comes
from the bundled tessdata folder when present, so more languages can be added
later by dropping in <lang>.traineddata files.
"""

from __future__ import annotations

import csv
import io
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from claw.tools.base import ToolError

APP_ROOT = Path(__file__).resolve().parents[3]  # repository / installed app root
OCR_TIMEOUT_S = 180
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass
class PageOcr:
    text: str
    confidence: float | None  # mean word confidence 0–100, None if no words
    words: int
    rotation: int = 0  # degrees the page image was turned before recognition
    notes: list[str] = field(default_factory=list)


class OcrUnavailable(ToolError):
    pass


def _bundled_dirs() -> list[Path]:
    dirs = []
    if os.environ.get("CLAW_RESOURCES"):
        dirs.append(Path(os.environ["CLAW_RESOURCES"]) / "tesseract")
    dirs += [APP_ROOT / "resources" / "tesseract", APP_ROOT / "backend" / "runtime" / "tesseract"]
    return dirs


class TesseractEngine:
    name = "tesseract"

    def __init__(self, exe: str | None = None, tessdata: str | None = None):
        # exe=None: look for Tesseract; exe="": explicitly no engine (used to test the missing case)
        self.exe = self._find_exe() if exe is None else (exe or None)
        self.tessdata = tessdata or self._find_tessdata()

    @staticmethod
    def _find_exe() -> str | None:
        if os.environ.get("CLAW_TESSERACT"):
            return os.environ["CLAW_TESSERACT"]
        name = "tesseract.exe" if sys.platform == "win32" else "tesseract"
        for d in _bundled_dirs():
            if (d / name).is_file():
                return str(d / name)
        found = shutil.which("tesseract")
        if found:
            return found
        if sys.platform == "win32":  # developer machines: the UB Mannheim installer's default folders
            local = os.environ.get("LOCALAPPDATA")
            for base in filter(None, (os.environ.get("ProgramFiles"), local and os.path.join(local, "Programs"))):
                p = os.path.join(base, "Tesseract-OCR", name)
                if os.path.isfile(p):
                    return p
        return None

    @staticmethod
    def _find_tessdata() -> str | None:
        for d in _bundled_dirs():
            if (d / "tessdata").is_dir():
                return str(d / "tessdata")
        return None  # Tesseract's own default location

    def _env(self) -> dict:
        env = {k: v for k, v in os.environ.items() if k.upper() in ("PATH", "SYSTEMROOT", "TEMP", "TMP", "HOME", "USERPROFILE", "LANG", "LC_ALL")}
        if self.tessdata:
            env["TESSDATA_PREFIX"] = self.tessdata
        env["OMP_THREAD_LIMIT"] = "1"  # one OCR process = one core; keeps the computer responsive
        return env

    def _run(self, args: list[str], timeout: float = OCR_TIMEOUT_S) -> str:
        if not self.exe:
            raise OcrUnavailable("The OCR engine (Tesseract) is not installed with Claw.")
        try:
            out = subprocess.run(
                [self.exe, *args], capture_output=True, timeout=timeout, env=self._env(),
                creationflags=_NO_WINDOW, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ToolError(f"Reading this page took longer than {int(timeout)} seconds.", transient=False) from exc
        except OSError as exc:
            raise OcrUnavailable(f"The OCR engine could not start: {exc.strerror}") from exc
        if out.returncode != 0:
            msg = out.stderr.decode("utf-8", "replace").strip().splitlines()
            raise ToolError("OCR failed: " + (msg[-1] if msg else f"exit code {out.returncode}"))
        return out.stdout.decode("utf-8", "replace")

    def languages(self) -> list[str]:
        try:
            out = self._run(["--list-langs"], timeout=20)
        except ToolError:
            return []
        return [l.strip() for l in out.splitlines()[1:] if l.strip() and l.strip() != "osd"]

    def available(self, lang: str = "eng") -> tuple[bool, str]:
        if not self.exe:
            return False, "The OCR engine (Tesseract) is not installed with Claw."
        langs = self.languages()
        if not langs:
            return False, "The OCR engine is installed but could not be started."
        missing = [l for l in lang.split("+") if l not in langs]
        if missing:
            return False, f"OCR language data missing: {', '.join(missing)}. Installed: {', '.join(langs)}."
        if self.tessdata and not (Path(self.tessdata) / "configs" / "tsv").is_file():
            # Without tessdata/configs Tesseract silently writes plain text instead of TSV.
            return False, "The OCR engine's data files are incomplete (tessdata/configs is missing). Reinstall Claw."
        return True, ""

    def has_osd(self) -> bool:
        try:
            return "osd" in self._run(["--list-langs"], timeout=20).split()
        except ToolError:
            return False

    def detect_rotation(self, image: Path) -> int:
        """Degrees to rotate the image clockwise so text is upright (0 if unknown)."""
        try:
            out = self._run([str(image), "stdout", "--psm", "0"], timeout=60)
        except ToolError:
            return 0
        m = re.search(r"Rotate:\s*(\d+)", out)
        return int(m.group(1)) % 360 if m else 0

    def recognize(self, image: Path, lang: str = "eng") -> PageOcr:
        tsv = self._run([str(image), "stdout", "-l", lang, "--psm", "3", "tsv"])
        if tsv.strip() and not tsv.lstrip().startswith("level\t"):
            # Never present output we could not interpret as "no text found".
            raise ToolError("The OCR engine answered in an unexpected format (its data files may be incomplete).")
        return parse_tsv(tsv)

    def searchable_pdf(self, image: Path, out_base: Path, lang: str = "eng") -> Path:
        """One-page PDF: the page image with an invisible, selectable text layer."""
        self._run([str(image), str(out_base), "-l", lang, "--psm", "3", "pdf"])
        return out_base.with_suffix(".pdf")


def parse_tsv(tsv: str) -> PageOcr:
    """Rebuild text from Tesseract TSV, keeping paragraphs and line breaks."""
    rows = list(csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE))
    lines: dict[tuple, list[str]] = {}
    order: list[tuple] = []
    confs: list[float] = []
    for r in rows:
        try:
            if r.get("level") != "5":
                continue
            word = (r.get("text") or "").strip()
            conf = float(r.get("conf") or -1)
        except (TypeError, ValueError):
            continue
        if not word:
            continue
        key = (int(r["block_num"]), int(r["par_num"]), int(r["line_num"]))
        if key not in lines:
            lines[key] = []
            order.append(key)
        lines[key].append(word)
        if conf >= 0:
            confs.append(conf)
    out, prev = [], None
    for key in order:
        if prev is not None and key[:2] != prev[:2]:
            out.append("")  # blank line between paragraphs
        out.append(" ".join(lines[key]))
        prev = key
    return PageOcr(
        text="\n".join(out).strip(),
        confidence=round(sum(confs) / len(confs), 1) if confs else None,
        words=len(confs),
    )


def default_engine() -> TesseractEngine:
    return TesseractEngine()
