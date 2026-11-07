"""Does the brain pick the right capability? Measured, not guessed.

The planner chooses one capability per step, and that choice decides which
tools the agent is even shown. Choose "browser" for "make an invoice" and
make_document is invisible, however well it works and however well it is
routed - which is exactly what a real 2B brain did on the first run of this
script: 5 of 8 right.

    python scripts/brain_bench.py --model path/to/brain.gguf [--tasks 16]

Prints a score and every miss, so a prompt change can be judged instead of
argued about. Temperature is 0, so two runs of the same model and prompt
give the same answer and a difference means the change did something.

This needs a real GGUF brain and llama-cpp-python. It is not part of the
test suite: it is slow (tens of seconds per plan on a CPU) and it measures
a model, not the code.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from claw.agent.jsonfix import loads as repair_json  # noqa: E402
from claw.agent.planner import SYSTEM_PROMPT  # noqa: E402

#: (what a person types, the capability the main step should use).
#: Phrased the way people actually ask, not in the catalogue's words - the
#: whole question is whether the model can bridge that gap.
TASKS: list[tuple[str, str]] = [
    # documents
    ("Find the latest PDF in Downloads and summarise it", "documents"),
    ("Join the three invoices in January invoices into one PDF", "documents"),
    ("Take pages 2 to 5 out of the contract PDF", "documents"),
    ("Send one reminder letter to each customer in customers.csv", "documents"),
    # data
    ("Total the sales column across the CSV files in Books", "data"),
    ("Make an invoice for Ade Stores for 20 exercise books at N500", "data"),
    ("Show me the total sales by city from sales.csv", "data"),
    # design
    ("Make my photos in the Shop photos folder smaller for WhatsApp", "design"),
    ("Make a flyer for a back to school sale", "design"),
    ("Make a QR code for my catalogue page", "design"),
    # files
    ("Open the supplier's zip in the Supplier folder and tell me what is in it", "files"),
    ("Which files in Quotes mention the word refund?", "files"),
    ("Organise the Downloads folder into subfolders by type", "files"),
    # desktop
    ("Install VLC on this computer", "desktop"),
    ("Open Notepad and type my shopping list", "desktop"),
    # code
    ("Write a python script to rename the files in Wedding shots in date order", "code"),
    # browser
    ("Search the web for free video editors and list three", "browser"),
]


#: A second set the prompt was NOT written against. Same jobs, different
#: words, and none of them appears in the prompt's worked examples.
#:
#: This exists because the first set was used to tune the prompt, and a
#: prompt tuned against its own test measures nothing. A score that holds up
#: here is a real improvement; a score that only holds on TASKS is a prompt
#: that memorised the answers.
HELD_OUT: list[tuple[str, str]] = [
    ("Stick the scanned receipts together into a single file I can e-mail", "documents"),
    ("This contract is 40 pages, I only want the payment terms on page 9", "documents"),
    ("Write to every supplier in suppliers.xlsx about the new address", "documents"),
    ("Work out what I earned last month from takings.csv", "data"),
    ("Bill Chidi Ltd for 3 cartons at 1250 each", "data"),
    ("Which branch sold the most in sales.xlsx?", "data"),
    ("These camera pictures are too heavy to send, sort that out", "design"),
    ("I need something eye-catching for the shop window about our sale", "design"),
    ("Put a scannable square on the poster that opens my price list", "design"),
    ("Tidy up my Downloads, it is a mess", "files"),
    ("Where did I save the thing that talks about the refund?", "files"),
    ("The accountant sent a compressed folder, get the papers out of it", "files"),
    ("I need 7-Zip on this machine", "desktop"),
    ("Put the total in the calculator app for me", "desktop"),
    ("Number these camera files so they are in the order I shot them", "code"),
    ("Look online and tell me three free photo editors", "browser"),
]


def run(model_path: str, limit: int, threads: int, context: int,
        held_out: bool = False) -> int:
    from llama_cpp import Llama

    chosen = HELD_OUT if held_out else TASKS
    tasks = chosen[:limit] if limit else chosen
    started = time.time()
    llm = Llama(model_path=model_path, n_ctx=context, n_threads=threads, verbose=False)
    print(f"{Path(model_path).name}: loaded in {time.time() - started:.1f}s, "
          f"{len(tasks)} tasks\n")

    good_json = right = 0
    steps_total = 0.0
    misses: list[str] = []
    for task, want in tasks:
        began = time.time()
        reply = llm.create_chat_completion(
            messages=[{"role": "system", "content": SYSTEM_PROMPT},
                      {"role": "user", "content": task}],
            max_tokens=700, temperature=0.0)
        text = reply["choices"][0]["message"]["content"] or ""
        took = time.time() - began

        try:
            plan = repair_json(text)
        except Exception:                                   # noqa: BLE001
            plan = None

        # Every step must be an OBJECT with a capability. A model that
        # returns steps as bare strings has produced something S-CLAW will
        # reject, so it is a bad plan, not a crash in the scorer - which is
        # what it was until the old prompt produced exactly that.
        steps = plan.get("steps") if isinstance(plan, dict) else None
        if not steps or not all(isinstance(x, dict) for x in steps):
            why = "no usable plan" if not steps else "steps are not objects"
            print(f"[BAD ] {task[:50]:52} {took:5.1f}s  {why}")
            misses.append(f"{task} -> {why}")
            continue

        good_json += 1
        caps = [x.get("capability") for x in steps]
        steps_total += len(caps)
        if want in caps:
            right += 1
            print(f"[OK  ] {task[:50]:52} {took:5.1f}s  {len(caps)} step(s)")
        else:
            print(f"[MISS] {task[:50]:52} {took:5.1f}s  got {caps} want {want}")
            misses.append(f"{task} -> {caps}, wanted {want}")

    n = len(tasks)
    print(f"\nusable plan:       {good_json}/{n}")
    print(f"right capability:  {right}/{n}  ({100 * right / n:.0f}%)")
    print(f"average steps:     {steps_total / max(good_json, 1):.1f}")
    if misses:
        print("\nmisses:")
        for m in misses:
            print("  -", m)
    return right


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--model", required=True)
    p.add_argument("--tasks", type=int, default=0, help="only the first N")
    p.add_argument("--threads", type=int, default=8)
    p.add_argument("--context", type=int, default=8192)
    p.add_argument("--held-out", action="store_true",
                   help="the set the prompt was NOT tuned on")
    args = p.parse_args()
    run(args.model, args.tasks, args.threads, args.context, args.held_out)


if __name__ == "__main__":
    main()
