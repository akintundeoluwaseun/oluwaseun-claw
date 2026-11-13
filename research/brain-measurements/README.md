# Brain measurements

Numbers from a **real** Qwen3.5-2B (Q4, 1.28 GB GGUF) on 4 CPU cores, via
llama-cpp-python 0.3.36, temperature 0 so a repeat run gives the same answer
and a difference means the change did something.

Not part of the test suite: it needs a model and takes half an hour.

Reproduce:

    pip install llama-cpp-python
    python scripts/brain_bench.py --model <brain.gguf> --held-out

---

## 1. Does a shorter planner prompt help? No. It makes things worse.

The audit of six open-source agents recommended Goose's 21-line
`tiny_model_system.md` as "the cheapest experiment available" and the top
prompt idea to try. It was tested properly, and **the recommendation was
wrong.**

Three planner prompts, same model, same 16 held-out tasks (held-out = the set
the prompt was NOT written against):

| prompt | size | correct | unusable plans | mean/task | mean steps |
|---|---|---|---|---|---|
| **A, as shipped** | 5,720 chars | **13/16 (81%)** | 1 | 25.5 s | **2.5** |
| B, trimmed | 3,396 chars | 11/16 (68%) | 2 | **19.4 s** | 2.7 |
| C, tight | 2,243 chars | 10/16 (62%) | 4 | 22.6 s | 3.6 |

**The shipped prompt is not bloat; it is load-bearing.** Cutting 40% of it
cost three correct answers out of sixteen.

The important column is the last one. C is 1,153 characters shorter than B and
yet **slower** — because it produces worse plans: 3.6 steps instead of 2.7,
and four plans S-CLAW cannot use at all. Every extra step is another execution
call, and an unusable plan is a retry. A bad plan costs far more time than a
long prompt saves.

So prompt length is not the speed lever. Plan quality is, and the long prompt
is what buys it.

## 2. What the chat fast path saves

Three general questions, planner path versus the chat path:

| | mean | what it produced |
|---|---|---|
| planner (what these questions used to get) | **17.9 s** | a *plan* to "find the capital city of France" |
| chat path (what they get now) | **2.6 s** | "The capital of France is Paris." |

**6.9× faster**, and the 17.9 s is only the planning call — the old path would
then execute the plan it made, so the real saving is larger.

The planner's output is the point: asked the capital of France, it wrote a
plan to go and find out. That is the "thinking when it is not supposed to
think" this fixes.

## 3. Honest limits

- One model (Qwen3.5-2B Q4), one machine, 4 cores, 16 tasks per variant.
  Absolute seconds will differ on other hardware; the ratios should hold.
- 16 tasks is a small set. A 2-task difference is near the noise floor, which
  is why the A-vs-C gap (3 correct, 3 extra unusable plans) is reported as
  real and B-vs-C is not treated as meaningful.
- Temperature 0 removes sampling noise but not prompt-order effects.
- Measured on Linux. S-CLAW ships on Windows against `llama-server`, not
  llama-cpp-python, so these are the model's numbers rather than the shipped
  app's.
