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
