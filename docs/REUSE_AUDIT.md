# Reuse audit (playbook Step 1) — 2 November 2026

Audit only: no production code was changed for this document. It was written against the actual
repository: the 86 registered tools, backend/requirements.txt, the installer scripts and the
benchmark evidence (TEST_RESULTS.md, ci-evidence). Statuses come from docs/CHALLENGES.md (286
challenges): 12 PASSED, 9 BUILT, 1 FLAKY, 2 FAIL, 197 PLANNED, 65 OUT.

## 1. What S-CLAW already uses, by capability

| Capability | Implementation today | Library already in | Evidence |
|---|---|---|---|
| Windows desktop control | `computer/windows_uia.py`. Pattern-first: Invoke → Toggle → Select → Expand, then a mouse click as the last resort. `launcher.py` uses Get-StartApps / AppsFolder IDs. `wait_for_window`, `read_control` | **pywinauto 0.6.9 (UIA backend)**, comtypes, pywin32 | Notepad task PASSED with all three brains on a clean Windows runner. Release checks 33–40 |
| Browser | `browser/session.py` and `snapshot.py`: aria-ref role snapshot (ported from OpenClaw); click / type / choose by ref; downloads; tabs | **Playwright 1.64.1** | Real Chromium tests here. No web challenge from the list has run with a real brain yet |
| Files / OS | 26 file tools: find, list, copy, move, rename, duplicates by content, compare folders, sort into folders, date ranges | stdlib | 15.02, 15.03, 15.04, 15.11, 15.12 PASSED (benchmark) |
| Spreadsheets / data | `tools/table_tools.py`: combine, dedupe, totals, chart, break-even and forecast models | **openpyxl 3.1.5**, csv | 7.01, 7.02, 13.11 PASSED. Models and charts BUILT |
| Word / PDF | `documents/readers.py` and `pdf_pipeline.py`. save_report writes .docx | **python-docx 1.2.0, pypdf, pypdfium2** | docs-invoices-table and docs-five-files PASSED |
| OCR | `documents/ocr.py`; Tesseract ships inside the installer (eng + osd) | **Tesseract** (bundled) | invoice OCR PASSED; flyer/video headline read-back PASSED |
| Images | `integrations/images.py`: flyer and edits. Photoshop through COM/ExtendScript | **Pillow 13.0** | Built-in editor PASSED. Photoshop never run |
| Video | `integrations/motion.py`: built-in maker; After Effects through `AfterFX.exe -r` | **PyAV 19.0.2** (bundles FFmpeg libraries) | Built-in maker PASSED. After Effects never run |
| Speech | `speech/sherpa.py` | **sherpa-onnx 2.0.1** (Apache-2.0) | Unit-tested. Not benchmarked |
| Safety | `permissions/policy.py`: tiers read_only / local_write / external / destructive, approvals, authorized folders, an unattended mode that refuses asks. Guards in `agent/executor.py` | — | Release checks. Benchmark input hashing found 0 unrequested changes in run 3 |
| Plan preview | `POST /tasks/plan` and the app's "Plan only" button | — | e2e test |

**So most of the playbook's Phase 1 (pywinauto), Phase 2 (Playwright) and Phase 3/4 libraries
(openpyxl, python-docx, Pillow, Tesseract, FFmpeg via PyAV) are already integrated.** The gap
is not missing libraries. It is (a) real-brain reliability and (b) a few missing adapters.

## 2. Duplicate or fragile code found

1. **Executor guards are growing regex heuristics** (`fitting_tools`, `premature_finish`,
   `_unfinished_recipe`, `invents_named_file`, `breaks_no_files_rule`, `arithmetic_slip`). Each is tested
   and was added because of a measured failure, but together they are brittle with wording.
   - *Fix:* move the request checks into one intent-and-constraint step that runs before the
     plan. This is the playbook's "INTENT + CONSTRAINT PARSER".
2. **Two tool lists that must agree**: `executor.LOOKING_TOOLS` / `SAVING_TOOLS` and `report.LOOKING`.
   - *Fix:* make them one attribute on each tool's spec (read-only vs making).
3. **Overlapping tools**: `combine_files` (text) vs `combine_tables`, and `create_spreadsheet` used by
   the brain to rebuild tables by hand. The brain picks the weaker tool when both fit.
   - *Fix:* clearer descriptions, and fitting rules that prefer the deterministic tool (already
     partly done).
4. **`type_text` is never verified.** Every typing step ends "done, not checked". The release checks
   once garbled "S-CLAW" to "S-CLAt".
   - *Fix:* read the control back through UIA ValuePattern (pywinauto `get_value`/`window_text`).
5. **`click_at` (screen coordinates)** exists for apps with poor UIA trees. It is not used in any
   passed task. Keep it as the last resort, as the playbook says.
6. **The tool catalogue is near its token budget** (86 tools; the files section is about 2,000 tokens
   for small brains). Every new tool now costs shorter descriptions elsewhere.
   - *Fix:* load a capability's tools only when the plan needs that capability. This is already
     done per task; the remaining pressure is the per-capability section.
7. **One unexplained hang**: benchmark run 3, infeasible-missing-app, 22 minutes with no step
   recorded. Per-step logging was added; run 4 will show where it stalls.

## 3. BUILT, not yet PASSED, and what closes each gap

| ID | Gap | What closes it |
|---|---|---|
| 17.06 conflicting instructions (FAIL ×3) | Safety bug. The brain makes the file it was told not to | `breaks_no_files_rule` guard is built; **benchmark run 4 is the test**. The general fix is the intent/constraint step (§2.1) |
| 17.07 wrong path (FLAKY) | Brain adds an age filter nobody asked for | 0/None filter fix built; run 4 |
| 17.09 missing app | Hang | Step logging; run 4 |
| 7.03 / 7.04 / 7.15 / 7.16 / 7.20 | Charts and models | Benchmark set v1.2 (run 5) |
| 1.06 billboard, 3.14 video with Adobe apps | Photoshop and After Effects paths never run | Needs a Windows machine with Adobe apps. GitHub has none, so **NOT RUN** until the owner runs it |
| 17.04 resume, 17.17, 17.20 report | Built in milestone 2 | Needs a benchmark scenario that interrupts a task |

## 4. Playbook repositories: adopt, adapt, or not

| Upstream | Verdict | Why |
|---|---|---|
| pywinauto | **Already in** (0.6.9, BSD-3) | Next: ValuePattern read-back after typing (§2.4), and Calculator, File Explorer and Settings as the first test apps |
| Playwright | **Already in** (1.64.1, Apache-2.0) | Next: milestone 6 structured extraction into a sheet, plus MiniWoB++ as an offline test bed |
| Browser Use 0.13.14 | **Do not add as a dependency** | 62 packages, including posthog telemetry and the OpenAI, Anthropic, Google and Groq SDKs. It pins pillow 12.3 and pydantic 2.13.5, which clash with ours (13.0, 2.14.1). Its agent is designed for large hosted models. Ideas only |
| OpenCV | **Not now** | About 90 MB. Pillow covers today's image tasks. Add only if a milestone 8 task needs contours, perspective or image comparison that Pillow cannot do, and measure first |
| Pillow | **Already in** | — |
| Tesseract | **Already in** (bundled) | Keep. Confidence and boxes could be exposed for screen reading |
| FFmpeg | **Already in through PyAV** | PyAV's libraries report "LGPL version 3 or later" but include libx264 and libx265 encoders (GPL upstream). **Licence check needed before calling the installer licence-clean** (§5). Milestone 7 can use PyAV's filters instead of shipping ffmpeg.exe |
| whisper.cpp | **Not now** | sherpa-onnx already does offline speech (Apache-2.0, unit-tested). Compare only if the voice benchmark shows sherpa failing on Nigerian English |
| pandas | **Not now** | About 60 MB with numpy. openpyxl plus our own readers already pass the data challenges. Reconsider for 7.07 pivots and 7.18 reconciliation if the code gets complex |
| openpyxl | **Already in** | Does not calculate formulas. We write live formulas and compute the expected values in Python. LibreOffice headless could recalculate for checking, when installed |
| python-docx | **Already in** | Milestone 5: headings, a table of contents field, styles |
| python-pptx | **Adopt in milestone 5** (MIT, about 1 MB, needs lxml and Pillow, both already in) | 8.08–8.15 decks |
| LibreOffice | **Optional, detected** (MPL-2.0; not bundled, about 300 MB) | DOCX/PPTX/XLSX → PDF and recalculation when installed. Section 8 tasks must not depend on it |
| Blender | **Optional, detected** (GPL; not bundled) | Milestone 8: `blender -b -P script.py`. Free, so it can run on GitHub's Windows runner |
| FreeCAD | **Optional, detected** (LGPL; not bundled) | Milestone 10: parametric parts through its Python. Do not claim SolidWorks or AutoCAD parity |
| OSWorld / OSWorld-V2 | **Ideas adopted** | Infeasible tasks and input hashing (benchmark v1.1). Not a runtime dependency |

## 5. Licence and dependency risks

- **PyAV/FFmpeg encoders (needs checking):** the bundled build includes libx264 (GPL-2.0+). Two
  ways forward:
  - (a) confirm the wheel's terms and ship the GPL notices and source offer; or
  - (b) encode with an LGPL-safe encoder (OpenH264 or VP9), checked by the same test.
  **Until checked, do not describe the installer as LGPL-only.**
- Blender is GPL and FreeCAD LGPL. Both are run as separate programs the user installs, not
  bundled, so S-CLAW's own licence is unaffected.
- Every adapter for an optional tool must have an availability check and must say what is missing,
  never pretend. make_flyer and make_motion_video already do this.

## 6. Cost on low-spec PCs (installer today: 837 MB installed)

| Addition | Disk | RAM while used |
|---|---|---|
| python-pptx | about 1 MB | small |
| pandas + numpy | about 60 MB | 50–150 MB |
| OpenCV (headless) | about 90 MB | 50–200 MB |
| Browser Use | 100 MB+ of SDKs | — (rejected) |
| LibreOffice / Blender / FreeCAD | 300 MB – 1 GB each | 300 MB – 2 GB+. Optional, the user's own install |

## 7. Recommended order (each a small vertical slice; needs your approval)

1. **17.06 and the general intent/constraint check**: one pre-plan step that pulls out "do not…",
   "only…", "without…", deadlines and file names from the request, and that the guards consult.
   Measured by stress-conflict and the stress set.
2. **Typing read-back (pywinauto ValuePattern)**, plus Calculator, File Explorer and Settings tasks.
   Measured by the share of verified `type_text` steps and three new benchmark tasks.
3. **One tool list, read from each tool's spec** (§2.2). No behaviour change; tests prove it.
4. **Milestone 4 remainder** (startup apps, memory hogs, bulk rename with approval, archive a project,
   find broken shortcuts) using stdlib and pywin32, which are already in.
5. **Milestone 5 with python-pptx** (new, small) and python-docx (in), plus LibreOffice detection for
   PDF export.
6. **The FFmpeg licence decision** (§5) before milestone 7 adds video features.
7. **Blender as an optional adapter** (milestone 8), tested on the GitHub runner with Blender
   installed there.

## 8. Tests each slice needs before adoption

- Unit tests for the adapter and its availability check.
- An integration test against the real library or app (here, or on the Windows runner).
- An end-to-end benchmark scenario with independent checks on files and answers, run with a real
  brain on the clean Windows runner. The evidence goes in TEST_RESULTS.md and ci-evidence.
- Statuses in CHALLENGES.md move only on that evidence. Where an app is missing, the result is
  **NOT RUN**, never a simulated pass.
