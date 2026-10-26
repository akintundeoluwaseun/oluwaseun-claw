# Audit for the v0.6 master prompt (26 Oct 2026)

Audit of the real codebase at commit `a791e9d` (GitHub `akintundeoluwaseun/oluwaseun-claw`, `main`).

## Stack (kept — no reason to change)
| Part | Choice |
|---|---|
| UI | Electron 45, sandboxed renderer, vanilla JS, quick bar + tray |
| Backend | Python 3.12, FastAPI on 127.0.0.1, Pydantic, SQLite |
| Agent | own planner + executor (structured JSON tool calls, validated locally), no framework |
| AI | llama.cpp `llama-server` managed by Claw; Qwen3-VL 4B/8B GGUF; Ollama optional adapter only |
| Browser | Playwright (Edge/Chrome/Chromium, own profile) |
| Desktop | pywinauto (UI Automation), mss screenshots, vision through the brain |
| Documents | pypdfium2, pypdf, Tesseract, python-docx, openpyxl |
| Packaging | PyInstaller + electron-builder + Inno Setup (written, not yet built) |
| Windows | 10 and 11, x64 (nothing Windows-version-specific used; untested on both) |

**Ollama references:** only the optional developer adapter (`models/ollama.py`, `models/registry.py`,
`config.py` provider list, a Settings dropdown option). No startup script, port or default needs it.

## Feature matrix
Status key: **WT** = working and tested · **IU** = implemented but untested on Windows (logic tested
with stand-ins) · **INC** = incomplete · **NI** = not implemented.

| Capability | Status | Notes |
|---|---|---|
| Task input, plan, timeline, approvals, history, stop, notifications, tray, quick bar | WT | 52-check end-to-end test (Linux) |
| Planner → executor with schemas, permissions, retries, replanning, limits | WT | scripted model |
| Real brain (Qwen3-VL) quality | IU | only a tiny stand-in model was ever loaded |
| llama.cpp engine management, downloads, checksums | WT | Linux; Windows job object untested |
| Browser: search, open, read, links, tabs, click button, history | WT | local test site |
| Browser: fill permitted forms | WT | Phase A: `fill_field` (secrets refused, never submits) |
| Browser: download files | WT | Phase A: `download_file` (programs refused) |
| Browser: compare sources / report | WT | report tool cites opened sources only |
| Windows control: launch, focus, list windows, controls, click, type, keys, screenshot, look at screen | IU | stand-in desktop; pywinauto driver never run |
| Windows: scroll, menus, unexpected-dialog detection | IU | Phase A: tested on the stand-in desktop |
| Windows: visible "Claw is in control" indicator + global stop | WT (Linux) | quick bar + Ctrl+Alt+X |
| Notepad workflow (type, save, reopen, verify) | IU | Phase A: Test A passes on the stand-in; real Windows BLOCKED |
| Files: find, read, write, report, spreadsheet, edit with backup | WT | |
| Files: copy / organise into a new folder | WT | Phase A: `copy_files`, `check_file` |
| OCR + PDFs (7 cases), searchable PDF, chunks with pages | WT | synthetic scans |
| WhatsApp unread detection + notification | IU | Phase B: official app via UI Automation; stand-in tested; real app BLOCKED |
| Email (read/draft/send as separate permissions) | **NI** | messaging-app Enter guard added; email clients not integrated |
| TechDesk sale workflow | IU | Phase C: through the app's screen (UI Automation); stand-in tested; real app BLOCKED |
| Image editing (Photoshop / alternative) | WT (built-in) · IU (Photoshop) | Phase D |
| Video creation (images + text + audio → MP4) | **NI** | |
| Calendar + meetings, transcription | **NI** | |
| Two tasks controlling the desktop at once | WT | runner allows one task at a time |
| Resumable long tasks | **INC** | interrupted tasks are marked, not resumed |
| Installer | IU | scripts written, not built |

No fake progress or placeholder success was found: progress comes from recorded events, and outcomes
come from recorded steps. Tools that can't run report it, for example "Controlling desktop apps works on
Windows only".

## Plan (phases, in the prompt's priority order)
| Phase | Content | Can be fully tested here? |
|---|---|---|
| A | Windows control hardening (scroll, menus, dialog detection, verification), Notepad test A, browser forms and downloads (test B), file copy/organise | Logic yes; real Windows no (BLOCKED, with steps) |
| B | WhatsApp unread check + notifications (approach to be chosen) | No (needs Windows + your account) |
| C | TechDesk test-sale workflow | Partly (needs TechDesk build + test data) |
| D | Image editing: Photoshop when installed; Pillow-based fallback | Fallback yes; Photoshop no |
| E | Video: images + text + audio → MP4 with FFmpeg, verified duration and sync | Yes |
| F | Calendar, meetings, transcription (whisper.cpp) | Partly |
| G | Packaging, security, release testing (Test I and Test J) | Partly |

Rejected up front (reasons in THIRD_PARTY_NOTICES when each phase lands): multi-agent frameworks
(LangGraph, AutoGen, CrewAI…), because the single validated pipeline already exists; Selenium and
Browser Use, because Playwright already covers it; Tauri and .NET, because the stack is working; bundling
heavy editors (GIMP, Blender, Kdenlive) or generative video models.

## Decisions (with the user, 26 Oct 2026)
- **WhatsApp:** read unread badges in the official WhatsApp Desktop app through UI Automation. No
  unofficial libraries. Sending always needs confirmation.
- **TechDesk:** operate `TechDesk-enterprise` (the Electron desktop app) through its screen, like WhatsApp —
  not through its code or data — tested against test data only.
- **Calendar:** calendar apps on the PC only (Windows Calendar / Outlook through UI Automation, and
  `.ics` files). No Google/Microsoft sign-in.
