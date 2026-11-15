# Performance

Measured 27 October 2026 with `scripts/benchmark.py`, which is in the repository
so any figure here can be reproduced or contradicted:

```
backend/.venv/bin/python scripts/benchmark.py --runs 7 --json bench.json
```

It adds no dependencies — memory comes from `/proc`, processor time from
`/proc/<pid>/stat`, import costs from `python -X importtime`. Every figure is
the **median of several runs**, with the spread shown, because one timing on an
unnamed machine is not a measurement.

## The machine

| | |
|---|---|
| CPU | Intel Xeon @ 2.80 GHz, 4 cores |
| Memory | 15.7 GB |
| OS / Python | Linux 6.18 (container) / CPython 3.13.17 |

**This is not a Windows laptop.** Start-up on Windows will differ — Defender
scans a frozen executable, and the PyInstaller bundle unpacks before Python even
starts. These numbers are a baseline to compare against, not a promise about
your machine. The same script run on Windows produces the comparable set.

## What it measures, and what it found

### Cold start — launch to the backend answering

**643 ms** median, 617–746 ms, 54.9 MB resident.

That is the wait before Claw can accept a word. Where it goes:

| Package | Cumulative import |
|---|---|
| fastapi | ~335 ms |
| asyncio | ~61 ms |
| httpx | ~48 ms |
| pydantic + pydantic_core | ~58 ms |

FastAPI is half the launch and is not removable: it is the API. Nothing else is
large enough to be worth contorting the code for.

### The tools, on real files

A 1 MB text file and a folder of 300 files — ordinary sizes, not toy ones.

| Tool | Before | After | |
|---|---|---|---|
| `count_text` (1 MB) | 80.2 ms | **22.2 ms** | 3.6× faster |
| `search_in_file` (1 MB) | 34.6 ms | 21.5 ms | |
| `compare_files` (1 MB × 2) | 32.8 ms | 36.0 ms | unchanged (noise) |
| `read_file` (1 MB) | 1.8 ms | 1.1 ms | |
| `find_files` (300 files) | 3.6 ms | 4.2 ms | unchanged (noise) |
| `list_folder` (300 files) | 2.3 ms | 3.5 ms | unchanged (noise) |
| `is_program_running` | 9.8 ms | 11.1 ms | reads the real process list |
| `disk_space` | 0.4 ms | 0.4 ms | |
| `current_time` | 0.0 ms | 0.0 ms | |

### Idle

**0.03 s of processor time over 10 s — 0.3% of one core**, 54.9 MB resident,
with no task running. A background process that costs nothing is the point: on
a laptop this is battery.

### In-process

| | |
|---|---|
| `build_registry()` (147 tools) | 0.06 ms (re-measured 15 Nov; 66 tools then, 147 now) |
| `create_app()` | ~11 ms |
| `GET /health`, `/settings`, `/edition`, `/tasks`, `/models/status` | ~6 ms each |

## The two changes made, and what each actually bought

### 1. `count_text` — a real 3.6× win

The profile pointed at one line: counting non-space characters with a
per-character generator, 76 ms of the 80 ms. `len("".join(text.split()))` is the
same answer — `str.split()` splits on any whitespace — and does the work in C.

**80.2 ms → 22.2 ms on a megabyte.** The test that asserts the count still
compares against the original per-character sum, so the two cannot drift apart.

### 2. Pillow out of start-up — memory, not speed

Pillow was imported by the tool registry at launch, so every session paid for it
even though most never touch an image. `claw/integrations/pillow.py` loads it on
first use instead.

`-X importtime` attributed **424 ms** to Pillow and predicted a large win.
Measured end to end, cold start went from 656 ms to 643 ms — **within the
spread, so no measurable speed improvement at all.** The profile was misleading
because repeated launches find the compiled extensions in the page cache; the
first launch after a reboot pays more, and that is the case this helps.

What it did buy, consistently: **58.9 MB → 54.9 MB resident**, about 4 MB.

The honest summary of this one: the change is still right — a program should not
load what it does not use — but it is a memory change, not a speed change, and
reporting it as a 424 ms saving would have been false.

## What has not been measured

- **Windows.** Every figure here is Linux. Defender, the frozen executable and
  the unpack step are not represented.
- ~~**Inference latency.** No model has ever answered...~~ **Measured on 15
  November 2026 — see "The brain, measured" below.** It does dominate every
  number on this page: ~13 tokens a second on this machine, and output tokens
  are the only cost that matters. Everything above is noise beside it.
- **The interface.** Render time, first paint and input latency need Electron,
  which cannot run here: the binary comes from GitHub releases, which this
  container's egress policy refuses.
- **Large documents.** PDFs and OCR were not benchmarked; OCR is likely the
  slowest thing Claw does and deserves its own pass.
- **Memory over hours.** Idle was sampled for 10 seconds. Twenty real tasks
  were since measured (65 → 71.6 MB resident, below), which is better evidence
  but still says nothing about a working day.


---

# The brain, measured — 15 November 2026

Everything above this line is the application without a model. This section is
the part that actually decides what using Claw feels like, and until now it had
never been measured because no model had ever answered.

Full detail, including every negative result, is in
`research/performance-audit/FINAL-REPORT.md`.

## The machine and the engine

| | |
|---|---|
| Engine | llama.cpp `llama-server` 1.0.0-dev, build 1, commit a956a85 |
| Flags | Claw's own production argv: `--api-key`, `-c 8192`, `-t 4`, `--jinja`, `--no-webui`, `--parallel 1` |
| Brain | Qwen3.5-2B Q4, 4 CPU cores |
| Throughput | **~13 tokens/second generating**, prefill ~165 tok/s (paid once, prefix reuse) |
| Driven through | a real uvicorn backend, not a test client |

**Still Linux.** No Windows figure on this page is a Windows figure.

## The one number that matters: output tokens

At ~13 tok/s, **a reply's length is its cost**, and nothing else on this page
is within an order of magnitude. Routing and model selection measured 0.00s.
Prompt size barely matters — prefill is twelve times faster than generation and
is reused. So the way to make Claw faster is to make it say less, or not wake
the brain at all.

That is what the router is for:

| lane | cost |
|---|---|
| canned reply ("hi", "thanks") | **0.0s** — no model |
| a pasted folder path | milliseconds — no model |
| tier B, one obvious action | no planning call at all |
| ordinary conversation | one short call |
| real work | planning + a call per step |

## End to end, by task shape

| category | n | completed | median wall | router | planning | generation |
|---|---|---|---|---|---|---|
| conversation | 7 | **7** | **1.8s** (max 4.1s) | 0.00s | 0.0s | 1.6–3.9s |
| simple action (1-step plan) | 8 | 5 | 33.9s | 0.00s | 9–14s | 9.6–24.9s |
| complex task (4 steps) | 1 | 1, correct | 99.9s | 0.00s | 14.5s | 85.4s |

Per-phase figures come from each task's own `timings` event, so any of this can
be reproduced or contradicted from the app itself rather than taken on trust.

## The thinking-model trap, which dominated everything

Before this was found, a conversation **never answered at all**. The cause was
not speed:

| `max_tokens` | time | finish | answer |
|---|---|---|---|
| 512 | 38.2s | length | **0 characters** |
| 1024 | 82.7s | length | **0 characters** |
| 1536 | 127.1s | length | **0 characters** |
| 2048 | 160.7s | length | **0 characters** |

A thinking brain filled whatever budget it was given with reasoning and never
reached an answer. Asking the chat template not to think answered the same
question in **1.4s**. On the planner, over sixteen held-out tasks:

| | usable plan | right capability | median |
|---|---|---|---|
| thinking on | **2/16** | **2/16** | 162.0s |
| thinking off | **16/16** | **14/16** | **15.7s** |

Seven times faster and seven times more accurate at once — possible only
because the failure was total rather than slow. Claw now asks every lane not to
think; see `claw/models/openai_compat.py` for the contract and why it must not
be undone.

## Reliability

| check | result |
|---|---|
| ten repeated conversations | all completed; **65 → 71.6 MB** resident; median 1.5s, no drift |
| six different tasks in a row | none refused, none hung |
| interrupt, then carry on | next task ran in 1.3s; nothing left mid-flight |
| brain dies, then returns | **failed in 0.3s** instead of hanging; recovered in 1.3s |

## Honest limits of this section

- **A 2B is the floor, not the target.** 14/16 capability selection is this
  brain's accuracy, not the architecture's ceiling.
- **A one-step task that must plan can time out.** Planning costs 9–14s of a
  30-second simple-action budget. The budget is deliberately left at 30s; see
  `FINAL-REPORT.md` §5.1.
- **Model specialisation is NOT TESTED** — only one brain was available.
- **Windows is PARTIAL.** See `docs/WINDOWS_ACCEPTANCE.md`.
