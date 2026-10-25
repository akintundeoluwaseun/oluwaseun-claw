# Claw's brain

Users never pick models. On first launch Claw asks one question, Online or
Offline, and handles the rest.

## Online (default suggestion)
- Uses Google's Gemini API with **the user's own free key** (created at
  https://aistudio.google.com/apikey, no card needed). Nothing else to install.
- Claw reads the key's model list and picks the model itself, preferring
  **Flash-Lite** (the largest free daily allowance), then Flash. When one
  model's daily limit is reached it moves to the next.
- Screenshots can be read by the same model (needed for `describe_screen`).
- Free-tier limits (reported by developers in 2026, not measured by us): about
  500 requests/day for Flash-Lite and 20/day for Flash, per key. A task uses
  roughly 10–25 requests. Limits reset at midnight Pacific time (about 8–9 AM in Lagos).
- Google says free-tier requests may be reviewed and used to improve its
  products, so the welcome screen recommends Offline for private documents.
- The key is stored encrypted with Windows DPAPI in `secrets.bin`, never in
  `settings.json`, never logged, never sent back to the UI.

## Offline
- Claw measures memory, processor cores and NVIDIA GPU memory, then picks:

| Role | Computer | Model (Ollama tag) | Approx. download |
|---|---|---|---|
| Thinking | 28 GB+ RAM or 12 GB+ VRAM | qwen2.5:14b | 9 GB |
| Thinking | 14 GB+ RAM or 7 GB+ VRAM | qwen2.5:7b | 4.7 GB |
| Thinking | 7 GB+ RAM | qwen2.5:3b | 1.9 GB |
| Thinking | smaller | qwen2.5:1.5b | 1 GB |
| Seeing | 22 GB+ RAM or 9 GB+ VRAM | qwen2.5vl:7b | 6 GB |
| Seeing | 11 GB+ RAM or 5 GB+ VRAM | qwen2.5vl:3b | 3.2 GB |

- It downloads the thinking model first, with progress on screen, then the
  seeing model. If a model isn't in the library it falls back to the next size.
- To keep the computer responsive: on machines under 24 GB Claw unloads the
  thinking model before reading a screenshot, models unload two minutes after
  Claw goes quiet, and Claw leaves 1–2 processor cores free.
- **Currently requires the free Ollama engine to be installed** (the app links
  to it). Bundling it into Claw's installer is a Batch 5 task.
- Sizes and thresholds are estimates; they have not been measured on real laptops.

## Licenses
Qwen2.5 and Qwen3 repositories state Apache 2.0, but some sizes (notably
qwen2.5:3b) use a Qwen research licence. Check model cards before commercial use.
Google's API terms apply to Online mode.

## Developer setting
Settings → Claw's brain → Developer lets a developer point Claw at any Ollama or
llama.cpp server and model. Normal users never need it.
