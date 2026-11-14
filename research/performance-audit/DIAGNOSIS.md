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
