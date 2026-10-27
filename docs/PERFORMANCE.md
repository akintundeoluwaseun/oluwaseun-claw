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
| `build_registry()` (66 tools) | 0.0–0.1 ms |
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
- **Inference latency.** No model has ever answered, in either edition, so
  tokens per second is unknown. It will dominate every number on this page.
- **The interface.** Render time, first paint and input latency need Electron,
  which cannot run here: the binary comes from GitHub releases, which this
  container's egress policy refuses.
- **Large documents.** PDFs and OCR were not benchmarked; OCR is likely the
  slowest thing Claw does and deserves its own pass.
- **Memory over hours.** Idle was sampled for 10 seconds, which says nothing
  about a leak over a working day.
