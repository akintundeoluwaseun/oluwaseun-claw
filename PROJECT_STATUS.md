# Project status — Oluwaseun Claw

**Current stage:** v0.5.0: scanned-document reading (OCR) and the built-in llama.cpp engine, with
Ollama removed as a requirement. Done and tested in the build workspace (Linux).
**Batch 5 (part 1) done:** full tests, security review, dependency audit, user guide, developer
guide, known issues, release checklist. **Not done, by request:** building and installing.
**v0.6 (master prompt 2):** audit done (`docs/AUDIT_V06.md`); **Phase A done** (Windows control
hardening, Notepad Test A logic, browser forms and downloads, file copies); **Phase B done** (WhatsApp
unread check, notifications, send with approval); **Phase C done** (TechDesk sale through its screen). Next:
**Phase D — image editing**, then E video,
F calendar apps on the PC, G packaging and security.
**Version:** 0.5.0 · **Last updated:** 2026-10-26

## Completed
- **Batches 1–4:** foundation, browser control, desktop control, multi-step autonomy (see CHANGELOG).
- **Interface + background mode:** premium design, quick bar, tray, notifications.
- **Scanned documents (v0.5):** Documents view, text-vs-scan detection per page, Tesseract OCR with
  confidence, auto-rotation, problem-page flags, search, ask Claw, searchable PDF copies, OCR cache,
  page-aware chunks with page citations, agent tools (`read_document_pages`, `search_document`,
  `summarize_document`, `make_searchable_pdf`). OCR works without the brain.
- **Built-in engine (v0.5):** llama.cpp `llama-server` managed by Claw (start/stop, memory check,
  load wait, crash restart, idle unload, localhost + per-launch key, dies with the backend).
  Standard (Qwen3-VL 4B) and Pro (Qwen3-VL 8B) brains with licence/size/checksum-checked
  download, import of your own GGUF, remove with confirmation. **Ollama is no longer needed**;
  it stays only as an optional developer adapter.
- **Packaging pipeline (v0.5, partly verified):** PyInstaller-frozen backend, electron-builder
  layout, Inno Setup script for the two editions, `build-release.ps1`, `setup.ps1` that fetches
  llama.cpp and Tesseract. The frozen backend and the packaged layout were tested on Linux;
  the Windows scripts and installers have not been run.

## What the app can do today
Everything from Batch 4, plus: open a PDF (text or scanned), Word, Excel or text file; see each
page's text with where it came from and how sure Claw is; search it; ask Claw about it; save a
searchable copy of a scanned PDF; and run with its own engine and brain — no Ollama, no keys.

## Known issues / limits
- **Never run on Windows, and never with the real Qwen3-VL weights.** All engine runs used a tiny
  random test model; how well a 4B/8B local brain follows the action format is the biggest open risk.
- Windows-only code untested: job object (engine killed with backend), UI Automation driver,
  setup.ps1 downloads, build-release.ps1, Inno Setup installers.
- The Pro installer is `Setup.exe` + `.bin` parts (Inno Setup's single-file limit is ~4.2 GB).
- OCR tested on synthetic pages only; English only (more language packs are possible later).
- Handwriting, tables and multi-column layouts are read as plain text, not structured.
- Injection detection is pattern-based; the real protection is that changes need approval.
- Desktop steps can't run on a locked screen; "Plan only" can't be cancelled; one task at a time.
- Not code-signed (Windows SmartScreen will warn) until a certificate is available.

## Exact startup commands (Windows 10/11, developers)
```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1        # once: Python env, Electron, llama.cpp, Tesseract
powershell -ExecutionPolicy Bypass -File scripts\start.ps1
# then in the app: Settings > Claw's brain > Download (once)
powershell -ExecutionPolicy Bypass -File scripts\build-release.ps1 -Edition Standard   # installer
```

## Guides
`docs/WINDOWS_ACCEPTANCE.md` · `docs/USER_GUIDE.md` · `docs/DEVELOPER_GUIDE.md` · `docs/KNOWN_ISSUES.md` · `docs/RELEASE_CHECKLIST.md`

## Next action
Run `setup.ps1`, the app and `build-release.ps1 -Edition Standard` on a Windows 10 PC; install
the result on a clean Windows 10 machine and go through `docs/DESKTOP.md` and the Batch 5 checklist.
