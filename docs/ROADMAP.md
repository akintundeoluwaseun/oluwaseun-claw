# S-CLAW roadmap — one milestone at a time

Made 2 November 2026 from two of the owner's documents: the "Astra-level" blueprint and the
200-challenge list. Each milestone is finished before the next one starts. A milestone counts
as finished only when it is built, its tests pass, and a real-brain run on Windows has been
recorded in TEST_RESULTS.md.

The rule for spending time and compute is to measure first, then fix what scores lowest.
Free, scriptable apps (Blender, FreeCAD, ffmpeg, LibreOffice) come before paid ones, because
GitHub's Windows machines can run the free ones, so the work can actually be tested.

| # | Milestone | What it delivers | Challenge-list sections | Status |
|---|---|---|---|---|
| 1 | **Benchmark and baseline** | A runner for challenges that each have objective checks; a first set of 16 realistic challenges; a score report per brain; this roadmap; the supported-apps matrix | 18 (scoring), 15, 7, 17 | **in progress** |
| 2 | Honest final report and resume | Every task ends as COMPLETED / INCOMPLETE / UNVERIFIED / BLOCKED, per item. Tasks are checkpointed and resume after a crash or restart | 17, blueprint §10–11 | **built**: four-part report on every result, "Carry on from where it stopped" (it skips steps already checked). Waiting on a real-brain run |
| 3 | Data and spreadsheets | Combine messy CSVs, clean duplicates, totals by group, charts in the workbook, break-even and forecast models with live formulas | 7, 13 | **built**: combine_tables, remove_duplicates, table_totals, add_chart (live SUMIF), build_model (break-even, forecast with FORECAST.LINEAR). Combine and dedupe PASSED with a real brain; models and charts are in benchmark set v1.2 |
| 4 | Files and the OS | Duplicates by content, large files, sorting a messy folder by type, comparing folders, renaming in bulk (with approval), searching by date range, startup apps, memory hogs | 15 | planned |
| 5 | Documents and office | Extracting from many PDFs, a report built from several files, Word reports with real headings and a table of contents, PowerPoint decks from a report or a dataset | 8, 10 | planned |
| 6 | Web research into a table | Research several sites into one comparison sheet, with every value linked to its source page | 9 | planned |
| 7 | Video and audio by script | 9:16 versions, several resolutions, cutting silence, finding black frames, normalising audio, subtitles from speech (PyAV/ffmpeg plus the speech model S-CLAW already has) | 2, 14 | planned |
| 8 | Creative apps by script | Blender (free, testable): product turntable render, materials. After Effects: logo animation and lower-third templates. Photoshop: one campaign exported in several sizes | 1, 3, 4 | built, not yet run on the real brain: Blender turntable/3D text (tested with bpy), make_campaign (8 sizes), logo reveal and see-through lower third (built-in makers; After Effects and Photoshop themselves never run) |
| 9 | Code workspace | Run a project's tests, read the failures, apply a fix, Git status/diff/commit (with approval) | 6 | planned |
| 10 | Engineering by script | FreeCAD parametric part, KiCad netlist checks, MATLAB-style analysis in Python, control charts (SPC) | 12 | planned |
| 11 | Multi-app missions | Chaining milestones 3–10 into one task graph, for example: CSV to analysis to chart to Word report to PowerPoint | 16 | planned |

## Reference repositories

docs/REFERENCE_REPOS_2026-11.md records what was taken from OSWorld 2.0, BrowserGym, open-operator,
pywinauto and FlaUI, what was adapted, and what was left out and why. Changes to the milestones:
- **Milestone 1**: the 16 challenges are frozen as set v1, and set v1.1 adds two OSWorld-style
  infeasible tasks plus input-file hashing.
- **Milestone 4**: gains a ValuePattern read-back after typing.
- **Milestone 6**: gains MiniWoB++ as an offline browser test bed.

## What S-CLAW will not claim

These need a frontier-size model or a paid app that cannot be tested here, so they stay out
of scope until that changes:

- removing a person from a photo, hair-level masking, colourising a photo;
- multi-camera edits and colour grading in Premiere or Resolve;
- SolidWorks assemblies;
- Figma design systems;
- character rigging.

S-CLAW will say it cannot do them rather than try and fake a result.

## Brain choice for runs

Benchmarks run on the **Standard** brain, the one most laptops get. A milestone's final check
also runs Light and Pro. Spending one brain per day keeps each run to about an hour of
GitHub's machines.
