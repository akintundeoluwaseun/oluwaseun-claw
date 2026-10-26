# Claw's brain

Users never pick or download models and never enter keys. Claw has one built-in
brain that runs entirely on the user's computer.

## How it works today (development builds)
- Claw measures memory, processor cores and NVIDIA GPU memory, then picks:

| Role | Computer | Model | Approx. size |
|---|---|---|---|
| Thinking | 28 GB+ RAM or 12 GB+ VRAM | qwen2.5:14b | 9 GB |
| Thinking | 14 GB+ RAM or 7 GB+ VRAM | qwen2.5:7b | 4.7 GB |
| Thinking | 7 GB+ RAM | qwen2.5:3b | 1.9 GB |
| Thinking | smaller | qwen2.5:1.5b | 1 GB |
| Seeing (screenshots) | 22 GB+ RAM or 9 GB+ VRAM | qwen2.5vl:7b | 6 GB |
| Seeing (screenshots) | 11 GB+ RAM or 5 GB+ VRAM | qwen2.5vl:3b | 3.2 GB |

- Development builds use the Ollama engine and fetch the model on first run.
- To keep the computer responsive: under 24 GB Claw unloads the thinking model before reading
  a screenshot, models unload two minutes after Claw goes quiet, and 1–2 cores stay free.
- Only the tools a task's plan needs are described to the model in full, to keep prompts short
  for small models.
- Sizes and thresholds are estimates, not yet measured on real laptops.

## Release builds (Batch 5 — decided, not built yet)
- **The engine and the brain ship inside the installer.** No download on first launch, works
  offline from the start. Engine: llama.cpp `llama-server` (MIT). Brain: GGUF model files.
- Because one installer can't know the computer in advance, Batch 5 must decide between one
  installer per size (e.g. "standard" with a 3B model, "pro" with a 7B model) or one larger
  installer containing two sizes. See `IMPLEMENTATION_PLAN.md`.

## Licenses
Qwen2.5 and Qwen3 repositories state Apache 2.0, but some sizes (notably qwen2.5:3b) use a
Qwen research licence that restricts commercial use. **Bundling a model in a distributed
installer makes this binding: Batch 5 must pick sizes whose licence allows redistribution.**

## Developer setting
Settings → Claw's brain → Developer points Claw at any Ollama or llama.cpp server and model.
