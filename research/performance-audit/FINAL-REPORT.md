# S-CLAW — final technical report

**Milestone:** intelligence, performance, reliability and architecture audit.
**Status:** complete. Codebase clean, tested and documented.
**Windows production validation: PARTIAL** — see §6. It must stay PARTIAL
until exercised on a real Windows machine against `llama-server.exe`.

Every measurement in this report was taken against a real `llama-server`
(built from source, version 1.0.0-dev, build 1, commit a956a85) serving
**Qwen3.5-2B Q4 on four CPU cores**, started with S-CLAW's own production
flags (`--api-key`, `-c 8192`, `-t 4`, `--jinja`, `--no-webui`,
`--parallel 1`), driven through a real uvicorn backend. **All of it is
Linux.** Nothing here is a Windows result.

---

## 1. Architecture as it now stands

### 1.1 The stack

    Electron 45 desktop app
      └── HTTP on 127.0.0.1, per-launch session token
            └── Python 3.13 / FastAPI backend          claw/api/app.py
                  ├── TaskRunner  (one task at a time) claw/agent/runner.py
                  ├── Planner                          claw/agent/planner.py
                  ├── Executor                         claw/agent/executor.py
                  ├── Tool registry                    claw/tools/
                  ├── Permission policy                claw/permissions/
                  └── Model adapters                   claw/models/
                        └── llama.cpp llama-server     claw/runtime/engine.py
    SQLite for tasks, events, threads and memory
    Playwright/Chromium for the browser, pywinauto/UIA for the desktop

### 1.2 The router: six gates before any work

`TaskRunner._run` decides what a message *is* before waking the brain. In
order, and each returns outright:

| gate | cost | what it answers |
|---|---|---|
| `persona.self_answer` | none | "who are you?" from IDENTITY.md |
| `conversation.quick_reply` | none | greetings, thanks — canned |
| `looks_like_bare_path` | none | a pasted folder: list it |
| `is_conversation` | one short model call | ordinary talk |
| `constraints.conflict_question` | none | a self-contradicting request |
| plan + execute | the rest | actual work |

All five answering gates now share one `answered()` helper, so every lane
reports its own timings; `close_router()` stops the router's clock before any
model call, so the phases stay additive and comparable with the wall clock.

### 1.3 Tiers

- **Tier A** — the free gates above.
- **Tier B** — `simple_action.single_action`: one obvious action, plan
  synthesised locally with **no model call**. Deliberately strict and
  one-sided: treating a multi-step job as one action is a confident wrong
  answer, while treating a simple action as complex costs only the planning
  call it costs today. Rests on `fitting_tools`, which is a narrow matcher
  for *specialist* tools — see §5.
- **Tier C/D** — plan, then execute step by step, with replanning.

### 1.4 One clock per task

`claw/agent/deadline.py`. Started before the router, never reset. It bounds
planning, every model call, every tool, every retry and every replan.

- A model call is an HTTP request and is safely cut off: it gets the time
  remaining, capped at `MODEL_CALL_CEILING_S` (defined once, in the executor,
  imported by the planner).
- A **tool is never interrupted** — it may be halfway through writing a file.
  The deadline stops the *next* one starting.
- Expiry returns `incomplete` with the steps that finished, the step it was
  on and the reason. Nothing is rolled back and nothing claims it was.

Bands, chosen from the plan's step count and only ever **lowered**:
conversation 15s (bounds the *call*), simple 30s, moderate 180s, complex
600s, extended 1800s (explicitly requested per task, never inferred).

### 1.5 Per-phase diagnostics

`claw/agent/timings.py` — `router`, `selection`, `planning`, `generation`,
`tools`, `retry`, plus `total_s` and a named `unmeasured_s` remainder.
Deliberately not nested, so the sum is comparable with the wall clock. A task
finishing inside its deadline proves nothing about efficiency; this is how
that claim is actually checked.

---

## 2. The central fix: `content` versus `reasoning_content`

**The single most consequential finding of the audit, and the explanation for
problems previously attributed to performance.**

A thinking model emits its reasoning and then its answer. What becomes of the
reasoning depends on the **server**, not the model:

- **`llama-server`** (what Claw ships) parses it into a separate
  `reasoning_content` field. If the model never finishes thinking, `content`
  is an **empty string** and the reply still arrives HTTP 200 with
  `finish_reason: "length"`.
- **`llama-cpp-python`** does not split them. The monologue lands in
  `content`, where `jsonfix` digs the JSON out from after it — and everything
  appears to work.

Measured, chat prompt, temperature 0, "What is the capital of France?":

| `max_tokens` | time | finish | `content` | `reasoning_content` |
|---|---|---|---|---|
| 512 | 38.2s | length | **0 ch** | 1977 ch |
| 1024 | 82.7s | length | **0 ch** | 4006 ch |
| 1536 | 127.1s | length | **0 ch** | 5995 ch |
| 2048 | 160.7s | length | **0 ch** | 7859 ch |

The model never answered — not slowly, never, at any budget. Two conclusions
follow, and **both correct earlier conclusions of this audit**: raising
`max_tokens` cannot fix it, and the earlier 1536 → 1024 reduction neither
caused nor cured it.

### Remedies measured

| request | time | finish | `content` |
|---|---|---|---|
| as shipped | 72.1s | length | **0 ch — no answer at all** |
| `enable_thinking: false` | **1.4s** | stop | **correct** |
| `reasoning_format: "none"` | 81.5s | length | 4014 ch of raw `<think>` |

`reasoning_format: none` looks like a fix and is the opposite: it leaves
thinking on and puts the monologue in front of the person. It is tested
against.

### The planner, held-out 16

| mode | usable plan | right capability | total | median |
|---|---|---|---|---|
| thinking **ON** (as shipped) | **2/16** | **2/16** | 2330s | 162.0s |
| thinking **OFF** | **16/16** | **14/16** | 226s | 15.7s |

Seven times faster *and* seven times more accurate — possible only because
the failure is total rather than slow. Confirmed arithmetically: 2 × 1024 ÷
13.0 tok/s = 158s against 150–170s measured, i.e. both attempts ran to the
length limit every time.

### How the regression is prevented from returning

1. **Canonical documentation** at the top of `claw/models/openai_compat.py`:
   the two server behaviours, the measurement table, and three rules — ask
   the template not to think; never use `reasoning_format: none`; never read
   `reasoning_content` into a reply (it is the model's private working, it is
   not addressed to the person, and on the planner and executor lanes it is
   not valid JSON either). It is read in exactly one place, to *explain* an
   empty answer, and never returned.
2. **`_why_it_said_nothing`** turns an empty reply into one of four
   actionable sentences instead of a mystery.
3. **`tests/test_every_lane_stops_thinking.py`** walks the package's AST and
   checks **every** `.chat(...)` call. Structural because the bug is silent: a
   new lane added without the flag does not raise, it quietly answers nothing
   after eighty seconds.
4. **`tests/test_windows_engine_launch.py`** pins `--jinja` on both
   platforms. `llama-server` can only honour `chat_template_kwargs` by passing
   it to the model's own Jinja template, which it does only under that flag.
   Removing it would not look like a flag change; it would look like Claw
   silently going back to answering nothing.
5. **`tests/test_thinking_switch.py`** forbids `reasoning_format`, and proves
   the per-engine fallback is learned once rather than every call.
6. **Both adapters share one explanation.** `why_a_reply_was_empty` lives in
   `claw/models/base.py` so the two cannot drift. The Ollama adapter had the
   same hole and it is now closed: an empty `content` is a `str`, so it passed
   the type check and was returned *as if it were an answer*, and the caller
   then failed on something that looked like malformed JSON — sending anyone
   diagnosing it to the wrong place entirely. Ollama files the monologue under
   `thinking` where llama-server uses `reasoning_content`; the one helper
   takes either. `tests/test_empty_reply.py` runs the empty, whitespace-only
   and genuine-answer cases against **both** adapters.

### Where the switch is applied, and why only there

Eight call sites, all text-generation lanes where an empty `content` is
fatal: the chat lane, the planner, the executor's action call, the replan
call, the research tool, two PDF summarisation calls, and the brain
self-test. The self-test earns its place on its own merit — asked with
thinking on it would report a brain as broken that works perfectly for Claw,
which is testing something the app never does.

**Engine appropriateness.** `chat_template_kwargs` is a llama.cpp extension,
so support is **discovered, never assumed**: a server that answers 400 and
names the field sets `quiet_thinking_ok = False` and the request is re-sent
without it. The flag lives on the adapter, and Claw builds one adapter per
task, so the worst case on an unsupported engine is one wasted round trip per
task — a 400 with no generation behind it. It is deliberately *not* cached
globally: the address and model can both change when somebody edits Settings,
and a stale "this engine cannot be asked" would silently leave thinking on,
which is the whole failure this machinery prevents. Ollama's spelling
(`think: false`) is handled the same way. The refusal is **logged**, because
it predicts the next failure.

**One lane is excluded and it is recorded, not hidden.** `see()`, the
screenshot path, neither sends the switch nor rejects an empty reply, so a
*thinking* vision model would return an empty description. No vision model
was available to measure, and an unverified change to a path that cannot be
exercised is worse than a documented gap. The fix is sketched in the
docstring for whoever has one. See §5.

---

## 3. Benchmark evidence

### 3.1 End-to-end, by task shape

| category | n | completed | median wall | router | planning | generation |
|---|---|---|---|---|---|---|
| conversation | 7 | **7** | **1.8s** (max 4.1s) | 0.00s | 0.0s | 1.6–3.9s |
| simple action (1-step plan) | 8 | 6 at floor 25 / 5 at floor 15 | 33.9s | 0.00s | 9–14s | 9.6–24.9s |
| complex task (4 steps) | 1 | 1, correct answer | 99.9s | 0.00s | 14.5s | 85.4s |

Conversation was previously *never answering*, then falling through to 90s of
planning. Canned replies cost 0.0s. **Routing and model selection are free at
this resolution — the cost is output tokens at ~13 tok/s and nothing else.**

### 3.2 Grammar-constrained generation

Under production flags, `ACTION_SCHEMA`, `ACTION_SCHEMA_FOR_MODEL`,
`ModelPlan` and the stripped plan schema all returned HTTP 200 with the server
alive afterwards. **The 42KB-grammar concern is a `llama-cpp-python` converter
problem, not a real `llama-server` one** — the earlier segfault does not
reproduce on the engine Claw ships.

### 3.3 Reliability

| check | result |
|---|---|
| ten repeated conversations | all completed; RSS 65 → 71.6MB; median 1.5s, last three 1.3/1.3/1.5s |
| six different tasks in a row | **none refused as busy**, none hung |
| interrupt, then carry on | cancel accepted, task reached `cancelled`, next task ran in 1.3s, nothing left mid-flight |
| brain dies, then returns | **failed in 0.3s** instead of hanging; recovered in 1.3s |

**The `TaskBusy` cascade is gone.** One stuck conversation used to hold the
single-task runner for 90s, after which every following task was refused.
`busy` derives from the asyncio task's own state, so it self-clears even when
`_run` crashes — the cascade was genuine serialisation behind the stall, not a
leaked flag.

### 3.4 A change that was measured and rejected

Four tasks suggested constraining the executor's **first** attempt (3/4 vs
2/4). Eight reversed it:

| | completed | median wall | generation | calls | rejections |
|---|---|---|---|---|---|
| free first (**kept**) | **5/8** | 35.5s | **209.4s** | **21** | 9 |
| constrained first | 4/8 | 31.3s | 341.1s | 28 | 1 |

Constraining takes rejections from 9 to 1 and still loses, by 63% more
generation and a worse completion rate: the model satisfies the grammar with a
**valid but wrong** action and repeats it — one run spent nine calls and 98
seconds reaching "3 steps failed in a row". The only reason the wrong change
was not shipped is that the sample was widened first. Both lanes now agree and
both are measured: a free first attempt, with the grammar as the net under it,
never the opening move.

---

## 4. The six defects found reviewing the commits as one change

All six verified resolved against the code as it now stands.

| # | defect | resolution | evidence |
|---|---|---|---|
| 1 | The planner's model call was never bounded by the task deadline — planning was inside the budget only *arithmetically*, so one call could run for the adapter's own 600s timeout and spend a whole ten-minute task, after which the clock was checked for the first time and the task reported running out of time having started nothing. | `make_plan` takes the deadline, cuts the call off at the time remaining, starts no attempt on an expired budget, and expiry raises `DeadlineReached` → reported **`incomplete`**, not "the model did not produce a usable plan". | `test_task_deadline.py` (4 tests) |
| 2 | The conversation lane tightened the **task's** clock to 15s; a failed chat reply may fall through to real work, and that work inherited 15s while planning alone takes ~20s, so it expired the instant it began. | The bound moved to the **call** (`adapter.timeout_s`), leaving the task clock intact. | `test_a_failed_chat_reply_leaves_the_task_its_full_budget` — confirmed to fail with the bug reintroduced |
| 3 | The fast lanes reported no timings at all: five gates carried drifted copies of the same closing statements, and every lane answering *without* working returned before `emit("timings")`. Conversation — one of three things asked to be measured separately — was the one path measuring nothing. | One `answered()` helper for all five gates; `close_router()` closes the router's clock before any model call so phases stay additive. | `test_router_phases.py` (5 tests) |
| 4 | `/tasks/plan` was unbounded while the desktop waits **fifteen minutes** for it (`desktop/src/backend.js` marks it "slow"), and it had never received the enumeration fix the runner got. | Bounded by the moderate band; expiry answers **504 `planning_timed_out`** saying it was a time limit; now sends the same `tools_note`. | `test_plan_route_gates.py` (2 tests) |
| 5 | The executor's safety net had a hole: `ModelAction.tool` must be optional because a "finish" has no tool, so the flat schema **permitted `{"action":"tool"}` with nothing to call** — and the constrained retry could therefore re-serve the same invalid reply. It was the commonest rejection in both runs. | The model-facing schema states the two actions as alternatives with their own required fields: a tool action must name a tool, a finish must say something. `ModelAction` untouched and still validates. **0/4 → 2/4** from this fix alone. | `test_action_schema_shape.py` (8 tests) |
| 6 | A duplicated `_MODEL_CALL_CEILING_S`, written out in both the executor and the planner. | Defined once as `MODEL_CALL_CEILING_S` in the executor and imported. | verified by inspection |

---

## 5. Known limitations

1. **The simple band is genuinely tight on a 2B, and is kept at 30s.** A
   one-step task that must *plan* spends 9–14s planning and can time out with
   nothing done ("List every file and count it", "Make a file hello.txt").
   `min_work_after_planning_s` was tried at 25, which rescued one of them —
   and **reverted to 15**, because at 25 the floor binds at ordinary planning
   times and quietly turns "a 30 second simple action" into "30 seconds
   *after* planning". That is a different promise. The floor is a rescue for
   a pathological plan (19.6s was measured once), not an allowance for an
   ordinary one. The right fixes are to stop paying for planning the task does
   not need, or to raise `simple_deadline_s` deliberately — the latter is a
   decision about how long someone will wait, and belongs to the user.
   `test_a_simple_action_keeps_its_thirty_second_band` stops the floor
   drifting back.
2. **Tier B is narrower than it appears.** It rests on `fitting_tools`, whose
   `_FITTING` list is a deliberately narrow set of patterns for surfacing
   *specialist* tools ("9:16 version", "black frames", "broken links"). So it
   fires for "Open Notepad" (9.8–16.7s, a third of the band) but not for
   "List the files in X", which therefore pays full planning. Not a matcher
   bug — it was never general — but it bounds what tier B can save, and
   widening it would change `tools_note` and so must be benchmarked against
   the held-out set.
3. **One-step action cost varies more than a floor can absorb**: 9.6s of
   generation one run, 24.9s the next, for the same task.
4. **The vision path (`see`) is unverified** for this class of failure: it
   neither sends the thinking switch nor rejects an empty reply. Recorded in
   its docstring with the fix sketched. No vision model was available.
5. **Model specialisation: NOT TESTED.** A second model was never available.
   No conclusion is drawn and none is invented.
6. **A 2B is the floor, not the target.** Accuracy figures (14/16 capability
   selection) are this model's, not the architecture's ceiling.

---

## 6. Windows validation requirements — status PARTIAL

**This section must remain PARTIAL until the work below is done on a real
Windows machine against `llama-server.exe`.**

### What has been done

- The runtime was exercised against real `llama-server` rather than
  `llama-cpp-python` — which mattered more than anything else in this audit.
- Grammar-constrained generation re-verified under production flags (§3.2).
- Eleven tests (`test_windows_engine_launch.py`) drive `LlamaServer._start`
  with `sys.platform` reporting `win32`, intercept `subprocess.Popen` and
  assert on the real command line and process options: `--jinja` present,
  loopback host, API key, `--no-webui`, no `preexec_fn` (it raises on
  Windows), no `LD_LIBRARY_PATH`, the job object, no console window, and
  running from the engine's own directory.
- Windows filename handling and engine exit codes were already covered
  (`test_filenames_work_on_windows.py`, `test_engine_exit.py`).

### What those tests do NOT establish

They verify **Claw's decisions**, not that `llama-server.exe` behaves as the
Linux build does. No Windows machine was available and the Windows engine was
never started.

### Required to move PARTIAL → VALIDATED

1. **Engine startup.** Run `scripts/setup.ps1`, confirm
   `backend\runtime\llama\VERSION.txt` and that `llama-server.exe --version`
   runs. Record the llama.cpp release actually fetched.
2. **The thinking switch, which the whole fix depends on.** POST
   `/v1/chat/completions` with `chat_template_kwargs: {"enable_thinking":
   false}` and confirm a **non-empty `content`**. If the build answers 400,
   Claw's fallback keeps working but **thinking stays on and the bug
   returns** — so this is the single highest-priority Windows check.
   `setup.ps1` fetches whichever build was newest at install time, so the
   version is not reproducible and an older installation can land here.
   Claw logs the refusal; check the log.
3. **Grammar.** Repeat §3.2 against `llama-server.exe` — all four schemas,
   expecting HTTP 200 and a live server afterwards.
4. **The three task shapes**, as §3.1: a conversation, a tier-B action
   (`Open Notepad` — a real Windows app, which Linux cannot exercise), and a
   multi-step task. Compare per-phase timings; Windows CPU scheduling and
   Defender may change generation throughput.
5. **Reliability**, as §3.3, plus two Windows-only concerns: the job object
   really kills the engine when the backend dies, and the engine's DLLs
   resolve from its own directory.
6. **Desktop automation**, which Linux cannot test at all: pywinauto/UIA
   against real windows, `launch_app`, `type_text`, `press_keys`, the
   clipboard, and screenshots.
7. **The simple band on real hardware.** §5.1 is measured on four CPU cores
   at ~13 tok/s. Re-measure planning and action cost on the target machine
   before deciding whether `simple_deadline_s` needs raising.

Until all seven are done and recorded, **Windows remains PARTIAL**.

---

## 7. Tests

    1791 passed, 15 skipped, 0 failed    (full suite)

The 1,726 that had to be preserved are preserved, with 65 net new tests. Five
test files had their model-adapter doubles updated to accept the `thinking`
keyword; they failed with `TypeError`, which is the correct failure — the
interface genuinely changed and the doubles had not.

## 8. Housekeeping

- No experimental environment variables remain. The package reads only
  pre-existing configuration (`CLAW_DATA_DIR`, `CLAW_LLAMA_SERVER`,
  `CLAW_PORT`, platform paths and so on); this audit added none. A
  `CLAW_EXPERIMENT_CONSTRAIN_FIRST` toggle briefly reached one commit while
  §3.4 was being measured and has been removed — an env var that changes
  production behaviour has no business shipping.
- No temporary benchmark settings in production code. All benchmark harnesses
  live outside the package, under the session scratchpad.
- Two measurements of my own were retracted during this phase rather than
  defended: an end-to-end harness that ran the complex task with no folder
  (my bug, excluded), and the four-task executor result that the eight-task
  run reversed.
