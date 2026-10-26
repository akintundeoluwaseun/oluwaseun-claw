# Voice command bar

Speak a command, read it back, press Start. Recognition runs on this computer.

## How it works

```
microphone → quick bar (renderer)  ─IPC→  main process  ─localhost→  backend
                                                                       │
                                            sherpa-onnx + Whisper ◄────┘
                                                                       │
                           recognised text → the task field → you press Start
                                                                       │
                                                   the existing planner and tools
```

Five things are kept apart on purpose:

1. **Recognition** turns audio into text. That is all it does.
2. **You** read the text and correct it.
3. **The planner** decides what to do, as it does for typed text.
4. **The tools** do it, under the same permissions and approvals.
5. **Verification** checks the result.

The recogniser never chooses an action. Recognised words are untrusted input, like
a web page or a document: nothing runs until you press Start.

## Turning it on

Voice is **off** until you switch it on — the app never downloads a model by itself.

1. **Settings → Voice → turn on voice input.**
2. Pick a model and press Download. This needs the internet **once**.
3. The microphone button appears in the quick bar.

| Model | Live? | Download | Memory | Speed |
|---|---|---|---|---|
| Quick (English) | no | ~120 MB | 2 GB | Fastest, least accurate |
| **Balanced** (default) | no | ~250 MB | 4 GB | Fast |
| Most accurate | no | ~900 MB | 6 GB | A second or two per command |
| **Live (English)** | **yes** | ~330 MB | 3 GB | Words appear as you speak |

**Live transcription needs the "Live (English)" model.** Whisper cannot stream: it
needs the whole utterance before it can decode anything, so the three Whisper
models show the words after you stop. The Live model is a streaming transducer
that decodes continuously. It is English-only and weaker on names than Whisper —
a real trade, not a free upgrade. Settings shows which model does which, and the
bar adapts automatically.

After the download, recognition works with Wi-Fi and Ethernet switched off.

## Using it

- **Click** the microphone, speak, click again to stop.
- With the Live model the words appear **while you are still talking**, in grey
  italic to show they are provisional. They settle into normal text when you stop.
- Or hold the **push-to-talk** shortcut (default `Ctrl+Shift+V`).
- **Cancel** throws the recording away without recognising it.
- The words land in the task field. Edit them, then press **Start**.

Claw does not listen in the background. There is no always-on mode, and the
setting that would allow one does not exist. The microphone is released the moment
recording stops, before recognition even begins, so the Windows in-use indicator
goes out immediately.

## Privacy

- Audio is held in memory and **never written to disk**. `keep_recordings` is off
  and opt-in.
- Audio never leaves the computer. The modules that handle audio contain no network
  client at all — `test_recognition_path_contains_no_network_code` enforces that.
- The log records how many words were heard, never which ones.
- The quick bar's page cannot reach the network (`connect-src 'none'`); audio goes
  over IPC to the main process.
- Electron's permission handler allows **only** the microphone, **only** for Claw's
  own two windows, and **only** while voice input is on. Everything else is refused.
- `auto_submit` is off by default. Turning it on still cannot bypass approval for a
  sale, a message, a deletion or any other consequential action.

## Test results — 26 October 2026

Environment: Linux build workspace, **no microphone, no sound card, no Windows,
Hugging Face unreachable**. `sherpa-onnx` is pinned but its wheel and a model are
not installed here.

**No accuracy figure is reported, for Nigerian English or any accent.** Nothing has
been spoken into this build. See `docs/VOICE_NIGERIAN_ENGLISH.md`.

| # | Test | Status | Evidence |
|---|---|---|---|
| 1 | Click the microphone and dictate | **BLOCKED** | no microphone or desktop here |
| 2 | Text appears in the bar | **BLOCKED** | needs 1 |
| 3 | Correct the text and submit | **BLOCKED** | needs 1 |
| 4 | Notepad task from recognised text | **BLOCKED** | needs 1 + Windows |
| 5 | Chrome search from recognised text | **BLOCKED** | needs 1 + Windows |
| 6 | Cancel recording | **BLOCKED** | `stopRecording(true)` implemented, not exercised |
| 7 | Microphone released after use | **BLOCKED** | `releaseMic()` implemented, not observable headless |
| 8 | Works with the internet off | **PARTIAL** | no network code in the recognition path (test 14); the offline run itself is blocked |
| 9 | Preferences survive a restart | **PASS** | `test_settings_roundtrip_keeps_voice` |
| 10 | Different microphone devices | **BLOCKED** | no audio hardware |
| 11 | Missing, corrupt, incompatible models | **PASS** | `test_store_reports_damaged_separately_from_missing`, `test_a_corrupted_download_is_refused_and_leaves_nothing`, `test_damaged_model_is_reported_not_loaded`, `test_store_ignores_a_folder_without_usable_meta` |
| 12 | Noisy recording | **BLOCKED** | needs real recordings |
| 13 | Numbers, product and place names | **BLOCKED** | this is accuracy — needs recordings |
| 14 | No cloud request while transcribing | **PASS** | `test_recognition_path_contains_no_network_code` |
| 15 | Global hotkey and floating window | **BLOCKED** | needs a Windows desktop |
| 16 | Emergency stop and confirmations | **PASS (inherited)** | voice text enters the same planner: `test_declined_approval_stops_without_writing`, `test_cancel_while_waiting`, `test_destructive_floor_enforced` |
| 17 | Local AI unavailable, separately from speech | **PASS** | `test_recognition_works_with_no_brain_installed`, `test_voice_status_is_separate_from_the_brain` |
| 18 | No disk space; download interrupted | **PASS** | `test_no_disk_space_is_reported_before_downloading`, `test_cancelling_removes_the_partial_model` |
| 19 | Live partials grow while speaking | **PASS** (fake engine) | `test_words_appear_while_speaking` |
| 20 | Live audio resampled without seams | **PASS** | `test_stream_resampler_matches_whole_file_resampling` — chunked output is bit-identical to resampling the whole recording |
| 21 | Cancel a live recording | **PASS** | `test_cancelling_a_live_recording_stops_it_dead` |
| 22 | One live recording at a time; no leaks | **PASS** | `test_only_one_live_recording_at_a_time`, `test_an_abandoned_recording_does_not_pin_the_model` |
| 23 | A non-streaming model says so | **PASS** | `test_a_model_that_cannot_stream_says_so` |

**12 PASS, 1 PARTIAL, 10 BLOCKED.** Backend suite: 70 voice tests, 262 overall,
0 failures; 8 desktop tests.

`sherpa-onnx` 2.0.1 **is now installed in the build workspace**, so the adapter is
written against the library's real API rather than remembered names:
`OfflineRecognizer.from_whisper(encoder, decoder, tokens)` and
`OnlineRecognizer.from_transducer(tokens, encoder, decoder, joiner, …)` were both
checked by introspection. What is still missing here is a model and a microphone. Audio conversion, the model manager (checksums, corruption, resume,
cancellation, licence refusal, disk space), the service, settings and the API are
all covered by real tests, as is the live streaming path end to end with a fake
engine. **Microphone capture, the floating bar on screen, real streaming
recognition and every accuracy question are untested.**

## Running the blocked tests on Windows

```powershell
git checkout claude/ecstatic-ritchie-x6ao14
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -Chromium
cd backend; .\.venv\Scripts\python.exe -m pip install sherpa-onnx==2.0.1; cd ..
powershell -ExecutionPolicy Bypass -File scripts\start.ps1
```

Then: Settings → Voice → on → download **Balanced**. Click the microphone, say
*"Open Notepad and write my assignment"*, check the words, press Start. For test 8,
turn off Wi-Fi and Ethernet first and confirm recognition still works. For test 7,
watch the microphone icon in the Windows system tray go out when you stop.

## Known limitations

1. Never run on Windows; never run with a real microphone or a real model.
2. No accuracy measurement of any kind, Nigerian English included.
3. The models are general English/multilingual Whisper exports, not tuned for
   Nigerian English. Expect trouble with names like *Ado-Ekiti* and *Adebayo*
   until this is measured and biased accordingly.
4. No live/incremental transcription: the bar recognises one finished utterance.
   The engine supports streaming; the bar does not use it yet.
5. Push-to-talk ends an utterance on a 400 ms gap in the shortcut's auto-repeat,
   because a global shortcut has no key-up event. Needs tuning on real hardware.
6. `input_device` is stored but not yet honoured — the system default microphone
   is used.
7. The catalogue's repository names could not be verified from the build
   workspace. A wrong or relicensed repository fails the download with a clear
   message and installs nothing, but the first real download is the first proof
   they are right.
