# Installation and development guide (Windows 10, 64-bit)

## 1. Install prerequisites (developers)
1. **Python 3.12 (64-bit)** — https://www.python.org/downloads/ (tick "Add python.exe to PATH").
2. **Node.js 22 LTS** — https://nodejs.org

End users will get a single installer in Batch 5; nothing else to install for Online mode.

## 2. Brain
Nothing to do here. On first launch Claw asks Online or Offline (see `docs/MODELS.md`).
Online needs a free Google AI key; Offline currently also needs the free Ollama engine.

## 3. Set up the project
From the project folder:
```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```
This creates `backend\.venv`, installs the pinned Python packages, and
installs Electron into `desktop\node_modules`.

## 4. Run
```powershell
powershell -ExecutionPolicy Bypass -File scripts\start.ps1
```
The window opens, starts the backend automatically, and shows two status
pills: **Agent** and **Model**. Open **Settings**, click **Test connection**,
connect a brain on the welcome screen, then in Settings add a folder under **Folders Claw may
use** (needed for saving and reading files). Type a task and press **Start task**, or press
**Ctrl+Shift+Space** anywhere to use the quick bar. **Ctrl+Alt+X** stops a running task.

The agent controls Microsoft Edge by default, in its own separate profile. To use
Chromium instead, run `scripts\setup.ps1 -Chromium` and choose it in Settings.

## 5. Run the checks
```powershell
powershell -ExecutionPolicy Bypass -File scripts\check.ps1
```

## Useful settings
- `CLAW_PYTHON` — full path to a Python to use instead of `backend\.venv`.
- `CLAW_BROWSER_EXECUTABLE` — full path to a Chromium-family browser to control (testing).
- `CLAW_DATA_DIR` — where settings, history (`claw.db`) and logs live.
  Default: `%APPDATA%\OluwaseunClaw`.
- Logs: `%APPDATA%\OluwaseunClaw\logs\claw.log`.

## Running the backend alone (debugging)
```powershell
cd backend
.\.venv\Scripts\python.exe -m claw.main --port 8765
```
A development token is printed once; send it as the `X-Claw-Token` header.

## Troubleshooting
| What you see | What to do |
|---|---|
| "Python was not found" | Install Python 3.12 and rerun setup, or set `CLAW_PYTHON`. |
| "Google did not accept this AI key" | Create a new key at aistudio.google.com/apikey and connect it in Settings. |
| "Today's free Google AI limit has been reached" | Wait until about 8–9 AM Lagos time, or switch to Offline. |
| "The offline brain needs its engine" | Install Ollama from ollama.com; Claw downloads the model itself. |
| "Windows is locked" | Desktop steps need an unlocked screen; browser steps still run. |
| "Some settings are not valid" | Open Settings and correct the listed fields, or delete `settings.json` in the data folder. |
| Planning times out | Use a smaller model or raise the timeout in Settings. |
| "Microsoft Edge was not found" | Choose Chrome or Chromium in Settings (Chromium needs `setup.ps1 -Chromium`). |
| "browser profile is already open" | Close the agent's browser window and run the task again. |
| "Step limit reached" | Raise "Most steps per task" in Settings, or split the task. |
| Search finds nothing | Try the other search engine in Settings. |
