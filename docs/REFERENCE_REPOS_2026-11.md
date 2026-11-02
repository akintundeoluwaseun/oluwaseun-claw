# Reference repositories: what S-CLAW takes, adapts, or leaves (2 November 2026)

Each repository was cloned (shallow) and read: the README, the licence, and the code named below.
Nothing here was installed into S-CLAW. "Adopted" means the idea was rewritten in our own code,
with a test.

| Repository | Licence | What it is |
|---|---|---|
| xlang-ai/OSWorld-V2 (OSWorld 2.0/2.1) | Apache-2.0 | Benchmark for computer-use agents. Tasks are JSON or Python, each with setup, an evaluator (getter + metric) and post-config. Ubuntu VMs or Docker, ~16k lines of metrics, and the official tasks sit in a gated Hugging Face dataset. |
| ServiceNow/BrowserGym | Apache-2.0 | A gym environment for browser agents on Playwright: bid-marked AX tree, high-level action set, MiniWoB++ / WebArena / AssistantBench wrappers. |
| OpenHands/open-operator | MIT | A curated list of resources, benchmarks and models (UI-TARS, OS-Atlas, SeeClick…). No runnable agent code. |
| browserbase/open-operator | none stated | A Next.js demo that drives Browserbase's cloud browsers with OpenAI. |
| pywinauto | BSD-3 | Already S-CLAW's Windows UI Automation layer. |
| FlaUI | MIT | .NET (C#) wrapper over UIA2/UIA3. |

## Worth adopting (done today, tested)

1. **OSWorld's "infeasible" tasks.** An impossible task scores as passed only when the agent says it
   cannot be done. Two such scenarios were added to our benchmark as set **v1.1**: a missing file and
   a missing app. This measures the false-completion behaviour the owner cares most about.
2. **OSWorld's document-integrity check** (`desktop_env/safety/files.py`). Every input file is hashed
   before a scenario and again after it. Any file S-CLAW changed or deleted without being asked is
   reported next to the score as a safety signal. It is not folded into the score, so the baseline
   stays comparable.
3. **A frozen baseline set.** The original 16 challenges are set `v1` and are never edited. New
   scenarios go into later sets, and the report shows the v1 average on its own.

## Worth adapting (planned, in the milestone named)

- **OSWorld's multi-check scoring** (`conj: "avg"`, fine-grained partial credit). This is already how
  our checks work. **Milestone 3** borrows its `compare_table` rule style (cell values, a column
  present, row counts) for spreadsheet checks.
- **MiniWoB++ through our own Playwright** (BrowserGym's `miniwob` package shows how): the task pages
  are local HTML and the reward is read from the page's own JavaScript. This gives **milestone 6** a
  free, offline, objective browser test bed with hundreds of small tasks.
  - The BrowserGym package itself is not installed: it pins `playwright==1.44` and `lxml<6`, which
    conflict with ours (1.64, 6.1.3), and it adds gymnasium and numpy for no gain.
- **BrowserGym's frame-by-frame element marking** (`frame_mark_elements.js`). This is only worth it if
  milestone 6 shows our aria-ref snapshot (from OpenClaw) missing elements inside iframes. Measure
  first.
- **FlaUI / pywinauto read-back after typing.** S-CLAW's `invoke` is already pattern-first, the
  FlaUI way: Invoke, then Toggle, then Select, then Expand, and a mouse click only as the last
  resort. What is missing is reading the control's Value back after `type_text`. Today every typing
  step ends as "done, not checked", and the release checks once garbled "S-CLAW" to "S-CLAt". Adding
  a ValuePattern read-back turns those steps into checked ones or honest failures. This is planned
  as a small slice inside **milestone 4**, measured by the share of `type_text` steps that come back
  verified.

## Not worth adopting

- **OSWorld's environment** (VMs, Docker, a task server, gated datasets). It is Ubuntu-first and
  heavy, and its tasks are LibreOffice/GIMP on Linux. Our users are on Windows, and GitHub's Windows
  runner already serves as our clean machine.
- **OSWorld's official tasks.** They are gated, built for Linux apps and kept private to avoid
  leakage. We keep our own tasks, aimed at Windows and at the owner's list.
- **The BrowserGym package**, because of the version conflicts described above.
- **FlaUI itself.** It is .NET: using it would mean pythonnet plus the FlaUI DLLs, all for UIA3,
  which pywinauto's `uia` backend already uses. That is risk without a measured gain.
- **browserbase/open-operator.** It needs paid cloud browsers and an OpenAI key, which breaks the
  "free, no keys" rule.
- **Grounding models listed by open-operator** (UI-TARS-7B, OS-Atlas). These are worth a later look
  only if the benchmark shows that clicking on the screen by sight is what fails. Our Qwen3-VL brains
  already point at screen locations.

## Expected improvements (to be measured, not assumed)

- Infeasible scenarios and integrity hashing: no speed gain. They make the score **honest**, by
  catching false completions and unrequested file changes the v1 checks could miss.
- MiniWoB++ (milestone 6): a browser success rate measured over many tasks instead of a handful.
- ValuePattern read-back (milestone 4): the share of verified `type_text` steps should go from 0%
  today to most of them.

## Risks and licences

- **Apache-2.0** (OSWorld, BrowserGym): code we port must keep the notice and mark our changes. We
  only took ideas, and the files name their source. THIRD_PARTY_NOTICES lists both.
- **MIT** (FlaUI, open-operator, MiniWoB++): keep the copyright notice with any copied code.
- **Benchmark drift**: adding scenarios changes the overall average. That is why the v1 average is
  reported on its own.
