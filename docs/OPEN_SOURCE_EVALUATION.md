# Open-source components evaluated for S-CLAW

Dated 27 October 2026. 39 projects, each checked against the repository itself
rather than a search result.

## How these were verified, and what that does not cover

This build container cannot reach `api.github.com` (the egress proxy answers
403), so stars, issue counts and commit history were not available. What *was*
reachable, and what every row below rests on:

| Evidence | Source | What it proves |
|---|---|---|
| The project exists, at that exact path | `raw.githubusercontent.com/<repo>/<branch>/LICENSE` returned 200 | the repository and branch are real |
| The licence | the text of that file, read and classified | the licence as the project itself states it |
| Maintenance | the latest release on PyPI or npm, with its upload date | something was published, and when |

**All 39 repositories were reached. None is taken on trust from a snippet.**

Three licences were misread by the automatic classifier and corrected by hand:

- **Remotion** is *not* MIT. `LICENSE.md` is the "Remotion License": free for
  individuals and small entities, paid for larger companies. A classifier that
  matches on wording would have shipped a licence violation.
- **piper1-gpl** is **GPL-3.0**, not AGPL-3.0.
- **YaCy** keeps its licence in `gpl.txt`, not `LICENSE`, and it is **GPL-2.0**.

What no amount of reading can establish, and what is therefore *not* claimed
anywhere below: that any of these works inside Claw. Nothing here has been
installed, run or integrated except where a row says so explicitly.

## Licence policy for Claw

Claw ships as a Windows installer, so a dependency's licence travels with it:

- **Fine to bundle:** MIT, Apache-2.0, BSD, MPL-2.0.
- **Only at arm's length** (a separate process the user installs and Claw talks
  to over a socket, never linked or bundled): GPL, LGPL, AGPL.
- **Never without a commercial decision:** anything whose terms depend on who
  the user is, or that is dual-licensed with a paid tier.

The model weights are licensed separately from the runtime, every time. An
Apache-2.0 inference engine says nothing about the model it loads.

---

## A. Inference

### 1. ggml-org/llama.cpp — **ADOPTED (already in use)**
<https://github.com/ggml-org/llama.cpp> · **MIT** (`master/LICENSE`)
C++ inference engine and OpenAI-compatible HTTP server. Already Claw Local's
engine, fetched by `scripts/setup.ps1` and launched by `claw/runtime/engine.py`
on 127.0.0.1 with a per-launch key. MIT, CPU-capable, no account, no network.
**Decision: keep.** Nothing evaluated here is a reason to change it. The gap is
not the engine — it is that this container cannot obtain weights or compile it
(the sandbox refuses to compile downloaded external code).

### 2. vllm-project/vllm — **ADOPT FOR THE SERVER, NOT THE CLIENT**
<https://github.com/vllm-project/vllm> · **Apache-2.0** · PyPI `vllm` 0.32.0 (2026-10-18)
Very actively released. GPU-first: it wants NVIDIA hardware and tens of GB of
VRAM for a useful model. That makes it a candidate for the Claw Online *server*
and a non-candidate for the desktop. **Decision: adopt if and when the service
is hosted on GPU hardware; not now, and not in the installer.**

### 3. sgl-project/sglang — **STUDY**
<https://github.com/sgl-project/sglang> · **Apache-2.0** · PyPI `sglang` 0.5.22 (2026-10-16)
Same role and same hardware demands as vLLM, with better structured-output
handling, which matters because Claw constrains the model to a JSON schema.
**Decision: compare against vLLM when the service is actually funded and sized.
Choosing between them on paper would be guessing.**

### 4. BerriAI/litellm — **ADOPT (gateway only)**
<https://github.com/BerriAI/litellm> · **MIT** · PyPI `litellm` 1.106.4 (2026-10-25)
One OpenAI-shaped interface over many providers, plus a proxy with per-key rate
limits and spend caps — exactly the shape of the Claw Online gateway, and the
part that is tedious to write. It supplies **no compute**: it routes to a
provider someone pays for. **Decision: adopt for the server when it is built.
Not a client dependency; it must never be in the installer.**

### 5. ollama/ollama — **REJECT for bundling, keep as an adapter**
<https://github.com/ollama/ollama> · **MIT** · PyPI `ollama` 0.6.3 (2026-09-29)
Claw already has an Ollama adapter for developers who run it. As Claw Local's
engine it would mean shipping a second model manager with its own store and its
own daemon, duplicating `claw/runtime/`. **Decision: keep the optional adapter,
do not bundle.**

### 6. mudler/LocalAI — **REJECT**
<https://github.com/mudler/LocalAI> · **MIT**
An OpenAI-compatible server over many backends. Claw already has that interface
pointed at llama-server; this would add a layer without removing one.

### 7. huggingface/text-generation-inference — **REJECT**
<https://github.com/huggingface/text-generation-inference> · **Apache-2.0** ·
PyPI client `text-generation` 0.7.0 — last published **2024-03-22**, over two
years ago. GPU-first like vLLM, with a client that looks abandoned. vLLM and
SGLang are better-maintained answers to the same question.

---

## B. Windows desktop control

### 8. pywinauto/pywinauto — **ADOPTED (already in use)**
<https://github.com/pywinauto/pywinauto> · **BSD-3-Clause** · PyPI 0.6.9 (2025-01-06)
UI Automation and Win32 control from Python — already how `claw/computer/
windows_uia.py` finds windows and controls. Last release is ~10 months old,
which for a mature wrapper over a frozen Windows API is ordinary, not alarming.
**Decision: keep.** Claw's desktop gap is that no Windows machine has run the
acceptance tests, not that the library is wrong.

### 9. microsoft/WinAppDriver — **USE FOR TESTING ONLY**
<https://github.com/microsoft/WinAppDriver> · **MIT**
A WebDriver server for Windows apps. Useful as an *independent* check in the
acceptance suite — a second implementation agreeing that Notepad opened is worth
more than Claw agreeing with itself. **Decision: optional test dependency on the
Windows runner, never shipped.** Microsoft's own activity on it has been thin
for years; verify before leaning on it.

### 10. FlaUI/FlaUI — **STUDY**
<https://github.com/FlaUI/FlaUI> · **MIT**
.NET UI Automation wrapper, generally considered the cleaner UIA3 binding.
Reaching it from Python means a .NET bridge, which is a real cost. **Decision:
read its element-location strategies; do not take the dependency.**

### 11. bytedance/UI-TARS-desktop — **STUDY ONLY**
<https://github.com/bytedance/UI-TARS-desktop> · **Apache-2.0** (code; the model
is licensed separately and must be checked on its own)
A vision-model-driven desktop agent. Adopting its stack would mean adopting a
different safety posture — Claw's whole design is observe → validate → act →
verify with an approval floor, and a screenshot-driven agent that clicks what it
sees is the opposite. **Decision: study the grounding ideas, reject the stack.**

### 12. ibraheem-mustafa-dev/windowsagent — **REJECT (unverifiable quality)**
<https://github.com/ibraheem-mustafa-dev/windowsagent> · **MIT**
The repository and licence are real. Nothing else about it could be verified
from here — no release on any registry, no way to check issues or history. An
unknown single-author project that drives the user's desktop is exactly the kind
of dependency to be slow about. **Decision: reject for now; revisit only with
evidence of maintenance and a read of its source.**

### 13. sandraschi/windows-computer-use-mcp — **REJECT (same reason)**
<https://github.com/sandraschi/windows-computer-use-mcp> · **MIT**
Exists; otherwise unverifiable here. Its own README's claims are not evidence.

### 14. microsoft/PowerToys — **STUDY**
<https://github.com/microsoft/PowerToys> · **MIT**
Not an automation engine. Worth reading for how it registers global hotkeys
without stealing them from other apps, which is Claw's push-to-talk problem.

---

## C. Browser and search

### 15. microsoft/playwright — **ADOPTED (already in use)**
<https://github.com/microsoft/playwright> · **Apache-2.0** · PyPI 1.64.1 (2026-10-22), npm 1.64.1 (2026-10-14)
Released this month. Already drives Claw's browser via Edge. **Decision: keep.**
Today's work hardened its error paths rather than replacing it.

### 16. browser-use/browser-use — **REJECT for now**
<https://github.com/browser-use/browser-use> · **MIT** · PyPI 0.13.14 (2026-10-26)
Extremely active. It is an *agent*: it wants to drive the model loop itself.
Claw already owns that loop, with its own approvals and verification. Taking it
would mean either two agent loops or replacing Claw's. **Decision: reject the
framework; its DOM-serialisation approach is worth reading.** Note it also sells
a hosted service — the library is MIT, the cloud is not the library.

### 17. browser-use/browser-harness — **STUDY**
<https://github.com/browser-use/browser-harness> · **MIT**
Driving the user's *real* browser with their logged-in sessions. Powerful and
dangerous in equal measure: every site the user is signed into becomes reachable
by a model. **Decision: do not adopt without an explicit consent design.**

### 18. searxng/searxng — **ADAPT (interface yes, bundle no)**
<https://github.com/searxng/searxng> · **AGPL-3.0** · PyPI `searxng` 0.1.2 (2026-09-09)
A self-hostable metasearch engine with a JSON API. The right answer to "stop
depending on one engine's HTML" — but **AGPL-3.0**, so Claw must never bundle or
link it. Reached over HTTP as a separate service the user or operator runs, the
AGPL does not reach Claw's code. **Decision: support it as a configurable search
backend; never ship it.** It also needs a reachable host and working upstreams —
it is not a source of internet access.

### 19. yacy/yacy_search_server — **REJECT**
<https://github.com/yacy/yacy_search_server> · **GPL-2.0** (`gpl.txt`)
Distributed search, Java, heavy to operate, and its result coverage for ordinary
queries is not comparable. Same licence caution as SearXNG with less benefit.

### 20. unclecode/crawl4ai — **STUDY**
<https://github.com/unclecode/crawl4ai> · **Apache-2.0** · PyPI 0.9.5 (2026-10-14)
Structured extraction from pages, Apache-2.0, active. Claw already reads pages
through its own extractor. **Decision: revisit only if page reading proves weak
on real sites — which cannot be judged from a container with no internet.**

### 21. firecrawl/firecrawl — **REJECT**
<https://github.com/firecrawl/firecrawl> · **AGPL-3.0** (the server; the JS
client on npm is MIT) · npm client 4.51.0 (2026-10-22)
Crawling and extraction, but the useful part is the AGPL server, and the product
is built around a paid hosted API. Wrong licence and wrong shape for a desktop
app that must work without an account.

---

## D. Voice

### 22. k2-fsa/sherpa-onnx — **ADOPTED (already in use)**
<https://github.com/k2-fsa/sherpa-onnx> · **Apache-2.0** · PyPI 2.0.1 published **2026-10-27 (today)**
Offline speech recognition, synthesis and VAD, Windows included. Already Claw's
speech engine. Apache-2.0 and released today. **Decision: keep.** The gap is that
no person has spoken into it, not the library.

### 23. SYSTRAN/faster-whisper — **STUDY**
<https://github.com/SYSTRAN/faster-whisper> · **MIT** · PyPI 1.2.1 (2025-10-31)
Whisper via CTranslate2. Likely more accurate than a small zipformer on accented
English, which is the Nigerian-English question — but it is not streaming in the
way push-to-talk partials want, and it adds a second runtime. **Decision: the
right candidate to benchmark *against measured Nigerian-English samples*, which
do not exist yet. Benchmarking it before those samples exist would prove
nothing.**

### 24. ggml-org/whisper.cpp — **STUDY**
<https://github.com/ggml-org/whisper.cpp> · **MIT** · PyPI binding `pywhispercpp` 1.5.1 (2026-08-22)
Same model family, C++ runtime, good on low-spec machines, and Claw already
ships a ggml runtime for llama.cpp. **Decision: second candidate in the same
benchmark.**

### 25. OHF-Voice/piper1-gpl — **REJECT for bundling**
<https://github.com/OHF-Voice/piper1-gpl> · **GPL-3.0** (`COPYING`), PyPI
`piper-tts` 1.8.0 declares GPL-3.0-or-later
Good offline text-to-speech, wrong licence to bundle in Claw's installer, and
each voice model carries its own licence on top. sherpa-onnx already provides
TTS under Apache-2.0. **Decision: reject unless run as a separate process the
user installs themselves.**

### 26. snakers4/silero-vad — **ADOPT (candidate)**
<https://github.com/snakers4/silero-vad> · **MIT** · PyPI 6.2.3 (2026-09-23)
Small, MIT, well-maintained voice-activity detection. It would make push-to-talk
end cleanly on silence instead of on a key release alone, and it is the single
cheapest voice improvement available. **Decision: adopt when voice work resumes;
sherpa-onnx also carries a VAD, so compare the two before adding a dependency.**

---

## E. Messaging

### 27. wwebjs/whatsapp-web.js — **STUDY**
<https://github.com/wwebjs/whatsapp-web.js> · **Apache-2.0** · npm 1.34.7 (2026-04-24)
Drives WhatsApp Web through a headless browser. Six months since the last
publish, against a service that changes without notice — that gap is the risk.
Also: automating WhatsApp is against WhatsApp's terms, and an account can be
banned. **Decision: no adoption without the user accepting that risk explicitly.**

### 28. wppconnect-team/wppconnect — **REJECT (licence)**
<https://github.com/wppconnect-team/wppconnect> · **LGPL-3.0-or-later** · npm 2.3.6 (2026-10-23)
Better maintained than whatsapp-web.js, but LGPL inside an Electron bundle is a
licence problem Claw should not take on for an optional integration.

### 29. WhiskeySockets/Baileys — **STUDY, PINNED**
<https://github.com/WhiskeySockets/Baileys> · **MIT** · npm 7.0.0-rc14 (2026-07-29)
Speaks the WhatsApp protocol directly — no browser, far lighter. The current
release is a **release candidate**, which is a reason to pin an exact version
rather than track the tag. Same terms-of-service risk.

---

## F. Calendar

### 30. Kozea/Radicale — **ADAPT (protocol yes, server no)**
<https://github.com/Kozea/Radicale> · **GPL-3.0** (`COPYING.md`; PyPI says GNU GPL v3) · PyPI 3.9.0 (2026-10-25)
A small, active CalDAV server. GPL, so not bundled — but the *protocol* is the
point: writing Claw against CalDAV means it works with Radicale, Nextcloud,
Fastmail and iCloud without a separate connector each. **Decision: build a
CalDAV client against the standard; use Radicale as a local test fixture, run as
its own process.**

### 31. nextcloud/server — **REJECT**
<https://github.com/nextcloud/server> · **AGPL-3.0**
An entire collaboration platform. Installing it to add a calendar connector is
exactly what the brief warns against.

### 32. calcom/cal.com — **REJECT**
<https://github.com/calcom/cal.com> · MIT at the root, but the product is
structured around an enterprise edition and a hosted service. It solves
*booking*, not "what is on my calendar" — the wrong problem.

---

## G. Documents

### 33. microsoft/markitdown — **ADOPT (candidate)**
<https://github.com/microsoft/markitdown> · **MIT** · PyPI 0.1.9 (2026-10-21)
Converts many formats to Markdown. MIT, active, small surface. Claw already
handles PDF, DOCX, XLSX and text; this would add PowerPoint, HTML, EPUB and
images in one dependency. **Decision: the best-value document addition, but it
pulls a dependency tree that has to be read before it enters a signed installer.**

### 34. pymupdf/PyMuPDF — **REJECT (licence)**
<https://github.com/pymupdf/PyMuPDF> · **AGPL-3.0 or commercial** · PyPI 2.0 (2026-10-19)
Faster and better at PDF layout than what Claw uses. AGPL-or-pay, inside a
desktop installer. Claw's existing `pypdfium2` (BSD/Apache) is the licence-safe
choice and already works. **Decision: reject while Claw ships unpaid.**

### 35. ocrmypdf/OCRmyPDF — **STUDY**
<https://github.com/ocrmypdf/OCRmyPDF> · **MPL-2.0** · PyPI 17.13.0 (2026-09-28)
Adds a searchable text layer to scanned PDFs, over the Tesseract that Claw
already bundles. MPL-2.0 is bundleable. Claw already produces searchable PDFs;
this would mostly improve quality. **Decision: revisit if OCR output disappoints
on real documents.**

### 36. docling-project/docling — **STUDY**
<https://github.com/docling-project/docling> · **MIT** · PyPI 2.143.0 (2026-10-27)
Strong structured extraction — tables, reading order, complex layouts. MIT and
published today. It also downloads its own models and wants real memory.
**Decision: too heavy for the default install; a candidate for Claw Local only,
and only with measured benefit.**

---

## H. Video and motion (not needed yet)

### 37. remotion-dev/remotion — **REJECT (licence)**
<https://github.com/remotion-dev/remotion> · **NOT open source.** `LICENSE.md`
is the "Remotion License": permission depends on the type of legal entity, and
companies above a size threshold must pay. npm declares `SEE LICENSE IN
LICENSE.md`, not a licence name. **Decision: reject.** An automatic licence
classifier called this MIT; it is not. Shipping it in a product would be a
licence violation.

### 38. motion-canvas/motion-canvas — **STUDY**
<https://github.com/motion-canvas/motion-canvas> · **MIT** · npm `@motion-canvas/core` 3.17.2, last published **2024-12-14** — nearly two years.
MIT and usable, but quiet.

### 39. ManimCommunity/manim — **STUDY**
<https://github.com/ManimCommunity/manim> · **MIT** · PyPI 0.22.0 (2026-10-08)
Active, MIT, Python — the natural fit if Claw ever generates explanatory
animations. Needs FFmpeg and a LaTeX install for text. **Decision: nothing to do
until video is an actual requirement.**

---

## What this changes, in order

1. **Nothing about the engine or the browser.** llama.cpp, Playwright, pywinauto
   and sherpa-onnx are the right components and are already here. The gaps in
   the 27 October report are an absent Windows desktop, absent weights, absent
   credentials and absent internet — none of which a dependency fixes.
2. **A search-provider interface** so Claw is not married to one engine's HTML,
   with SearXNG reachable over HTTP as one backend. *Implemented today.*
3. **LiteLLM** as the Claw Online gateway, when there is a server to put it on.
   It removes the per-user API key; it does not remove the compute bill.
4. **CalDAV**, written against the protocol, with Radicale as a test fixture.
5. **Silero VAD or sherpa's own**, when voice work resumes and there are
   recordings to measure against.
6. **MarkItDown**, after its dependency tree is read.

Rejected outright, with reasons above: Remotion (licence), PyMuPDF (licence),
piper1-gpl (licence), wppconnect (licence), Firecrawl (licence and shape),
Nextcloud and Cal.com (far too large), LocalAI and TGI (redundant or stale),
browser-use (duplicate agent loop), and the two unverifiable single-author
Windows agents.
