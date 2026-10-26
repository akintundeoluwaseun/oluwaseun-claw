# Known issues and limits (v0.5.0)

## Not yet tested
| Area | Status |
|---|---|
| Running on Windows 10/11 | Never run. Everything was tested on Linux. |
| Real Qwen3-VL brains | Never loaded. Tests used a tiny random stand-in model. Planning quality, speed and memory on 8 GB and 16 GB laptops are unknown. |
| Windows UI Automation (desktop apps) | Logic tested on a stand-in desktop only. Checklist in `docs/DESKTOP.md`. |
| Installers (`build-release.ps1`, Inno Setup) | Written, not built or installed. |
| `setup.ps1` downloads (llama.cpp via GitHub, Tesseract via winget) | Not run. |
| Engine stopping when Claw is force-closed, on Windows (job object) | Written, not tested (tested on Linux). |
| GPU builds of llama.cpp (Vulkan/CUDA) | Not tested. |
| OCR on real-world scans and other languages | Synthetic English pages only. |

## Limits by design
- One task at a time. "Plan only" can't be cancelled once started.
- Desktop steps need an unlocked screen. Admin windows (UAC prompts) can't be controlled.
- OCR reads plain text: tables, columns and handwriting are not structured, and handwriting is
  usually not recognised.
- Password-protected PDFs aren't opened. PDFs over 500 pages are refused.
- Injection detection is pattern-based. The real protection is that changes need your approval.
- Spreadsheet checks catch values Claw never saw; they can't catch a real value put in the
  wrong row.
- The Pro installer is `Setup.exe` plus `.bin` parts (Inno Setup's single-file limit is about 4.2 GB).
- Not code-signed: Windows SmartScreen will warn on install.
- A brain that doesn't fit the computer can still be downloaded after a warning; it may then
  refuse to load with a "not enough memory" message.

## Fixed in this version (for reference)
See `TEST_RESULTS.md` → "Bugs found and fixed in this cycle".
