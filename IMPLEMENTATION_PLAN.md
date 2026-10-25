# Implementation plan

## Batch 1 — Audit, architecture, foundation ✅ (workspace-verified; Windows run pending)
Done: repo audit, architecture decision, backend (config, health, model adapters,
planner, permissions, SQLite, logging), Electron shell + UI, scripts, tests.

## Batch 2 — Local AI and browser automation ✅ (workspace-verified with scripted model)
Done: tool registry, Playwright browser tools, history search, save_links, executor loop,
background runner with approvals/stop, UI for running tasks, local test website, tests.
Carried over to verification on Windows: real model, Edge channel, live search engines,
Chrome/Edge history files. browser-use was not adopted: the direct Playwright tools cover the
acceptance tasks and keep every action inside the permission system.

## Batch 3 — Desktop control
0. **First:** Windows verification of Batches 1–2 with a real model (see PROJECT_STATUS.md).
pywinauto (UIA backend) for windows/controls; screenshots (mss or PIL); pyautogui only as a
coordinate fallback; folder picker; file inspection tool; global stop hotkey; click verification.

## Batch 4 — Multi-step autonomy
Replanning, verification after key actions, searchable logs, file/doc/spreadsheet tools,
untrusted-content isolation, recovery after backend restart, multi-step task tests.

## Batch 5 — Security, packaging, release
Dependency/model license audit, IPC review, path/overwrite safeguards, PyInstaller-built backend
bundled with electron-builder NSIS installer, clean-VM install test, manuals, release checklist.
