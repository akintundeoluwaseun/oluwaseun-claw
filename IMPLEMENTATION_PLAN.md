# Implementation plan

## Batch 1 — Audit, architecture, foundation ✅ (workspace-verified; Windows run pending)
Done: repo audit, architecture decision, backend (config, health, model adapters,
planner, permissions, SQLite, logging), Electron shell + UI, scripts, tests.

## Batch 2 — Local AI and browser automation
1. **First:** run `scripts\setup.ps1` + `scripts\check.ps1` on Windows 10 with real Ollama; record results.
2. Measure planning time/RAM for qwen2.5:7b, qwen2.5:3b, qwen3:8b on real hardware → `docs/MODELS.md`.
3. Tool registry (`claw/tools/`): name, JSON schema, risk level, executor; arguments validated before use.
4. Executor loop: one step at a time, model chooses a registered tool + args per step, state recorded.
5. Playwright (Chromium) in a dedicated profile under the data dir: open, navigate, tabs, read page, extract links.
6. Web search via the browser (search engine results page), result collection, save links to an authorized folder.
7. History search: read-only copy of the Chrome/Edge `History` SQLite for the time range asked, behind an explicit per-task permission; no cookies, passwords, or other profile data.
8. Approval dialog (UI) for `ask` steps; cancel button; per-step timeout; bounded retries.
9. Local test website for automated browser tests.

Evaluate browser-use against the direct Playwright tools with real local models before adopting it.

## Batch 3 — Desktop control
pywinauto (UIA backend) for windows/controls; screenshots (mss or PIL); pyautogui only as a
coordinate fallback; folder picker; file inspection tool; global stop hotkey; click verification.

## Batch 4 — Multi-step autonomy
Replanning, verification after key actions, searchable logs, file/doc/spreadsheet tools,
untrusted-content isolation, recovery after backend restart, multi-step task tests.

## Batch 5 — Security, packaging, release
Dependency/model license audit, IPC review, path/overwrite safeguards, PyInstaller-built backend
bundled with electron-builder NSIS installer, clean-VM install test, manuals, release checklist.
