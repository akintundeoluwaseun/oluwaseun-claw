# S-CLAW performance and reliability — diagnosis

Phase 1–3: map the architecture, trace real requests, find root causes.
Everything here was measured on this machine, not inferred.

**Setup.** Real Qwen3.5-2B (Q4, 1.28 GB) served over an OpenAI-compatible HTTP
API on 127.0.0.1:8099, S-CLAW's own backend run as a real uvicorn process on
:8766, driven over real HTTP. 4 CPU cores, 15 GB RAM, temperature 0.

---

## 1. The architecture, as it actually is

A message does **not** enter the planner first. `TaskRunner._run`
(`backend/claw/agent/runner.py`) is the router, and it runs before the brain is
woken:

| # | Gate | Cost | Example |
|---|---|---|---|
| 1 | `persona.self_answer` | 0 model calls | "Who are you?" |
| 2 | `conversation.quick_reply` | 0 model calls | "Hi", "thanks", "what can you do?" |
| 3 | `conversation.looks_like_bare_path` | 0 model calls | a pasted folder path |
| 4 | `conversation.is_conversation` | **1** call, no tools | "What is Python?" |
| 5 | `constraints.conflict_question` | 0 model calls | self-contradicting request |
| 6 | otherwise | **1 planning call + N execution calls** | real work |

So tiers A (conversation) and D (permissions) from the brief already exist and
work. Measured end to end over HTTP:

| message | lane | time | model calls |
|---|---|---|---|
| "Hi" | instant | **0.0 s** | 0 |
| "How are you?" | instant | **0.0 s** | 0 |
| "I" | chat | **4.0 s** | 1 |
| "What is the capital of France?" | chat | **3.1 s** | 1 |
| "What is Python?" | chat | **5.6 s** | 1 |

**Greetings are already instant and cost nothing.** If the installed build is
slow on "Hi", it is an older build: this is current `main`.

### Correction to something I said earlier in this session

My first trace used FastAPI's `TestClient` and showed `"I"` hanging for 600 s.
I reported that as reproducing the reported bug. **It was my harness, not
S-CLAW** — `TestClient`'s portal starves the background task while the test
thread polls. Re-run against a real uvicorn server, `"I"` answers in 4.0 s. The
bug was in my measurement.

### A real gap: tier B does not exist

There is no light path for a simple action. "Open Notepad" takes the same
planning call as "research five companies". That is the brief's tier B, and it
is genuinely missing.

### A real defect: `/tasks/plan` bypasses the router

`POST /tasks/plan` (`backend/claw/api/app.py`) calls `make_plan` directly. None
of the six gates run. The UI uses it only for the "Plan only" button, so "Hi"
typed into the normal box is safe — but "Plan only" on a greeting will plan it.

---

## 2. Where the time actually goes

Measured on the planner call:

- **Prompt processing:** 1,384 prompt tokens → first token in **8.4 s** (~165
  tok/s). Paid once; llama.cpp reuses the prefix, so later calls with the same
  system prompt skip it.
- **Generation:** **~10–13 tokens/second.**

A plan is 141–336 output tokens, so a planning call is 12–33 s, and **almost
all of it is generating output tokens.**

**The lever is output tokens, not input tokens.** This is why the earlier
prompt-shortening experiment failed: the shorter prompt saved input tokens
nobody was paying for, and cost plan quality, which produced *more* steps and
therefore more output.

### What the output is spent on

Four tasks, measured by field:

| field | share of plan output | used by anything? |
|---|---|---|
| `description` | 37.5% | yes — shown, and drives the step |
| **`expected_result`** | **27.4%** | **no — nothing reads it** |
| `goal` | 11.2% | yes — `app.js:597` shows it |
| `risk` | 7.2% | yes — permissions |
| `questions` | 6.3% | yes |
| `capability` | 5.4% | yes — picks the tools |
| `title` | 4.9% | yes — thread title |

`expected_result` is declared in `schemas.py:66`, named in the prompt's JSON
shape, generated for every step of every plan — and **grepping the entire
backend and renderer finds no reader.** It is 27% of planning output, generated
at ~10 tok/s, for nothing.

---

## 3. A promising lead that turned out to be nothing

S-CLAW constrains model output with a JSON schema, which llama.cpp converts to
a GBNF grammar. The `maxLength` limits expand into deeply nested rules:

| schema | grammar as shipped | with `maxLength` removed |
|---|---|---|
| `ModelAction` | **42,081 bytes** | 1,470 bytes (29× smaller) |
| `ModelPlan` | 13,352 bytes | 2,063 bytes (6.5× smaller) |

It looked like a strong suspect. It is not. Measured on the real model, same
prompts, same seed:

| grammar | throughput | valid JSON |
|---|---|---|
| as shipped (13,352 B) | **5.24 tok/s** | 3/3 |
| without `maxLength` (2,063 B) | **5.11 tok/s** | 3/3 |

A 2% difference, within noise, with identical token counts. **Grammar size
costs nothing at inference.** Ruled out.

One caveat worth recording: `llama-cpp-python`'s *server* crashed with
`failed to parse grammar` on the 42 KB `ModelAction` grammar. S-CLAW ships
against `llama-server`, which is not installed here, so whether the same 42 KB
grammar troubles it is **untested and unknown**.

---

## 4. Root causes, ranked

1. **Output tokens at ~10 tok/s are the entire cost of a planning call.**
   Everything else — prompt size, grammar size, application overhead, routing —
   is noise beside it. The 0.0 s greeting proves the app itself is not slow.
2. **27% of that output is `expected_result`, which nothing reads.**
3. **No tier-B path:** a one-step action pays a full planning call.
4. **`/tasks/plan` bypasses the router.**

Not yet investigated: retry behaviour, streaming, per-call timeouts, executor
step cost, model selection across the catalogue.

---

## 5. Proposed changes, in order of measured value

| # | Change | Expected | Risk |
|---|---|---|---|
| 1 | Remove `expected_result` from the plan schema and prompt | ~27% off every planning call | Might be acting as chain-of-thought and helping accuracy — **must be measured, not assumed** |
| 2 | Route `/tasks/plan` through the same gates as `/tasks/run` | Correctness | Low |
| 3 | A tier-B fast path for a single obvious action | Skips a planning call | Must not weaken approvals |
| 4 | Investigate retries, timeouts and executor step cost | Unknown | — |

Change 1 is the one to test first, and the test is the held-out 16 with
accuracy **and** time, because a change that saves 27% and loses two correct
answers is not an improvement.

---

# Phase 4–6: implementation and results

## The root cause I had missed: the schema is a grammar

S-CLAW passes `json_schema` on **every** planner call. `llama-server` turns
that into a GBNF grammar and constrains every token. That is not free — it
changes what the model writes.

Measured on the real brain, 16 held-out tasks, same seed, same prompt:

| | correct | unusable | s/task | tok/task | steps |
|---|---|---|---|---|---|
| grammar on every call (**as shipped**) | **9/16** | 0 | 15.3 | 69 | **1.0** |
| free JSON, repaired by `jsonfix` | **13/16** | 1 | 23.1 | 222 | **2.5** |

A grammar-constrained 2B writes the *cheapest structure that satisfies the
grammar*, not the best plan: it collapsed real multi-step work into a single
step, every time. That is four correct answers out of sixteen, lost to a
constraint meant to improve reliability.

**This also corrects an earlier number of mine.** The 13/16 baseline I reported
earlier was measured with no grammar — a configuration the app does not use.
The shipped planner was really running at 9/16.

## The change

`backend/claw/agent/planner.py`, one line: the schema is passed on a **retry**,
never the first attempt. The retry loop already existed; `MAX_ATTEMPTS` is 2,
so the budget is one free attempt and one constrained one. Free output gives
the better plan; the grammar guarantees the retry cannot come back malformed.

Measured through the **real `make_plan`** (real retry, real `jsonfix`, real
validation):

| | correct | planning failures | s/task | model calls | steps |
|---|---|---|---|---|---|
| as shipped | 9/16 | 0 | 15.3 | 16 | 1.0 |
| **new** | **13/16** | **0** | 20.6 | **16** | 2.6 |

**+4 correct (+25 points), no reliability regression, and the safety net was
never needed** — 16 calls for 16 tasks, so no retry fired. The cost is 5.3 s
per planning call.

That is the trade the brief asks for: intelligence first, reliability kept,
speed given up only where it buys correctness.

## Things I tested that did NOT work, and did not ship

Recorded because a negative result is worth as much as a positive one here.

| idea | result | shipped? |
|---|---|---|
| Remove `expected_result` (27% of plan output, read by nothing) | +4 correct but **4.7× the tokens and 2.9× slower**; plans ballooned from 1.0 to 9.8 steps | **No** |
| Reorder the prompt's JSON example to match grammar field order | 10/16 vs 9/16 — within noise on n=16 | No |
| Make `title` required so the grammar matches the prompt | 8/16 — worse | No |
| Shrink the GBNF grammar by dropping `maxLength` (29× smaller) | 5.24 vs 5.11 tok/s — no effect | No |

`expected_result` is the interesting one: it reads like dead weight, and it is
load-bearing. Forcing the model to state a result per step makes it commit to
few, meaningful steps. Deleting it would have been a large, invisible
regression.

## Honest limits

- One model (Qwen3.5-2B Q4), 4 cores, **n = 16 tasks**. A 1-task difference is
  noise; the 4-task difference is reported as real.
- Measured with `llama-cpp-python`, not `llama-server`, which is what S-CLAW
  ships. Both use llama.cpp's grammar engine, but the schema→GBNF converters
  are separate implementations, so **the exact numbers on Windows may differ.**
  The direction — a grammar makes a small model write minimal structures —
  should hold.
- The executor still passes its schema on every call. The same question applies
  there and is **not yet measured**.

---

# Phase 4b: the executor

The same question, asked of the other model call — and the answer here is
worse than the planner's.

## What `ACTION_SCHEMA` actually constrains

```
action        enum ["tool","finish"]   <- the only useful constraint
tool          free string, maxLength 64   <- NOT limited to real tool names
args          additionalProperties: true  <- any object at all
thought       maxLength 1000
final_answer  maxLength 4000
required      ["action"]
```

`tool` and `args` are the two things that must be right, and the grammar
constrains neither. Meanwhile **only `action` is required**, so the cheapest
string satisfying the whole grammar is `{"action":"finish"}` — the model
finishing without doing anything. `executor.py` already carries three separate
guards against exactly that false completion.

## And the grammar does not even build

`maxLength` becomes that many repetitions in GBNF. `final_answer`'s 4000
produced a **42,081-byte** grammar, and llama.cpp's own parser refuses it:

```
parse: error parsing grammar: number of rules that are going to be repeated
multiplied by the new repetition exceeds sane defaults
```

Run in isolated processes, model loaded, same call:

| schema sent | result |
|---|---|
| `ACTION_SCHEMA` as shipped (42,081 B) | **segmentation fault, exit 139** |
| limits stripped (1,470 B) | exit 0, returned `{"action":"tool","tool":"take_screenshot","args":{}}` |

**Caveat, and it matters:** this is `llama-cpp-python`, not `llama-server`,
which is what S-CLAW ships. The two have separate schema→GBNF converters. But
the error comes from llama.cpp's **GBNF parser**, which both share, and it is
specifically about repetition counts — which is what `maxLength: 4000`
produces either way. So this is a real risk on the shipped stack, **not a
verified one.** Verifying it needs `llama-server` on Windows.

## The change

`backend/claw/agent/executor.py`:

- `without_length_limits(schema)` — strips every `maxLength`, at any depth,
  without mutating the original.
- `ACTION_SCHEMA_FOR_MODEL` — what the model is sent. **42,081 B → 1,470 B.**
- `_next_action` sends it only when `attempt > 1`, the same as the planner.

`backend/claw/agent/planner.py` uses the same helper for its retry schema.

The limits are not lost. `ACTION_SCHEMA` keeps them and pydantic still rejects
a 4001-character `final_answer` — a length cap is a check on what came back,
not something a grammar should spend thousands of rules on. There is a test
for that.

## Why this one is lower risk than it sounds

The executor's grammar was never doing the job it looked like it was doing:
it could not constrain `tool` or `args`, and its one real constraint — the
`action` enum — is still there in the retry. What changes is that the first
attempt is free, which is what produced better plans in the planner, and that
what the retry sends can actually be parsed.

---

# Phase 4c: limits, timeouts and the budgets that disagreed

## What already exists (the brief assumed these were missing)

| limit | value | behaviour on hitting it |
|---|---|---|
| `max_steps` | 20 | returns **`incomplete`** with what was done — not a fake success |
| `step_timeout_s` | 60 | step fails, marked transient, one retry |
| `approval_timeout_s` | 600 | treated as a denial |
| `max_consecutive_failures` | 3 | triggers a replan |
| `request_timeout_s` | 120 | model call fails with a named reason |
| `MAX_ATTEMPTS` / `MAX_REPEATS` / `MAX_REPLANS` / `MAX_PUSHBACKS` | 2 / 3 / 2 / 2 | all enforced |

S-CLAW's limit coverage is good, and `incomplete` is the honest outcome the
brief asks for. The problem is not a missing limit. It is **two limits that
contradict each other.**

## The runaway guard could never fire

`max_tokens` was **1536**. Measured generation on this machine is **~10
tokens/second** (2B Q4, four CPU cores). 1536 tokens therefore needs **154
seconds** — against a **120-second** `request_timeout_s`.

So the guard meant to stop a model that will not stop was unreachable. The
HTTP timeout always arrived first, and a timeout **throws the whole reply
away**, where hitting the cap leaves a truncated reply that `jsonfix` can
often repair and the retry can correct.

This is not hypothetical. Measured over the 16 held-out tasks plus 6 executor
calls, with the cap raised so the real need could be seen:

| | min | median | max | ran to the 1536 cap |
|---|---|---|---|---|
| planner replies | 96 | 208 | **1536** | **1 of 16** |
| executor replies | 41 | 59 | 72 | 0 of 6 |

One plan in sixteen was degenerate and generated until something stopped it.
In the shipped configuration the thing that stopped it was the 120 s timeout,
with nothing to show for the 120 s. That is the brief's "model sometimes gets
stuck thinking without producing a useful response", and it is arithmetic.

## The change

`max_tokens` 1536 → **1024** (~102 s at 10 tok/s, inside the 120 s timeout
with headroom), and `SLOW_TOKENS_PER_SECOND = 10.0` recorded next to it so the
relationship is explicit rather than two independent numbers that drifted
apart.

`tests/test_token_time_budgets.py` holds them together: the cap must be
reachable before the default timeout, with 10% headroom, and must still clear
4× the largest real reply measured (208 tokens). If anyone raises the cap or
lowers the timeout past the point where the guard stops working, a test fails
and says why.

1024 truncates exactly one of the 22 replies measured — the degenerate one,
which is the reply that should be truncated.

## Still open

- **No overall task deadline.** Each limit is sane; their product is not.
  20 steps × (120 s model + 60 s tool) is up to an hour with every individual
  limit respected. Not changed here: a deadline needs a decision about what
  a half-finished task should report, and `incomplete` already exists as the
  honest shape for it.
- Tier B (a light path for one simple action).
- `/tasks/plan` bypassing the router.

---

# Phase 4d: one clock for the whole task

## Why the runaway reply happened — it was not rambling

The one planner reply that ran to the 1536-token cap was
**"Tidy up my Downloads, it is a mess"**, and the output is specific:

```
{"description": "Move files from the root Downloads folder into a '2006' subfolder", ...},
{"description": "Move files from the root Downloads folder into a '2005' subfolder", ...},
{"description": "Move files from the root Downloads folder into a '2004' subfolder", ...},
```

140 lines, 54 distinct; 24 `{`, 23 `"capability": "files"`. The model chose to
**enumerate one step per year, counting downwards**, and would have carried on
to 2003, 2002, 1999. It is not degenerate repetition in the
`repetition_guard` sense — every step is slightly different, so a repeat
detector would never catch it.

Two things let it happen:

1. **An open-ended request with no bound.** "Tidy up" has no stopping
   criterion, so the model invented one and it was unbounded.
2. **Nothing enforced the step limit during generation.** The prompt says
   "maximum 15" and `ModelPlan` sets `maxItems: 15`, and the model sailed past
   both to 24+. Only the grammar enforces `maxItems` mid-generation — and
   after commit 8fb5be3 the first attempt is deliberately unconstrained.

So the token cap is a backstop, not the fix, exactly as the brief says. The
real fix is a plan-shape one: when a single tool handles a whole folder
(`sort_into_folders` exists), the plan should be one step, not one per group.
**Not yet done, and not yet measured** — it belongs with the planner-prompt
work, where every change has to be measured on the held-out set.

What the already-shipped change does do: the grammar-constrained **retry**
enforces `maxItems: 15`, so the second attempt cannot produce a 24-step plan.

## The deadline

`backend/claw/agent/deadline.py`. One clock, started in `TaskRunner._run`
**before the router**, so planning is inside it, and never reset.

| requirement | how |
|---|---|
| covers the whole lifecycle | started before the router gates; passed through `make_plan` → `run_agent` → `_next_action` |
| never resets | `tighten_to()` only ever **lowers**, and `started` is never touched. Tested. |
| stops new work | checked before each step and before each model attempt |
| cancels safely | a model call is an HTTP request, so it gets `min(its own limit, time left)` and is cut off. A **tool is not cancelled**: it may be halfway through writing a file, so a running tool keeps its own `step_timeout_s` and the deadline stops the *next* one. Overshoot is bounded by one step. |
| honest result | `incomplete` (the status that already existed), naming completed steps and the step it stopped on |
| preserves work | the message says what finished is kept; nothing claims a rollback, and a test forbids the words "rolled back" and "undone" |
| extended tasks | `extended: true` on the request selects `extended_deadline_s`. Never inferred — how long someone will wait is their decision. |

### Four budgets, because the shapes differ

| band | default | chosen when |
|---|---|---|
| conversation | 120 s | the chat lane |
| simple | 180 s | plan of 1 step |
| moderate | 360 s | plan of 2–4 steps |
| complex | **600 s** | plan of 5+ steps |
| extended | 1800 s | the person asked for it |

The band is picked from the plan's step count *after* planning, and only ever
narrows the budget the task started with — the time planning took still counts
against it.

`tests/test_task_deadline.py` (20 tests) holds all of it, including that a run
with no deadline behaves exactly as before.

---

# Phase 5: tier B, the plan route, diagnostics, and the enumeration fix

## C. Diagnostics first, because they measure everything after

`backend/claw/agent/timings.py`. Seven phases, each timed separately and all
reported — including the cheap ones, because a number that only appears when
it is bad cannot show that anything is good. `unmeasured_s` names whatever the
phases did not account for, rather than leaving a silent gap.

The first real run paid for itself immediately:

```
[simple action] Open Notepad        30.2s -> failed
    router 0.00s | selection 0.00s | planning 19.58s | generation 10.39s | tools 0.00s
```

Three things at once:

1. **Routing and model selection cost nothing** — 0.00 s each. They were never
   the problem.
2. **"Open Notepad" spent 19.6 s planning a one-step plan**, which is the whole
   case for tier B, measured rather than argued.
3. **A bug I had just introduced:** the run was reported as `failed` with "The
   model did not give a usable next action" when it had actually run out of
   time. Blaming the brain for a limit Claw imposed. Fixed — deadline expiry
   now returns `incomplete` with the real reason, and a test forbids the two
   from being confused again.

## A. The open-ended enumeration

Root cause found by grepping the planner's prompt for tool names: **there are
none.** The planner knows capabilities, not tools. So "Tidy up my Downloads"
was planned in the abstract and became one step per year, counting downwards —
while `fitting_tools()` already maps that exact request to `sort_into_folders`.

Benchmarked on the held-out 16, three ways:

| | correct | unusable | tok/task | s/task | steps |
|---|---|---|---|---|---|
| as shipped, no note | 13/16 | **1** (the runaway) | 242 | 23.8 | 2.5 |
| **note naming the tools** | **13/16** | **0** | **178** | **19.3** | 2.3 |
| note + "prefer one step over many" | 12/16 | 0 | 151 | 16.8 | 1.8 |

Naming the tools fixes the runaway, costs no accuracy and saves 26% of the
output tokens. **Telling the model what to conclude from them costs a correct
answer** — it pushed "Which branch sold the most in sales.xlsx" onto
`create_spreadsheet`, a creation tool for an analysis question. So the note
states the fact and stops, and a test forbids instruction words in it.

## 1. Tier B

`backend/claw/agent/simple_action.py`. One obvious action skips the planning
call entirely — no model, plan synthesised from Claw's own matcher.

It is **not** a keyword list: it rests on `fitting_tools`, and adds only the
checks that matcher cannot make. A request is one obvious action when it is
one line, at most 8 words, carries no conjunction joining a second job, and
matches 1–4 tools **that agree on capability and risk**. That last clause is
what lets "Open Notepad" through (three tools, all `desktop`/`local_write`)
while refusing anything whose matched tools disagree — because then the
permission shown to the person would be a guess.

The bias is one-sided, like `conversation.py`: treating a multi-step job as one
action is a confident wrong answer; treating a simple action as complex costs
only the planning call it costs today. 12 of 12 hand-checked cases correct,
including the ones that matter: "…and email it", "Research five companies and
put them in a spreadsheet" and "Delete everything in Downloads" all refused.

**Nothing about approval changes.** The executor still chooses the tool and its
arguments, `decide()` still asks, and the DESTRUCTIVE floor still holds. The
plan was only ever advice.

## 2. `/tasks/plan` no longer bypasses the router

It now runs the two cheap gates. A greeting is **refused without a model call**
— this endpoint only ever produces a plan, so it has no "completed" to return,
and the refusal carries the answer it would have given. One obvious action is
planned from the matcher, also without a model.

## B. Deadlines

conversation **15 s**, simple **30 s**, moderate **3 min**, complex **10 min**,
extended **30 min**, all configurable.

**One honest caveat on the 30-second simple budget:** before tier B, "Open
Notepad" needed 19.6 s of planning plus 10.4 s of action and hit exactly that
limit. Tier B removes the planning call, which is what makes 30 s the right
number rather than a cut too tight. The two changes belong together.


---

# Phase 5b: the fragility I flagged was a real defect

I ended the last phase noting that the 30-second simple budget "only works
because of tier B". That was not just a coupling note - it was a bug, and the
numbers make it plain.

The bands are applied **retroactively**: planning is inside the budget, so a
slow plan eats a small band before a single step runs.

| planning took | simple band leaves | outcome |
|---|---|---|
| 5.0 s | 25.0 s | fine |
| 19.6 s (measured) | 10.4 s | barely enough for the 10.4 s action call |
| 25.0 s | 5.0 s | dies mid-thought |
| 35.0 s | **0 s** | **expires the instant planning ends, fails having done nothing** |

Somebody waited 35 seconds for nothing. That is worse than having no deadline
at all, and it is exactly the `failed` run the diagnostics caught earlier.

**Fix:** `tighten_to` takes a floor, `min_work_after_planning_s`, default
**15 s** and configurable. Tightening never leaves less than that.

It is sized for what it actually has to cover: choosing the next action and
*starting* a tool. A running tool is never interrupted by the deadline - it
finishes under its own `step_timeout_s` - so the floor does not need to cover
the tool running. The measured action call was 10.4 s; 15 leaves headroom on a
slower machine, and a test asserts it stays below `step_timeout_s` so it can
never grow into something that inflates every band.

It rescues, it does not inflate:

| planning took | result |
|---|---|
| 5.0 s | **unchanged** - 30 s band, 25 s left, already above the floor |
| 15.0 s | **unchanged** - 30 s band, 15 s left |
| 19.6 s | rescued - total 34.6 s |
| 35.0 s | rescued - total 50.0 s |

And the outer bound still holds: the floor never raises the budget above what
the task started with. Planning for 1000 s against a 600 s start still ends at
600 s. Tested.

---

# Phase 6: model selection, failure modes — and a correction

## A correction to something I reported earlier

I said `max_tokens = 1536` made the runaway guard **unreachable**, because
1536 tokens at ~10 tok/s is 154 s against a 120 s timeout. **That was wrong
about the path most people run.**

`claw/api/app.py` passes the builtin brain
`max(request_timeout_s, LOCAL_REPLY_TIMEOUT_S)`, and `LOCAL_REPLY_TIMEOUT_S`
is **600**. So:

| brain | timeout that applies | was 1536 reachable? |
|---|---|---|
| **builtin (the default)** | **≥ 600 s** | **yes — the guard worked** |
| cloud / custom | `request_timeout_s`, default 120 s | no — the mismatch was real |

So the change from 1536 to 1024 is two different things depending on where the
brain is: a genuine fix for cloud and custom, where the budgets disagreed, and
merely a smaller worst case for builtin, where a runaway now costs ~102 s
instead of ~154 s. The comment in `openai_compat.py` and the tests have been
corrected to say so, and a test now pins `LOCAL_REPLY_TIMEOUT_S` specifically
so this cannot be got wrong again.

## 3. Model selection

Three questions from the brief. Two have measured answers; one cannot be
answered on this machine and says so.

**Does selection cost time?** No. Phase timings on the real app:
`selection 0.00 s`.

**Does loading?** No. A 1.2 GB GGUF loads in **1–2 s**, and dropping the page
cache made no difference — llama.cpp **mmaps** the file, so "loading" never
reads 1.2 GB; pages fault in during inference instead. Against a ~20 s
planning call this is noise. (Caveat: on Windows with an 8 B model on a slow
disk, those page faults land on the first inference. Not measurable here.)

**Is the choice sensible?** Yes, across eight machine profiles, and it does not
decide on size alone — Pro fits 16 GB of RAM on paper and is still refused
without a GPU, because each reply takes minutes on a laptop processor. Unknown
RAM gets Standard rather than the largest. Tiny is never recommended. One
deliberate edge is now pinned by a test: a 2 GB machine is given Light even
though it does not fit, because the alternative is handing someone the worst
brain in the catalogue and calling it the best their computer can manage —
and `fits()` still reports the truth so a caller can warn.

**What I cannot answer:** whether different models should serve conversation,
classification, planning and tool-calling. That needs several models measured
against each other and **only one model exists on this machine**
(Qwen3.5-2B Q4). Any ranking I produced would be invention. The honest status
is NOT TESTED, and it stays that way until a second model is available.

What the evidence so far does suggest, without proving it: the costs that
matter are output tokens and round trips, not which model is loaded, and
S-CLAW already routes the cheapest work (greetings, one obvious action) away
from the model entirely. A second model would have to beat that by more than
the complexity it adds.

## 4. Failure-mode tests

`tests/test_failure_modes.py`, 18 tests, covering what the brief listed:

| failure | what is asserted |
|---|---|
| reply is not JSON | retried once, then reported — never silently accepted |
| reply is nearly JSON | repaired by `jsonfix` rather than thrown away |
| plan with 0 steps | **rejected** — accepting it reports success for a task where nothing ran |
| unknown capability | rejected |
| model server error | retried, then surfaced with a real reason |
| transient error | recovers on the retry |
| deadline expiry | positive timeout, and the reason does not blame the model |
| context overflow | trimmed, and being over the line is **reported, not hidden** |
| trimming | the system message and the task always survive |
| malformed JSON of every shape a small brain writes | handled, including Windows paths |
| unparseable input | **raises** rather than inventing a plausible result |
| retry schema | cannot build the grammar that segfaulted the process |

The rule they all encode is the project's own: never hide an error behind a
fake success, and never blame the brain for a limit Claw imposed.

---

# Phase 7 — validation against the real engine

Everything below was measured against a real `llama-server` built from source
(version 1.0.0-dev, build 1, commit a956a85) serving Qwen3.5-2B Q4 on four CPU
cores, **on Linux**. That matters and is not glossed over: see "What is still
not validated" at the end. Nothing here is a Windows result.

Earlier phases used `llama-cpp-python`. Several of the findings below could
only be found on the real server, because the two behave differently in ways
that turn out to matter.

## 7.1 The thinking model never answered. Not slowly — never.

The chat lane was failing on the real engine for every question tried. The
cause is not a slow answer, it is no answer:

| `max_tokens` | time | `finish_reason` | `content` | `reasoning_content` |
|---|---|---|---|---|
| 512  |  38.2s | length | **0 ch** | 1977 ch |
| 1024 |  82.7s | length | **0 ch** | 4006 ch |
| 1536 | 127.1s | length | **0 ch** | 5995 ch |
| 2048 | 160.7s | length | **0 ch** | 7859 ch |

"What is the capital of France?" through `CHAT_SYSTEM`, temperature 0. The
reasoning grows to fill whatever budget it is given and the answer is never
reached. **This disproves two things at once:** the failure is not caused by
the 1536 → 1024 token reduction made in phase 4 (it fails identically at
2048), and it cannot be fixed by raising the limit.

`llama-server` splits a thinking model's chain of thought into a separate
`reasoning_content` field, so all of this arrived as HTTP 200 with an empty
`content`. `llama-cpp-python` does not split them, which is exactly why five
phases of work never saw it.

Three ways out were measured:

| request | time | finish | `content` |
|---|---|---|---|
| as it was | 75.7s | length | **0 ch — no answer at all** |
| `chat_template_kwargs: {"enable_thinking": false}` | **1.4s** | stop | **71 ch, correct** |
| `reasoning_format: "none"` | 81.5s | length | 4014 ch of raw `<think>` |

So `enable_thinking: false` is a **54× speed-up that also turns a total
failure into a correct answer**, and `reasoning_format: none` is actively
harmful — it leaves the thinking switched on and merely inlines the monologue
into the reply the person reads. It is now tested against.

**This is the "gets stuck thinking without producing a useful response"
problem this project kept hearing about, reproduced deterministically and
fixed at the cause.** Its knock-on effect was the worse half: the chat lane
raised, fell through to planning, and held the single-task runner for 90
seconds, after which every other task was refused as busy.

### Shipped
`thinking=False` on the chat lane only. The field is a llama.cpp extension, so
support is **discovered, not assumed**: a server that answers 400 and names it
(as a cloud provider does) sets `quiet_thinking_ok = False` and the request is
sent again without it. Cost is one wasted round trip per server, once —
`test_the_refusal_is_learned_once_not_every_call` pins that. Ollama's spelling
of the same switch (`think: false`) is handled the same way.

Planning and tool choice are **left alone** until measured — see 7.2.

## 7.2 Does planning want thinking off too?

Measured through `make_plan` against the real engine on the held-out 16
(the set the planner prompt was *not* written against), temperature 0:

    thinking OFF    usable 16/16   right 13/16   avg 2.8 steps   total 247s   median 16.2s
    thinking ON     (running — not yet reported)

Thinking off holds the 13/16 accuracy established in phase 3 while producing a
usable plan every single time. The ON figure is being measured on the same
engine and the same tasks before anything is changed on the planning path.

## 7.3 Four defects found reviewing the eight commits as one change

Reading the audit's commits together rather than one at a time turned up four
problems, none of which any single commit had introduced on its own.

1. **The planner's model call was never bounded by the task deadline.** The
   executor wraps each of its calls in `deadline.timeout_for(...)`; `make_plan`
   did not. Planning was therefore inside the budget only *arithmetically* —
   one call could run for the adapter's own timeout (600s on the built-in
   brain) and spend a whole ten-minute task, after which the clock was checked
   for the first time and the task reported running out of time having started
   nothing. Fixed: planning is bounded by the same clock, and expiry during
   planning now raises `DeadlineReached` and is reported as **incomplete**,
   not as "the model did not produce a usable plan" — which sent people
   looking for a broken brain.

2. **The conversation lane tightened the task's clock, not its own call.** A
   chat reply is allowed to fail and fall through to real work; when it did,
   that work inherited the 15-second conversation budget. Planning alone takes
   about 20 seconds on a 2B, so the task expired the instant planning ended.
   The bound now goes on the call. `test_a_failed_chat_reply_leaves_the_task_
   its_full_budget` was confirmed to fail with the bug reintroduced and pass
   with the fix.

3. **The fast lanes reported no timings at all.** Five gates each carried their
   own copy of the same four or five closing statements, and the copies had
   drifted: every lane that answers *without* working returned before
   `emit("timings")` ran. Conversation — one of the three things this phase was
   asked to measure separately — was the one path measuring nothing. The five
   copies are now one `answered()` helper, so every lane reports its own cost,
   and the router's clock is closed by `close_router()` before any model call
   so the phases stay additive (`test_the_phases_never_double_count`).

4. **`/tasks/plan` never received the enumeration fix.** The runner sends
   `tools_note(...)`; the plan endpoint still called `make_plan(req.task, ...)`
   bare, so it kept the runaway the runner no longer had. Fixed.

Checked and found **not** to be defects: `busy` is derived from the asyncio
task's own state, so it self-clears even when `_run` crashes — the cascade of
rejected tasks measured in 7.1 was genuine single-task serialisation behind the
90-second stall, not a leaked flag.

## What is still NOT validated

- **Windows.** Every number above is Linux. No claim of Windows production
  readiness is made or implied.
- **Model specialisation.** NOT TESTED. A second model is needed and no
  conclusion is invented in its absence.

## 7.4 Planning wants thinking off too, decisively

The ON/OFF comparison through `make_plan`, held-out 16, real llama-server
under Claw's production flags, Qwen3.5-2B, temperature 0:

| mode | usable plan | right capability | total | median |
|---|---|---|---|---|
| thinking **ON** (as shipped) | **2/16** | **2/16** | 2330s | 162.0s |
| thinking **OFF** | **16/16** | **14/16** | 226s | 15.7s |

Seven times faster and seven times more accurate at once. That combination is
only possible because the failure with thinking on is **total rather than
slow**: fourteen of the sixteen ran their whole 1024-token budget twice over
and put every token in `reasoning_content`, leaving `content` empty. The
arithmetic confirms it independently — 2 × 1024 ÷ 13.0 tok/s = 158s against a
measured 150–170s, i.e. both attempts generated to the length limit every
time. A plan that is never written cannot be a better plan.

**This also explains why five phases of this audit measured the planner as
working.** `llama-cpp-python` inlines the chain of thought into `content`,
where `jsonfix` digs the JSON out from after it. The real engine files it
under `reasoning_content`, where nothing reads it.

### Shipped
`thinking=False` on every model call Claw makes — planner, executor, replan,
the two tool lanes, and the brain self-test. Applied everywhere rather than
lane by lane because the failure mode is total: there is no speed-versus-care
trade to make with an answer that is never produced. The self-test matters
for its own reason — asked with thinking on, it would report a brain as broken
that works fine for Claw, which is testing something the app never does.

`test_every_lane_stops_thinking.py` walks the package's AST and checks every
`.chat(...)` call. Structural on purpose: the bug is silent, it has already
hidden from five phases, and a new lane added without the flag would not
raise — it would quietly answer nothing after eighty seconds.

## 7.5 End-to-end, through the real app

A real uvicorn backend (not TestClient, which starves the runner and produced
a phantom 600s hang earlier in this audit), real engine, per-phase numbers
from each task's own `timings` event.

**Conversation — fixed, and now the fast path it was meant to be:**

    7 of 7 completed, median 1.8s, slowest 4.1s
    canned replies 0.0s; model replies 1.6-3.9s of generation
    router 0.00s, selection 0.00s, planning 0.0s

Against "never answered at all, then 90s of planning, then every following
task refused as busy" before the fix.

## 7.6 The hole in the executor's safety net

The executor was failing on ordinary read-only CSV tasks. The cause was not
the model being weak, and not thinking: `ModelAction.tool` must be optional,
because a "finish" action has no tool, so the flat schema generated from it
**permits `{"action": "tool"}` with nothing to call**. `run_agent` rejected
that by hand — and because the schema allowed it, the constrained RETRY, the
safety net under the free first attempt, could serve the same invalid reply
again. "action 'tool' needs a tool name" was the commonest rejection in both
the unconstrained and the constrained runs.

The schema the model is SHOWN now describes the two actions as what they are:
alternatives, each with its own required fields — a tool action must name a
tool, and a finish must say something (a finish with nothing to say is the
false completion this file already guards against three other ways, and the
cheapest reply a grammar can emit must not be the one that abandons the task).
`ModelAction` is untouched and remains what a reply is validated against.
Verified on the real engine: 401 bytes, HTTP 200, and it produces a tool call
with a tool name and a finish with an answer.

Four read-only CSV tasks, before and after, same engine and flags:

| | completed | median wall | generation | rejections |
|---|---|---|---|---|
| before the fix, free first | 0/4 | — | — | 6 |
| before the fix, constrained first | 0/4 | — | — | 7 |
| after the fix, free first | 2/4 | 45.8s | 136.5s | 7 |
| after the fix, constrained first | **3/4** | **30.3s** | **83.7s** | **0** |

A wider run is in progress before anything is concluded about constraining the
executor's FIRST attempt; the schema fix itself stands on the 0/4 → 2/4
improvement with the free first attempt left exactly as it was. Note that the
planner measured the opposite way round on constraint (13/16 free vs 9/16
constrained), so the two lanes are not assumed to want the same thing.

## 7.7 Open, measured, not yet fixed

- **The simple band is knife-edge on a 2B.** "List the files in <folder>"
  plans in 14s and then has 16s of a 30s budget for an action call that costs
  15–21s, so it reports "reached its time limit of 30 seconds". 30s is the
  value asked for, and it is right for a tier-B action that skips planning;
  it is too tight for a one-step plan that does not.
- **Tier B is narrower than it looks.** It rests on `fitting_tools`, whose
  `_FITTING` list is a deliberately narrow set of patterns for surfacing
  SPECIALIST tools the planner would otherwise miss ("9:16 version", "black
  frames", "broken links"). So tier B fires for "Open Notepad" but not for
  "List the files in X", which is why that task pays full planning. Not a bug
  in the matcher - it was never a general one - but it bounds what tier B can
  save, and the 30s band above assumes savings it does not always get.

## 7.8 Constraining the executor's first attempt: measured, and rejected

The four-task run in 7.6 suggested constraining the executor's FIRST attempt
(3/4 against 2/4). Widening it to eight reversed that:

| | completed | median wall | generation | calls | rejections |
|---|---|---|---|---|---|
| free first (today) | **5/8** | 35.5s | **209.4s** | **21** | 9 |
| constrained first | 4/8 | 31.3s | 341.1s | 28 | 1 |

Constraining does take rejections from 9 to 1 — and still loses, by 63% more
generation and a worse completion rate. Its failures say why: the model
satisfies the grammar with a **valid but wrong** action and then repeats it.
One run spent nine calls and 98 seconds reaching "3 steps failed in a row".
A reply that is well-formed and useless costs more than one that is rejected
and retried.

So the executor's first attempt is unchanged, and the four-task result is
recorded here as the noise it was. **The only reason the wrong change was not
shipped is that the sample was widened before shipping it**, and an
experiment toggle that briefly existed in the executor to run this comparison
has been removed.

Worth noting the two lanes disagree and both are now measured: the planner is
better free (13/16 against 9/16), and so is the executor. The grammar is a net
under a free attempt in both, never the opening move.

## 7.9 The simple band, measured and left to the user

Raising `min_work_after_planning_s` from 15 to 25 took the eight tasks from
5/8 to 6/8 and generation from 209s to 189s. "List every file and count it"
went from failing at 30s having done nothing to completing in 29.8s.

It was **not** raised further. "Make a file hello.txt" still fails: it wanted
24.9s of generation that run against 16.4s the run before, so a one-step
action's cost varies by more than a floor can absorb. Covering it needs a
floor of 30, and with a 30s band a 30s floor binds for *any* planning at all
— which quietly redefines "a 30-second simple action" as "30 seconds after
planning". That is a different promise, and not one to make unasked.

So the trade is stated rather than resolved: a one-step task whose plan took
9–14s now runs to about 34–39s instead of failing at 30 with nothing done. If
that is still too tight for the brain in use, the band itself
(`simple_deadline_s`) is the thing to raise, because how long someone will
wait is their decision. `test_the_floor_binds_once_planning_is_slow_and_the_
cost_is_known` pins the arithmetic so the trade cannot drift silently.

## 7.10 Reliability

Real uvicorn backend, real engine, after all of the above.

| check | result |
|---|---|
| ten repeated conversations | all ten completed; RSS 65 → 71.6MB; median 1.5s, last three 1.3/1.3/1.5s |
| six different tasks in a row | none refused as busy, none hung |
| interrupt, then carry on | cancel accepted, task reached `cancelled`, next task completed in 1.3s, no row left mid-flight |
| brain dies, then comes back | failed in **0.3s** rather than hanging; recovered in 1.3s |

**The `TaskBusy` cascade is gone.** Before the thinking fix, one stuck
conversation held the single-task runner for 90 seconds and every following
task was refused; six consecutive tasks now run without a single refusal. No
memory leak over ~20 tasks, no drift in repeated latency, and nothing left in
a `planning`/`running` state to show as a spinner that never clears.

Not hidden by that pass: **two of the six sequential tasks came back
`incomplete` at about 32s** — the 7.9 simple-band limitation, not a
reliability defect, but it is what a person would actually notice.
