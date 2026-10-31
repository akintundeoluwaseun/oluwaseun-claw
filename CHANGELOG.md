# Changelog

## Unreleased — fixes from the first real install (Light brain)
### New layout (user: "change everything, the arrangement")
- A slim rail on the left (New, Chats, Docs, theme, Settings); chats slide out as a drawer and are remembered open or closed.
- Status (agent and brain) moved to the top right.
- Home: the logo, one question, the task box, six tiles of what Claw can do (Files, Web, Apps, WhatsApp,
  Calendar, Flyers; each fills in an example), and "Pick up where you left off" with the three latest chats.
- A task is split in two: the conversation on the left (your messages, Claw's question or answer, the files it
  made, the reply box docked at the bottom) and a live Steps panel on the right with a progress bar.
- While Claw thinks, its reply says so ("Thinking about how to do this…", then "Working on it").
### Second real-brain trial (run 41173224236)
- The brain asked for "Documents" (relative): refused as outside the authorized folders. Relative names now start
  at the authorized folder they name (traversal still refused).
- Three tasks hit the 120 s reply limit while a 2B brain on a CPU read the tool list. A local brain now gets
  10 minutes per reply, and when tools plainly fit the request only those are described in full.
- A finish with no steps and no summary, and "I will now save…" with no save tool named, are now sent back
  with the fitting tools named.
### Found by the real-brain trial on Windows (`real-trial.yml`, Qwen3-VL 2B, run 41171556944)
- Every file task failed with "no folders have been authorized": a fresh install had no folders at all.
  **Fixed:** a new install (or one that never had folders) is given Documents, Desktop and Downloads once
  (OneDrive's copies when Windows keeps them there). Removing them later sticks. Writing still asks first.
- The brain said "I will now proceed…" after one step and the task was reported **completed**. It also said it
  had no tool for a flyer, a spreadsheet and a copy with `make_flyer`, `create_spreadsheet` and `copy_files`
  in its list. **Fixed:** the tools that fit the request are named next to the task and described in full, and
  a finish that describes work still to do, or gives up for want of a tool that exists, is sent back (twice
  at most). Shown in the timeline as "Claw stopped too early, so it was told to carry on".
- Settings said the brain was ready when its last start had failed, so every task errored with a "ready"
  brain on screen. **Fixed:** status reports "Brain did not start" with the reason, and the task box shows it.
- "Finished" in green over a list of failures. **Fixed:** "Finished, but nothing worked" (red) or "Finished
  with problems" (amber).
### Reported by the user
- **Chats.** A retry or a follow-up stays in the same chat: one history entry with a message count, instead
  of a new entry with the same name each time. Titles are written by the brain while planning (2–6 words),
  with a cleaned-up fallback, not the request pasted back. Follow-ups are planned knowing the last three
  messages. New: `thread_id`/`title` on tasks (schema 5), `GET /tasks?thread=`, `thread_id` on `/tasks/run`.
- **Settings appeared to switch back.** Settings now re-reads what is saved each time it opens, and after
  saving checks that the chosen way of thinking was kept, saying so if it was not.
- **"Not connecting".** llama-server needs the Microsoft Visual C++ runtime, which many home PCs lack; the
  engine then dies before printing anything. The installer now ships the runtime DLLs next to the engine, and
  the two Windows exit codes for "DLL missing" and "processor not supported" are explained in plain words.
  (Likely cause, not yet confirmed on the user's PC.)
- The edition profile written by PowerShell has a byte-order mark; it is now read with `utf-8-sig` instead
  of failing and falling back.
### Changed
- Charcoal, chat-style window with the logo's periwinkle as the only accent (no uppercase labels, no card around
  every block; Claw's answer leads the result). The logo tile now follows the theme: its inline style was
  blocked by the page's CSP, so it was always a black square. Before that: your request on the right, Claw's steps and outcome as its reply, a reply box at
  the foot of each chat, a breathing edge while Claw works. Dark is now the default theme.

## Unreleased — Windows build on GitHub
### Added
- `.github/workflows/build-windows.yml`: builds the installer (with its brain) on GitHub's Windows machines,
  runs the backend tests on real Windows, smoke-tests the frozen backend, and publishes a GitHub Release.
- `backend/packaging/fetch_brain.py`: downloads a brain with Claw's own checked downloader for bundling.
- The installer stores brain files uncompressed (faster builds) and can be split into parts below 2 GB.

## Unreleased — v0.6 Phase D
### Added
- **make_flyer:** promotional flyers (headline, subtitle, up to 6 points, contact band, up to 4 pictures) in
  square, story, A5, A4 or landscape, as PNG, JPG, PDF (or PSD with Photoshop). Uses **Photoshop when it is
  installed** (its scripting interface), otherwise Claw's built-in editor, and always says which one made it.
  The result is reopened, its size checked, and the headline read back with OCR.
- **edit_image** (crop, rotate, resize, brightness, contrast, black-and-white, convert; saves a new file) and
  **inspect_image**.

## Unreleased — v0.6 Phase C
### Added
- **TechDesk sales through the app's screen:** "Open TechDesk and prepare a sale for two phone chargers"
  opens Sales → New Sale, searches each product, reads the real names and prices shown, sets quantities,
  and checks TechDesk's total against prices × quantities. Preparing never records anything.
- Ambiguous or missing products: Claw asks, listing what TechDesk shows. PIN screens: Claw stops.
- **Recording** is a separate step that always asks; it only goes ahead if the screen still shows the
  approved total, then looks for the sale in the Sales list and reports a receipt/invoice number only if
  TechDesk displays one. **Cancel** closes the form without recording.

## Unreleased — v0.6 Phase B
### Added
- **WhatsApp unread check** in the official WhatsApp Desktop app (UI Automation): chat names and
  unread counts, "new since the last check", optional short previews (off by default). It opens
  WhatsApp if needed and says clearly when WhatsApp isn't installed, isn't linked, is still loading,
  or can't be read. Message text is never stored.
- **Settings → Messages (WhatsApp):** reading permission (Ask me / Go ahead / Never), optional
  background check every 15/30/60 minutes (only with Go ahead, never opens WhatsApp itself), a
  notification when chats get new messages, and a "Check WhatsApp now" button.
- **Send a WhatsApp message:** always asks, exact chat name only, checks the message appeared.
- In WhatsApp, Telegram, Teams, Outlook, Slack, Discord, Signal and other messaging apps, pressing
  Enter or typing a new line counts as sending and always needs your OK.

## Unreleased — v0.6 Phase A
### Added
- Browser: **fill_field** (text, dropdowns, checkboxes; never passwords, cards or codes; never submits)
  and **download_file** (into an authorized folder; programs and scripts refused; never overwrites).
- Files: **copy_files** (by pattern or "only screenshots", into a new folder; checked by checksum;
  originals untouched) and **check_file** (reopen a file and compare its exact contents).
- Windows: **scroll**, **choose_menu** (File > Save As…; "Delete"-type items need your OK),
  **wait_for_window**; pop-up dialogs are reported after every action, and error-like dialogs mark
  the step as not done.
- Typing runs in short bursts, so Stop / Ctrl+Alt+X interrupts long typing quickly.
- `docs/AUDIT_V06.md` (feature matrix and plan) and `docs/WINDOWS_ACCEPTANCE.md` (real-Windows test steps).

## Unreleased — Batch 5 (part 1)
### Added
- User guide, developer guide, known issues list and release checklist.
- Security review and dependency audit (no known vulnerabilities).

## 0.5.0 — 2026-10-26 (scanned documents + built-in engine)
### Added
- **Documents view:** open PDF, Word, Excel or text files; live progress; each page shows whether
  its text came from the file or from a scan, with OCR confidence and rotation; unclear or unread
  pages flagged; search with jump-to-page; "Ask Claw about this document"; save a searchable copy
  of a scanned PDF (never overwrites).
- **OCR (Tesseract):** only pages without real text are OCR'd, at 300 DPI; sideways pages turned
  upright; results cached; English built in, other languages can be added; works without the brain.
- **Agent document tools:** read pages with labels, search, summarise in bounded chunks with page
  references, make a searchable PDF (asks first). Text from documents is treated as untrusted.
- **Claw's own engine:** llama.cpp `llama-server`, started and stopped by Claw on 127.0.0.1 with a
  per-launch key; memory check, load wait, crash restart, idle unload; stops if Claw is killed.
- **Brains:** Standard (Qwen3-VL 4B) and Pro (Qwen3-VL 8B), with screenshot vision. Settings shows
  engine status and lets you download (size, progress, cancel, resume; licence and checksum
  checked), switch, remove (with confirmation), use your own GGUF file, or restart the brain.
- **Packaging:** frozen backend (PyInstaller), electron-builder layout, Inno Setup script for the
  Standard and Pro installers, `build-release.ps1`; `setup.ps1` now fetches llama.cpp and Tesseract.
- Tests: OCR (16), agent + documents (3), engine/runtime (19), e2e +13 checks (52 total), packaged-app smoke (9).
### Changed
- Developer custom server defaults to an OpenAI-compatible (llama.cpp) server on port 8080.
- Malformed or cut-off brain replies are retried instead of failing the task as a server error.
### Removed
- **Ollama is no longer required** (kept only as an optional developer adapter). The automatic
  Ollama model manager was removed.

## 0.4.0 — 2026-10-26 (Batch 4)
### Added
- **Re-planning:** after two failed steps Claw works out why and makes a new plan (max 2 per task).
- **Documents:** read PDF, Word and Excel files; write text files; save reports (Word or Markdown)
  that may only cite pages/files Claw opened; create spreadsheets (Excel or CSV) with a check of
  how many values match what Claw read; edit text files with an automatic backup.
- **Prompt-injection guard:** content that tries to instruct Claw is flagged in the timeline and
  outcome; after it, every change needs your OK. After reading any web/file content, changes
  outside the computer need your OK even if allowed in Settings.
- **Recovery:** the app restarts the agent if it crashes (up to 3 times in 5 minutes); interrupted
  tasks are marked; "Run this task again" on finished tasks.
- **Outcome card:** files Claw made, with Open and Show in folder (only files from that task).
- History search also finds words in Claw's answers and errors.
- Shorter prompts: full tool details only for the capabilities a plan needs.
### Removed
- Online mode and the Google key screen. Claw uses its built-in brain only.

## 0.3.0 — 2026-10-25 (Batch 3 + brain choice)
### Added
- **Claw's brain, chosen once on a welcome screen:** Online (Google Gemini with the user's own
  free key; Claw picks the model and falls back when a daily limit is hit) or Offline (Claw
  measures the computer, picks models by role, downloads them with progress, unloads when idle).
  No model picking for users. Key stored encrypted with Windows DPAPI.
- **Desktop control (Windows UI Automation via pywinauto):** list/switch windows, open apps from
  the Start menu (system tools refused), numbered controls, click/type/keys with before-and-after
  checks, screenshots, "look at the screen" through the brain, click-at-position fallback.
- **File tools:** list folders, read text files, find files, all within authorized folders.
- Buttons labelled Send/Delete/Buy/Pay/Submit/Post… always ask, in apps and on web pages.
- Global stop shortcut **Ctrl+Alt+X**; quick bar shows it while Claw uses the mouse and keyboard.
- Locked-screen and admin-window cases reported clearly.
### Changed
- Model settings moved to Settings → Claw's brain → Developer.

## 0.2.1 — 2026-10-25 (interface redesign + background mode)
### Added
- Redesigned main window: custom title bar, grouped task list, large task box with example
  tasks, timeline of steps, docked approval sheet, outcome card; light and dark themes.
- Quick bar: always-on-top pill at the top of the screen; click or press Ctrl+Shift+Space,
  type a task, press Enter. Shows live activity, "Needs your OK", and a stop button.
- Tray icon with status (idle / working / needs you) and menu: open, new task, stop, show
  quick bar, start with Windows, quit. Closing the window keeps Claw running.
- Desktop notifications when a task finishes or needs approval (click opens the task).
- Keeps the computer awake while a task runs (setting).
- Start with Windows (setting; launches hidden in the tray).
- App and tray icons; bundled Manrope font.

## 0.2.0 — 2026-10-25 (Batch 2)
### Added
- Tool system with schemas, risk levels, validation and pre-checks (13 tools).
- Browser control through Playwright with a dedicated profile (Edge default on Windows):
  web search, open address/result, read page, links, follow link, click button, tabs.
- Browser-history search (titles/addresses only, always asks or off).
- `save_links` to authorized folders (no overwrite, only links seen in the task).
- Executor loop and background runner: Run, Stop, approvals, limits, retries, audit events.
- UI: Run task, live activity, approval card, Stop, outcome summary, browser/limits settings.
- Database v2 with migration; unfinished tasks marked interrupted after restart.
- Local test website and 29 new backend tests; e2e test extended to 18 checks.
### Changed
- Ctrl+Enter now runs the task; "Plan only" is a separate button.

## 0.1.0 — 2026-10-25 (Batch 1)
### Added
- Repository audit and architecture decision (custom Electron + Python runtime).
- Python backend: settings with validation and readable errors, health check,
  Ollama and llama.cpp (OpenAI-compatible) adapters, model status/probe,
  task planner with schema-validated JSON and one corrective retry,
  permission policy with risk levels and folder scoping, SQLite history and
  audit events, JSON logging with secret redaction.
- Electron desktop app: starts the backend with a per-launch token, route
  allowlist, sandboxed UI with task input, Plan button, progress, results,
  history search, settings drawer (model, permissions, folders), error banner.
- Windows scripts: setup, start, check. Linux check script.
- Tests: 46 backend, 2 desktop unit, 12-check end-to-end.

### Not included yet
- No step is executed; plans are proposals only.
