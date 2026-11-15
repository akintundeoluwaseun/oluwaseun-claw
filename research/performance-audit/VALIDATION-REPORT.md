# S-CLAW — validation and product-quality report

> **SUPERSEDED by FINAL-REPORT.md**, which adds the architecture section and
> the Windows validation requirements, and carries the final decision on the
> simple-action band. This document is kept because its measurements are the
> record they were taken as; where the two differ, the final report is right.
> One claim here was overtaken: §7's "`min_work_after_planning_s` went 15 →
> 25" was **reverted to 15** so the simple band stays a 30 second band. See
> FINAL-REPORT.md §5.1.

What was asked for, what was measured, and what is still unknown.

Every measurement below was taken against a **real `llama-server`** (built
from source, version 1.0.0-dev, build 1, commit a956a85) serving
**Qwen3.5-2B Q4 on four CPU cores**, started with **S-CLAW's own production
flags** (`--api-key`, `-c 8192`, `-t 4`, `--jinja`, `--no-webui`,
`--parallel 1`), and driven through a **real uvicorn backend** rather than a
test client. **It is all Linux. None of it is a Windows result.**

---

## 1. Windows production validation — PARTIAL, and not a pass

**What was done.** The runtime was exercised against real `llama-server`
rather than `llama-cpp-python`, which turned out to matter more than
anything else in this audit (§2). Grammar-constrained generation was
re-verified under production flags: `ACTION_SCHEMA`,
`ACTION_SCHEMA_FOR_MODEL`, `ModelPlan` and the stripped plan schema all
returned HTTP 200 with the server alive afterwards. **The 42KB grammar
concern is a `llama-cpp-python` converter problem, not a real
`llama-server` one** — the earlier segfault does not reproduce on the engine
Claw actually ships.

The complete application path was traced end to end: model startup, routing,
planning, tool execution and error recovery (§3, §5).

**What was NOT done, and cannot be claimed.** No Windows machine was
available. `llama-server.exe` was never run. Eleven new tests
(`test_windows_engine_launch.py`) drive `LlamaServer._start` with
`sys.platform` reporting `win32`, intercept `subprocess.Popen` and assert on
the command line and process options Claw would really have used — no
`preexec_fn` (it raises on Windows), no `LD_LIBRARY_PATH`, the job object,
no console window, running from the engine's own directory. **Those verify
Claw's decisions, not that `llama-server.exe` behaves like the Linux build.**

One Windows-specific risk was found and is worth acting on: `scripts/setup.ps1`
fetches **the newest llama.cpp Windows build at install time**, so the engine
version is not reproducible. The fix in §2 depends on `chat_template_kwargs`,
which an older build will reject. Claw now detects that refusal, falls back
safely, and **logs it** — because it predicts the next failure rather than
causing one.

**Verdict: production readiness on Windows is NOT established.**

---

## 2. The central finding: the brain never stopped thinking

S-CLAW's long-standing "gets stuck thinking without producing a useful
response" complaint is real. It was reproduced deterministically, and it was
never a tuning problem.

"What is the capital of France?" through the chat prompt, temperature 0:

| `max_tokens` | time | `finish_reason` | `content` | `reasoning_content` |
|---|---|---|---|---|
| 512  |  38.2s | length | **0 ch** | 1977 ch |
| 1024 |  82.7s | length | **0 ch** | 4006 ch |
| 1536 | 127.1s | length | **0 ch** | 5995 ch |
| 2048 | 160.7s | length | **0 ch** | 7859 ch |

The model never answered — at any budget. The reasoning grows to fill
whatever it is given. **This disproves an earlier conclusion of my own:** the
1536 → 1024 token reduction made earlier in this audit was not the cause (it
fails identically at 2048) and raising the limit cannot be the cure.

`llama-server` returns a thinking model's chain of thought in a separate
`reasoning_content` field, so all of this arrived as HTTP 200 with `content`
empty. **`llama-cpp-python` does not split the two — which is why five
earlier phases of this audit measured the planner as working.** It inlines the
monologue into `content`, where `jsonfix` digs the JSON out from after it.

Three remedies were measured:

| request | time | finish | `content` |
|---|---|---|---|
| as shipped | 72.1s | length | **0 ch — no answer at all** |
| `enable_thinking: false` | **1.4s** | stop | **correct** |
| `reasoning_format: "none"` | 81.5s | length | 4014 ch of raw `<think>` |

`reasoning_format: none` looks like a fix and is not: it leaves thinking on
and inlines the monologue into the reply **the person reads**. It is now
tested against.

### The planner, on the held-out 16

| mode | usable plan | right capability | total | median |
|---|---|---|---|---|
| thinking **ON** (as shipped) | **2/16** | **2/16** | 2330s | 162.0s |
| thinking **OFF** | **16/16** | **14/16** | 226s | 15.7s |

**Seven times faster and seven times more accurate at once** — possible only
because the failure is total, not slow. Fourteen of sixteen generated their
whole 1024-token budget twice and filed every token under `reasoning_content`.
Confirmed arithmetically: 2 × 1024 ÷ 13.0 tok/s = 158s against 150–170s
measured, i.e. both attempts ran to the length limit every time.

**Shipped:** `thinking=False` on every model call — planner, executor,
replan, both tool lanes, and the brain self-test. Everywhere rather than lane
by lane, because with a total failure mode there is no speed-versus-care
trade. `test_every_lane_stops_thinking.py` walks the package's AST and checks
every `.chat(...)` call, because the bug is silent and has already hidden
from five phases.

---

## 3. End-to-end performance, by task shape

| category | n | completed | median wall | router | planning | generation |
|---|---|---|---|---|---|---|
| conversation | 7 | **7** | **1.8s** (max 4.1s) | 0.00s | 0.0s | 1.6–3.9s |
| simple action (1-step plan) | 8 | 6 | 33.9s | 0.00s | 9–14s | 9.6–24.9s |
| complex task (multi-step) | — | correct answer in 99.9s, 4 steps, moderate band | | | |

Conversation was previously *never answering*, then falling through to 90s of
planning. Canned replies cost 0.0s. Routing and model selection are free at
this resolution — **the cost is output tokens at ~13 tok/s, and nothing else**.

A caution against my own numbers: my first end-to-end harness ran the complex
task with a bare `sales.csv` and no folder, so those two failures were my
bug, not the application's. They are excluded.

---

## 4. Reliability

| check | result |
|---|---|
| ten repeated conversations | all completed; RSS 65 → 71.6MB; median 1.5s, last three 1.3/1.3/1.5s |
| six different tasks in a row | **none refused as busy**, none hung |
| interrupt, then carry on | cancel accepted, task reached `cancelled`, next task ran in 1.3s, nothing left mid-flight |
| brain dies, then returns | **failed in 0.3s** instead of hanging; recovered in 1.3s |

**The `TaskBusy` cascade is gone.** One stuck conversation used to hold the
single-task runner for 90s, after which every following task was refused;
six consecutive tasks now run without a refusal. No memory leak over ~20
tasks, no latency drift, and no row left in `planning`/`running` to show as a
spinner that never clears.

Not hidden by that pass: **two of the six came back `incomplete` at ~32s** —
the simple-band limit in §6, not a reliability fault, but it is what a person
would actually notice.

---

## 5. Model specialisation — **NOT TESTED**

A second model was never available. No conclusion is drawn and none is
invented.

---

## 6. Final engineering review: eight commits as one change

Six defects, none introduced by any single commit.

1. **The planner's model call was never bounded by the task deadline.** The
   executor wrapped each of its calls in the time remaining; `make_plan` did
   not. Planning was inside the budget only *arithmetically* — one call could
   run for the adapter's own 600s timeout and spend a whole ten-minute task,
   after which the clock was checked for the first time and the task reported
   running out of time having started nothing. Expiry during planning is now
   `incomplete`, not "the model did not produce a usable plan".

2. **The conversation lane tightened the task's clock, not its own call.** A
   failed chat reply may fall through to real work, and that work inherited
   the 15-second conversation budget; planning alone takes ~20s, so it expired
   the instant it began. Confirmed by reintroducing the bug and watching the
   new test fail.

3. **The fast lanes reported no timings at all.** Five gates carried drifted
   copies of the same closing statements, and every lane that answers
   *without* working returned before `emit("timings")`. Conversation — one of
   the three things asked to be measured separately — was the one path
   measuring nothing.

4. **`/tasks/plan` was unbounded while the desktop waits fifteen minutes for
   it** (`desktop/src/backend.js` marks it "slow"), and it had never received
   the enumeration fix the runner got. That is the stuck loading indicator,
   hiding in the one route generous enough to conceal it.

5. **The executor's safety net had a hole.** `ModelAction.tool` must be
   optional, because a "finish" has no tool, so the flat schema **permits
   `{"action":"tool"}` with nothing to call** — and the constrained retry
   could therefore serve the same invalid reply again. "action 'tool' needs a
   tool name" was the commonest rejection in both runs. Four read-only tasks
   went **0/4 → 2/4** from the schema fix alone.

6. **A duplicated ceiling.** `_MODEL_CALL_CEILING_S` had been written out
   twice; now defined once and imported.

### A change that was measured and rejected

Four tasks suggested constraining the executor's first attempt (3/4 vs 2/4).
Eight reversed it:

| | completed | median wall | generation | calls | rejections |
|---|---|---|---|---|---|
| free first (kept) | **5/8** | 35.5s | **209.4s** | **21** | 9 |
| constrained first | 4/8 | 31.3s | 341.1s | 28 | 1 |

Constraining takes rejections from 9 to 1 and still loses, by 63% more
generation and a worse completion rate: the model satisfies the grammar with
a **valid but wrong** action and repeats it — one run spent nine calls and 98
seconds reaching "3 steps failed in a row". **The only reason the wrong change
was not shipped is that the sample was widened first.** An experiment toggle
that briefly reached a commit has been removed.

Both lanes now agree and both are measured: a free first attempt with the
grammar as the net under it, never the opening move.

---

## 7. Known limitations, measured and left open

- **The simple band is knife-edge on a 2B, and is kept at 30 seconds.**
  `min_work_after_planning_s` was tried at 25, taking the eight tasks from
  5/8 to 6/8, and then **reverted to 15**: at 25 the floor binds at ordinary
  planning times and quietly turns "a 30 second simple action" into "30
  seconds *after* planning", which is a different promise. The floor is a
  rescue for a pathological plan (19.6s measured once), not an allowance for
  an ordinary one. The measured cost of the honest 30s is that a one-step task
  which must plan can time out with nothing done. The right fixes are to stop
  paying for planning the task does not need, or to raise `simple_deadline_s`
  deliberately — a decision about how long someone will wait, and so theirs.
- **Tier B is narrower than it looks.** It rests on `fitting_tools`, whose
  `_FITTING` list is a deliberately narrow set of patterns for surfacing
  *specialist* tools ("9:16 version", "black frames", "broken links"). So it
  fires for "Open Notepad" but not for "List the files in X", which therefore
  pays full planning. Not a matcher bug — it was never general — but it bounds
  what tier B can save.
- **One-step action cost varies more than a floor can absorb**: 9.6s of
  generation one run, 24.9s the next, for the same task.

---

## 8. Tests

    1791 passed, 15 skipped, 0 failed    (8m57s, full suite)

The 1,726 that had to be preserved are preserved; 65 net new tests were
added. The ones worth naming:

- `test_every_lane_stops_thinking.py` — walks the package's AST and checks
  **every** `.chat(...)` call. Structural because the bug is silent: a new
  lane added without the flag does not raise, it quietly answers nothing
  after eighty seconds. It has already hidden from five phases.
- `test_windows_engine_launch.py` — drives `LlamaServer._start` with
  `sys.platform` reporting `win32` and asserts on the real command line.
  The one that matters pins `--jinja` on **both** platforms: `llama-server`
  can only honour `chat_template_kwargs` by passing it to the model's own
  Jinja template, so dropping that flag would not look like a flag change —
  it would look like the conversation lane silently going back to answering
  nothing.
- `test_action_schema_shape.py` — the replies that used to get through
  (`{"action":"tool"}` with no tool, a finish with nothing to say) no longer
  fit the schema the model is shown. Checked by hand rather than with a JSON
  Schema library, so it adds no dependency for one assertion.
- `test_router_phases.py` — every lane reports its timings, the phases never
  double-count, and a failed chat reply leaves the task its full budget. The
  last of those was confirmed to fail with the bug reintroduced.
- `test_the_floor_binds_once_planning_is_slow_and_the_cost_is_known` — states
  the §7 arithmetic so the trade cannot drift silently.

Five test files needed their model-adapter doubles updated to accept the
`thinking` keyword. They failed with `TypeError`, which is the correct
failure: the interface genuinely changed and the doubles had not.
