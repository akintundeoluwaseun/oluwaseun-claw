# Known issues and limits (v0.5.0)

> Verdicts for every capability are in `docs/CAPABILITY_MATRIX.md`; the tests
> that need another machine are in `docs/WINDOWS_ACCEPTANCE.md`.

## The four things that block most of what is untested
1. **No Windows desktop** in the build container, so all desktop automation is
   tested against a labelled double.
2. ~~**No reachable model weights**~~ **Resolved, 15 November 2026.** A real
   `llama-server` with a real brain (Qwen3.5-2B Q4, 4 CPU cores) has now
   answered, and doing so overturned several conclusions reached without one —
   see `docs/PERFORMANCE.md` and `research/performance-audit/FINAL-REPORT.md`.
   **Still Linux only.** Qwen3-VL and vision have not been loaded.
3. **No Claw service and no provider credentials**, so hosted inference is
   unproven. Claw Online's client is written; the server does not exist.
4. **No public internet**, so web search is tested against a local site only.

## Not yet tested
| Area | Status |
|---|---|
| Running on Windows 10/11 | The **backend test suite runs on real `windows-latest`** in CI on every push (`.github/workflows/test-windows.yml`), and it has caught a bug Linux hid. What has never happened on Windows: a brain answering, desktop automation, the live thinking-switch probe, and an installer being built or installed. See `docs/WINDOWS_ACCEPTANCE.md`. |
| Real Qwen3-VL brains | Never loaded. A non-vision brain (Qwen3.5-2B) has been measured end to end on Linux; the VL models, `mmproj` and `see()` have not. Memory on 8 GB and 16 GB laptops is still unknown. |
| Vision (`see`) with a *thinking* brain | Untested, and known to be unguarded: unlike every other lane, `see()` neither asks the brain to stop thinking nor rejects an empty reply, so a thinking vision brain would return an empty description. No vision model was available to measure. The fix is sketched in its docstring. |
| Model specialisation (different brains for different jobs) | **NOT TESTED.** Only one brain was ever available. No conclusion has been drawn. |
| The Light brain (`qwen3-vl-2b`) | Its Hugging Face repository and file patterns were written by analogy with the 4B and 8B entries and have never been resolved against the API. If they are wrong the download fails with "no file matched"; it cannot fetch the wrong file, because names, sizes and checksums all come from the API. |
| Claw Online end to end | The client refuses a plain-http service, carries a built-in token and reports connection loss honestly — all tested. No request has ever reached a real service, because there isn't one. |
| SearXNG as a search backend | The provider interface, URL building and validation are tested. No SearXNG server has been contacted. |
| PowerShell build scripts | Cannot be run **or parsed** on Linux. A parse check now runs in the Windows test workflow. |
| Windows UI Automation (desktop apps) | Logic tested on a stand-in desktop only. Checklist in `docs/DESKTOP.md`. |
| Installers (`build-release.ps1`, Inno Setup) | Written, not built or installed. |
| `setup.ps1` downloads (llama.cpp via GitHub, Tesseract via winget) | Not run. Note that it fetches **whichever llama.cpp build was newest at install time**, so the engine version is not reproducible; setup now checks the downloaded build supports `--jinja`, which Claw needs for the thinking switch. |
| Engine stopping when Claw is force-closed, on Windows (job object) | Written, not tested (tested on Linux). |
| GPU builds of llama.cpp (Vulkan/CUDA) | Not tested. |
| OCR on real-world scans and other languages | Synthetic English pages only. |

## Limits found by measurement (15 November 2026)

- **A thinking brain needs an engine that can be told not to think.** Claw
  sends `chat_template_kwargs`, which `llama-server` only honours under
  `--jinja`. On an engine too old to accept it, Claw falls back safely and
  logs it, and **Settings → Claw's brain → test the brain now warns** — but a
  thinking brain on such an engine can spend its whole reply budget reasoning
  and answer nothing. Measured: zero characters of answer at 512, 1024, 1536
  and 2048 tokens. Fix: a newer llama.cpp build, or a brain that doesn't think.
- **A simple action that has to be planned can run out of time.** On a 2B at
  ~13 tokens a second, planning a one-step job costs 9–14s of the 30-second
  simple-action budget, which can leave too little for the step itself. The
  budget is deliberately left at 30 seconds rather than quietly becoming "30
  seconds after planning"; raise `simple_deadline_s` if your brain needs it.
  Jobs the one-action shortcut recognises skip planning entirely and finish in
  about a third of the budget.
- **A 2B is the floor, not the target.** Capability selection measured 14/16 on
  held-out tasks with that brain. A larger brain should do better; none was
  available to confirm it.

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

## Claw's own browsing history is not kept in headless mode on Windows

Chromium writes no History database at all when it runs hidden on Windows.
Measured on a Windows runner with one persistent profile: headless produced 50
profile files and no `Default\History`; the same run with a visible browser
produced 156 files including it. Headless on Linux does write it, which is why
this only ever showed up on Windows.

Effect: with **Settings → Browser → run hidden** turned on, on Windows,
`search_browser_history(source="claw")` finds nothing. Claw now says exactly
that instead of "no browsing history was found". Reading Chrome's or Edge's own
history is unaffected, and so is the default configuration, because Claw runs
the browser visibly unless you change it.
