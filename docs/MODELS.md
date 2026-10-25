# Choosing a local model

Oluwaseun Claw does not need any paid AI service. It talks to a model server
running on your own computer:

- **Ollama** (default) — install from https://ollama.com/download, then e.g. `ollama pull qwen2.5:7b`.
- **llama.cpp `llama-server`** — run `llama-server -m model.gguf --port 8080` and pick
  "llama.cpp server" in Settings.

## Suggested starting points (not yet measured)

Hardware needs have **not been measured** for this project yet: the build
workspace cannot download model weights. The table below is a starting guide
only; real figures will be recorded in this file after testing on actual
Windows 10 machines (Batch 2).

| Model (Ollama tag) | Approx. download | Typical fit | Notes |
|---|---|---|---|
| `qwen2.5:7b` | ~4.7 GB | 16 GB RAM, or GPU with 8 GB VRAM | Good planning quality; recommended first try |
| `qwen2.5:3b` | ~1.9 GB | 8 GB RAM | Faster, weaker plans; check license below |
| `qwen2.5:1.5b` | ~1 GB | 8 GB RAM, slow CPUs | May fail to follow the JSON plan format |
| `qwen3:8b` | ~5 GB | 16 GB RAM or 8 GB VRAM | Newer family; test before relying on it |

Running tasks (not just planning) needs a model that reliably returns the agent's JSON
action format. Small models (1.5B–3B) are likely to fail this more often; this has not
been measured yet.

How to choose: start with the largest model your RAM can hold with a few GB to
spare. If planning takes longer than the timeout in Settings, choose a smaller
model or raise the timeout. If plans are rejected ("did not produce a usable
plan"), choose a larger model.

## Licenses of model weights

Runtime licenses (Ollama, llama.cpp) are separate from **weight** licenses.
The Qwen2.5 and Qwen3 repositories state Apache 2.0, but individual Qwen2.5
sizes (notably 3B and 72B) have been published under different Qwen licenses.
**Check each model card on Hugging Face before redistributing or using a model
commercially.** This app does not bundle any model weights.
