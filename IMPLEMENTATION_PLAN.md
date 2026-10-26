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

## Batch 3 — Desktop control ✅ (logic tested on a stand-in desktop; Windows driver not yet run)
Done: UI Automation driver (pywinauto), launcher, 12 desktop tools, 3 file tools, screenshots
(mss, real capture tested), screen reading through the brain, risk escalation, stop shortcut.
pyautogui not used: pywinauto's mouse/keyboard cover the fallback, one fewer dependency.
Also done in this stage at the user's request: premium redesign, quick bar, tray, notifications,
background mode, Online/Offline brain with automatic model choice.
Carried over: run docs/DESKTOP.md checklist on Windows 10.

## Batch 4 — Multi-step autonomy ✅ (scripted model; real browser, files, app)
Done: re-planning, document readers/writers, spreadsheet provenance, edit with backup, taint +
injection guard, crash auto-restart, run again, files card, wider history search. Online
mode removed at the user's request. Task history, settings, permissions, progress and
cancellation already existed from Batches 1–2.

### (original Batch 4 notes)
Replanning, verification after key actions, searchable logs, file/doc/spreadsheet tools,
untrusted-content isolation, recovery after backend restart, multi-step task tests.

## Batch 5 — Security, packaging, release
Decided with the user: **the brain ships inside the installer**; no keys, no downloads.
1. Bundle llama.cpp `llama-server` (Windows x64 builds: CPU AVX2, and CUDA/Vulkan if feasible) and
   start it from the backend on 127.0.0.1 with a random port; replace the Ollama dependency.
2. Choose model files whose licence allows redistribution; decide installer sizes (per-size
   installers or one large installer). Measure speed/memory on real 8 GB and 16 GB laptops.
3. Package the Python backend (embedded Python or PyInstaller) and Electron with electron-builder
   (NSIS). Test install, upgrade, uninstall, settings persistence on a clean Windows 10.
4. Full dependency licence scan; notices in the installer. Code signing if a certificate exists.
5. Manuals (user, developer, limitations), release checklist, known defects.
