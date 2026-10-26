# Installation and development guide (Windows 10/11, 64-bit)

## For users
Run `OluwaseunClaw-<version>-Standard-Setup.exe` (or the Pro one, keeping its `.bin` parts in the
same folder). Everything Claw needs is inside: the app, its AI engine, OCR and the brain.
No Python, Node.js, Ollama, account or key. *(Installer pipeline written; not yet built or run
on Windows — see `PROJECT_STATUS.md`.)*

## For developers
### 1. Prerequisites
1. **Python 3.12 (64-bit)** — https://www.python.org/downloads/ (tick "Add python.exe to PATH").
2. **Node.js 22 LTS** — https://nodejs.org
3. `winget` (built into current Windows 10/11) — used to install Tesseract OCR.

### 2. Set up
```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```
This creates `backend\.venv` with the pinned packages, installs Electron, downloads the newest
official **llama.cpp** Windows build into `backend\runtime\llama`, and installs **Tesseract OCR**
(UB Mannheim build) with winget. Options: `-Gpu vulkan` or `-Gpu cuda` for a GPU build of
llama.cpp, `-SkipEngine`, `-SkipOcr`, `-Chromium`.

### 3. Run
```powershell
powershell -ExecutionPolicy Bypass -File scripts\start.ps1
```
On first run, Claw shows **Give Claw a brain**: press **Download** (the size is on the button), or
**Use a GGUF file I have**. Add a folder under **Settings → Folders Claw may use** so Claw can save
files. Press **Ctrl+Shift+Space** anywhere for the quick bar; **Ctrl+Alt+X** stops a task.

**Documents** (left sidebar): open a PDF, Word, Excel or text file. Scanned pages are read with
OCR on this computer; each page shows where its text came from and how sure Claw is. Search,
ask Claw about it, or save a searchable copy of a scanned PDF.

### 4. Checks
```powershell
powershell -ExecutionPolicy Bypass -File scripts\check.ps1
```

### 5. Build the installers
```powershell
winget install JRSoftware.InnoSetup
powershell -ExecutionPolicy Bypass -File scripts\build-release.ps1 -Edition Standard
powershell -ExecutionPolicy Bypass -File scripts\build-release.ps1 -Edition Pro
```
Download the edition's brain once in Claw first (or pass `-ModelDir`). The script freezes the
backend with PyInstaller, copies the engine, Tesseract (English + orientation data only) and the
brain, packages the app with electron-builder, makes the installer with Inno Setup and writes
`build\installers\SHA256SUMS.txt`. It refuses to bundle a brain that was not checksum-verified or
whose licence is not Apache-2.0/MIT.

## Useful environment variables
- `CLAW_DATA_DIR` — settings, history (`claw.db`), downloaded brains, OCR cache and logs.
  Default `%APPDATA%\OluwaseunClaw`.
- `CLAW_LLAMA_SERVER` — full path to a `llama-server.exe` to use.
- `CLAW_TESSERACT` — full path to a `tesseract.exe` to use.
- `CLAW_RESOURCES` — the installed app's resources folder (set by the app itself).
- `CLAW_PYTHON` — a Python to use instead of `backend\.venv` (development).
- `CLAW_BROWSER_EXECUTABLE` — a Chromium-family browser to control (testing).

## Running the backend alone (debugging)
```powershell
cd backend
.\.venv\Scripts\python.exe -m claw.main --port 8765
```
A development token is printed once; send it as the `X-Claw-Token` header.

## Troubleshooting
| What you see | What to do |
|---|---|
| "Claw's AI engine is missing" | Reinstall Claw. Developers: run `scripts\setup.ps1` (or set `CLAW_LLAMA_SERVER`). |
| "Not enough free memory for this brain" | Close some apps, or choose the Standard brain. |
| "The model file could not be loaded" | The file is damaged or not supported: remove it and download again. |
| "The brain did not finish loading within 5 minutes" | The computer is too slow for this brain; choose the Standard brain. |
| "The OCR engine (Tesseract) is not installed" | Reinstall Claw. Developers: `winget install UB-Mannheim.TesseractOCR`. |
| A page says "unclear scan" | Check that page yourself; the text there may be wrong. |
| "This PDF is password-protected" | Open it in your PDF reader, save an unprotected copy, open that. |
| "Python was not found" | Development only: install Python 3.12 and rerun setup, or set `CLAW_PYTHON`. |
| "Windows is locked" | Desktop steps need an unlocked screen; browser steps still run. |
| "Some settings are not valid" | Open Settings and correct the listed fields, or delete `settings.json`. |
| "Microsoft Edge was not found" | Choose Chrome or Chromium in Settings (Chromium needs `setup.ps1 -Chromium`). |
| "Step limit reached" | Raise "Most steps per task" in Settings, or split the task. |
