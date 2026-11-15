# Claw's brain

Claw thinks with a language model that runs **on the user's own computer**. It needs no
account, no API key and no internet connection once the brain is on the machine. Ollama is
**not** needed.

## The engine
- **llama.cpp `llama-server`** (MIT), started and stopped by Claw itself (`backend/claw/runtime/engine.py`).
- Always bound to `127.0.0.1` on a random free port, with a random API key for each launch.
  Nothing else on the network, or on the computer, can use it.
- Claw checks free memory before loading and refuses with a plain explanation if the brain
  clearly won't fit. Out-of-memory, damaged files, crashes and slow loads (5-minute limit) are
  reported in plain words with the engine's own last messages.
- After a crash Claw restarts it automatically (twice at most). It unloads after 10 idle minutes
  (Settings: `idle_unload_minutes`) to give memory back.
- If the backend is killed outright, the engine stops too (Linux: parent-death signal, tested;
  Windows: a job object with kill-on-close, **not yet tested on Windows**).
- Where it comes from: installed apps carry it in `resources\engine`. Developer copies get the
  newest official Windows build from `scripts\setup.ps1` (looked up in llama.cpp's GitHub release
  list at run time, checksum-verified when GitHub publishes one).

## Thinking brains — the one thing to know before choosing one

Some brains "think" before answering: they write a chain of reasoning, then the
answer. **On a small brain on a plain processor this can mean no answer at
all.** Measured on a real `llama-server` with a 2B brain on four cores,
temperature 0, asked "What is the capital of France?":

| reply budget | time | answer |
|---|---|---|
| 512 tokens | 38.2s | **nothing** |
| 1024 tokens | 82.7s | **nothing** |
| 1536 tokens | 127.1s | **nothing** |
| 2048 tokens | 160.7s | **nothing** |

The reasoning simply grows to fill whatever budget it is given, so a bigger
budget does not help — it just costs more. The same question, with thinking
switched off: **1.4 seconds, answered correctly.** On planning it was the
difference between a usable plan 2 times in 16 and 16 times in 16.

So **Claw asks every brain not to think**, on every call. Two consequences
worth knowing:

- **The engine has to support being asked.** Claw sends
  `chat_template_kwargs`, which `llama-server` only honours when started with
  `--jinja` — which Claw always does. An engine too old to accept the field is
  detected, falls back safely, and is **reported in Settings → Claw's brain
  when you test the brain**. On such an engine a thinking brain may answer
  nothing; the fix is a newer llama.cpp build, or a brain that doesn't think.
  `scripts\setup.ps1` checks the build it downloads.
- **Claw never shows you a brain's private reasoning.** `llama-server` returns
  it in a separate field; Claw reads it in exactly one place, to explain an
  empty answer in plain words, and never repeats it as a reply.

The contract and the measurements are written into
`backend/claw/models/openai_compat.py`, at the top, because getting this wrong
cost five rounds of performance work aimed at the wrong thing.

## The brains
| | Standard brain | Pro brain |
|---|---|---|
| Model | Qwen3-VL 4B Instruct | Qwen3-VL 8B Instruct |
| Source | `Qwen/Qwen3-VL-4B-Instruct-GGUF` | `Qwen/Qwen3-VL-8B-Instruct-GGUF` |
| Files | `*Q4_K_M.gguf` + `mmproj*F16.gguf` | same |
| Download (approx.) | 3.3 GB | 6.2 GB |
| Suited to | 8 GB memory or more | 16 GB memory, or a graphics card with 8 GB |
| Reads screenshots | yes (mmproj) | yes (mmproj) |
| Licence | Apache-2.0 (shown on the Hugging Face page; checked again by Claw before every download) | Apache-2.0 (same check) |

- File names, sizes and SHA-256 checksums are **not hard-coded**: Claw asks the Hugging Face API
  (`/api/models/<repo>?blobs=true`) at download time, refuses any repository whose licence is not
  Apache-2.0 or MIT, checks free disk space (+1 GB margin), downloads with resume, verifies the
  SHA-256 when Hugging Face provides one and deletes the file if it does not match.
- Downloads start only when the user presses **Download** (the size is shown on the button).
  Nothing large is downloaded automatically.
- "Best for this computer" is chosen from total memory and graphics memory; a brain that may not
  fit can still be downloaded after a warning.

## Editions
- **Standard installer**: app + engine + OCR + Standard brain (~3.6 GB, one `Setup.exe`).
- **Pro installer**: app + engine + OCR + Pro brain (~6.5 GB; `Setup.exe` plus `Setup-N.bin`
  parts that must stay together, because one Inno Setup file holds about 4.2 GB at most).
- A small installer without a brain can also be built (`build-release.ps1 -NoBrain`); it
  downloads the brain on first run.
- Bundled brains live in `resources\models\<id>\manifest.json` and are never deleted by Claw.

## Settings → Claw's brain
- Engine status, the brain in use, Download (with progress and Cancel), Use this, Remove
  (with confirmation; only downloaded brains can be removed), **Use a GGUF file I have**
  (choose the model and, optionally, its `mmproj` vision file together; Claw never deletes your
  file), and **Restart the brain**.
- Developer section: point Claw at any OpenAI-compatible local server (for example a
  `llama-server` you run yourself). Ollama remains available here as an **optional** adapter.

## When there is no brain
Claw still opens, reads documents (including OCR of scanned pages), searches them and saves
searchable PDFs. Planning, tasks and summaries say clearly that the brain is needed.
