"""Compare planner prompts on the real brain. One model load, N prompts.

Measures both things that matter: did it pick the right capability, and how
long did it take. A shorter prompt that scores the same is a free speed win,
which is the whole point.
"""
import json, sys, time
from pathlib import Path
sys.path.insert(0, "/home/user/oluwaseun-claw/backend")
sys.path.insert(0, "/home/user/oluwaseun-claw/scripts")

from claw.agent.jsonfix import loads as repair_json
from claw.agent.planner import SYSTEM_PROMPT as BASE
import importlib.util
spec = importlib.util.spec_from_file_location("bb", "/home/user/oluwaseun-claw/scripts/brain_bench.py")
bb = importlib.util.module_from_spec(spec); spec.loader.exec_module(bb)

MODEL = "/tmp/claude-0/-home-user/43b2e3f1-c52d-5e50-845d-e5a060dc4519/scratchpad/brains/qwen3.5-2b-q4.gguf"

def score(llm, prompt, tasks, label):
    right = bad = 0; secs = 0.0; steps = 0; misses = []
    for task, want in tasks:
        t0 = time.time()
        r = llm.create_chat_completion(
            messages=[{"role": "system", "content": prompt}, {"role": "user", "content": task}],
            max_tokens=700, temperature=0.0)
        secs += time.time() - t0
        text = r["choices"][0]["message"]["content"] or ""
        try: plan = repair_json(text)
        except Exception: plan = None
        s = plan.get("steps") if isinstance(plan, dict) else None
        if not s or not all(isinstance(x, dict) for x in s):
            bad += 1; misses.append(f"{task[:40]} -> no usable plan"); continue
        caps = [x.get("capability") for x in s]
        steps += len(caps)
        if want in caps: right += 1
        else: misses.append(f"{task[:40]} -> {caps} want {want}")
    n = len(tasks)
    print(f"\n=== {label}")
    print(f"    prompt {len(prompt)} chars | correct {right}/{n} ({100*right//n}%) "
          f"| unusable {bad} | mean {secs/n:.1f}s | mean steps {steps/max(1,n-bad):.1f} | total {secs:.0f}s")
    for m in misses: print(f"      miss: {m}")
    return {"label": label, "chars": len(prompt), "right": right, "n": n,
            "bad": bad, "mean_s": secs/n, "total_s": secs}

if __name__ == "__main__":
    from llama_cpp import Llama
    variants = json.loads(Path(sys.argv[1]).read_text())
    tasks = bb.HELD_OUT if "--held-out" in sys.argv else bb.TASKS
    print(f"loading model… ({len(tasks)} tasks, {len(variants)} variants)")
    t0 = time.time()
    llm = Llama(model_path=MODEL, n_ctx=8192, n_threads=4, verbose=False)
    print(f"loaded in {time.time()-t0:.1f}s")
    out = []
    for label, prompt in variants.items():
        out.append(score(llm, BASE if prompt == "__BASE__" else prompt, tasks, label))
    print("\n--- summary ---")
    for r in sorted(out, key=lambda x: -x["right"]):
        print(f"  {r['label']:28} {r['right']}/{r['n']}  {r['mean_s']:.1f}s/task  {r['chars']} chars")
    Path(sys.argv[1] + ".result.json").write_text(json.dumps(out, indent=1))
