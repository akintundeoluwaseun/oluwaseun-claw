# Installation and development guide (Windows 10, 64-bit)

## 1. Install prerequisites
1. **Python 3.12 (64-bit)** — https://www.python.org/downloads/ (tick "Add python.exe to PATH").
2. **Node.js 22 LTS** — https://nodejs.org
3. **Ollama** — https://ollama.com/download (starts automatically in the system tray).

## 2. Get a model
```powershell
ollama pull qwen2.5:7b
```
See `docs/MODELS.md` for smaller options.

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
choose your model, and **Save settings**.

## 5. Run the checks
```powershell
powershell -ExecutionPolicy Bypass -File scripts\check.ps1
```

## Useful settings
- `CLAW_PYTHON` — full path to a Python to use instead of `backend\.venv`.
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
| "Model server offline" | Start the Ollama app (or `ollama serve`). |
| "Model missing: …" | `ollama pull <name>`, then Test connection in Settings. |
| "Some settings are not valid" | Open Settings and correct the listed fields, or delete `settings.json` in the data folder. |
| Planning times out | Use a smaller model or raise the timeout in Settings. |
