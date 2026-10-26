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

## v0.5 — Scanned documents + built-in engine (remove Ollama) ✅ (Linux-verified; Windows pending)
Done: (A) repo/licence review of OCRmyPDF, Tesseract, PaddleOCR, PDF-OCR, llama.cpp, DynaLM;
(B) OCR pipeline + Documents UI + 7 test cases; (C) llama.cpp engine manager, Standard/Pro
catalogue, Hugging Face download with licence/disk/checksum checks, import/remove, brain manager
UI; (D) agent document tools with page citations; (E) security review of new paths, licence scan,
packaging pipeline; (F) all tests, frozen-backend and packaged-app tests, Ollama-absent runs;
(G) records updated.

## Batch 5 — Security, packaging, release (remaining)
Decided with the user: two installers, **Standard** and **Pro**, each with the brain inside.
1. ~~Bundle llama.cpp and replace Ollama~~ ✅ (v0.5).
2. ~~Choose brains whose licence allows redistribution~~ ✅ Qwen3-VL 4B/8B (Apache-2.0); still to do:
   measure speed/memory on real 8 GB and 16 GB laptops and confirm the 4B follows the action format.
3. Package (PyInstaller + electron-builder + Inno Setup) — written and Linux-checked ✅; still to do:
   run `build-release.ps1` on Windows, install/upgrade/uninstall on a clean Windows 10, check that
   settings and downloaded brains survive an upgrade, and SmartScreen/Defender behaviour.
4. ~~Licence scan~~ ✅ (THIRD_PARTY_NOTICES.md); still to do: list the DLLs in the Windows Tesseract
   and llama.cpp builds and copy their notices; code signing if a certificate exists.
5. ~~Manuals (user, developer, limitations), release checklist, known defects~~ ✅ (docs/USER_GUIDE, DEVELOPER_GUIDE, KNOWN_ISSUES, RELEASE_CHECKLIST).
6. Security review ✅ (static scan, pip-audit, npm audit); repeat on the Windows build.
