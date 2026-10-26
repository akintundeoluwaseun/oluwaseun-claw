# Project status — Oluwaseun Claw

**Current batch:** Batch 4 complete in the build workspace (Linux, scripted model).
**Next batch:** Batch 5 — security, packaging (brain inside the installer), release.
**Version:** 0.4.0 · **Last updated:** 2026-10-26

## Completed
- **Batch 1:** audit, architecture, backend foundation, Electron shell, scripts, tests.
- **Batch 2:** tool system, browser control, history search, save links, executor with
  approvals/stop/limits, background runner.
- **Interface + background mode:** premium redesign, quick bar (Ctrl+Shift+Space), tray,
  notifications, start with Windows, keep awake, close to tray.
- **Batch 3:** Windows UI Automation desktop control, app launcher, screenshots, screen reading,
  file inspection, consequential-label escalation, stop shortcut Ctrl+Alt+X.
- **Batch 4:** re-planning after failures; read PDF/Word/Excel; write text, reports with opened
  sources only, spreadsheets with value checks, edits with backups; injection guard and taint
  escalation; crash auto-restart; files card with Open/Show in folder; Run again; wider search.
- **Brain:** built-in only, sized to the computer; no keys, no model choice (online mode removed).

## What the app can do today
Take a task (main window or quick bar), plan it, and carry it out across the browser, Windows
apps and files in allowed folders: research and save a sourced report, turn a web page into a
spreadsheet, summarise the newest PDF, edit a text file safely. It asks before changes, recovers
from failures by re-planning, flags hidden instructions in pages, and reports exactly what was
done, checked and produced.

## Remaining work
Batch 5 (see `IMPLEMENTATION_PLAN.md`): bundle engine + brain into a Windows installer, licence
audit, clean-machine install tests, manuals.

## Known issues / limits
- **Not yet run on Windows 10 and never driven by a real model** — all task runs used scripted
  stand-ins. How well a small local model follows the action format is the biggest open risk.
- Development builds still need Ollama; release builds will bundle llama.cpp (Batch 5).
- Windows UI Automation driver unexecuted (checklist in `docs/DESKTOP.md`).
- Scanned PDFs (images only) can't be read; no OCR.
- Spreadsheet checks catch values not seen in the text; they can't catch a real value put in the
  wrong row.
- Injection detection is pattern-based; the real protection is that changes need approval.
- Desktop steps can't run on a locked screen; "Plan only" can't be cancelled; one task at a time.

## Exact startup commands (Windows 10, developers)
```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1   # once
# install Ollama (development builds only)
powershell -ExecutionPolicy Bypass -File scripts\start.ps1
```

## Next action
Batch 5, step 1: replace the Ollama dependency with a bundled llama.cpp `llama-server` started
by the backend, then build the Windows installer.
