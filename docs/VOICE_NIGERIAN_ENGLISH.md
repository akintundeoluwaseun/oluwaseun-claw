# Nigerian English accuracy — measurement plan

**Status: NOT MEASURED.** No accuracy figure for Claw's voice input exists yet,
for Nigerian English or any other accent.

This is not an oversight to be filled in with a plausible number later. The build
workspace is Linux with no microphone, no sound card and no reachable model
library, so no recording has ever been passed through the recogniser here. Any
word error rate, intent accuracy or "works well with Nigerian accents" claim
written before the steps below are carried out would be invented.

Published benchmarks for Whisper are measured on American and British read
speech (LibriSpeech, Common Voice, FLEURS). They do not transfer to Nigerian
English, and quoting them here would be the same fabrication wearing a citation.

---

## What has to exist first

1. Windows 10/11 with a working microphone.
2. Claw installed, **Settings → Voice → enabled**, and one model downloaded.
3. Recordings from real speakers — see below. Synthetic speech does not count:
   text-to-speech reproduces the accent of whatever voice generated it, not of a
   Nigerian speaker, so it measures the TTS engine rather than the recogniser.

## The recording set

At least **five speakers**, mixed gender, mixed age, each recording the whole
prompt list. Two hundred utterances in total is enough for a first reading;
fewer than fifty tells you nothing useful.

For each speaker record:

| Condition | Why |
|---|---|
| Quiet room, headset microphone | the ceiling: best case |
| Quiet room, laptop microphone | what most people actually have |
| Background noise — fan, street, generator, other voices | the common Nigerian office and home case |
| Fast, natural speed | dictation is rarely slow and careful |

Save each as 16-bit mono WAV, 16 kHz or higher, one utterance per file, with a
reference transcript beside it in a plain-text file of the same name.

## The prompts

Everyday commands, already in Claw's vocabulary:

1. Open Notepad and write my assignment.
2. Open Chrome and search for industrial engineering internships in Nigeria.
3. Open TechDesk and search for Samsung Galaxy S21.
4. Check my downloads folder.
5. Open WhatsApp and check for unread messages.
6. Create a folder named School Documents.
7. Find my project proposal and summarise it.
8. Open my calendar and show tomorrow's appointments.
9. Search for Ado-Ekiti.
10. Create a report and save it in Documents.

Then the parts general models are weakest at, which matter most to this app:

- **Place names:** Ado-Ekiti, Ikeja, Abeokuta, Maiduguri, Oyo, Enugu, Port Harcourt, Owerri.
- **Personal names:** Adebayo, Chidinma, Oluwaseun, Ngozi, Yusuf, Folake, Emeka.
- **App and product names:** TechDesk, Claw, Samsung Galaxy S21, Infinix Hot 40, phone charger, power bank.
- **Money and quantity:** forty-five thousand naira; two thousand five hundred naira; two phone chargers; twelve units; ₦1,200.
- **Dates and times:** thirtieth of November; next Tuesday at 10 AM; tomorrow morning.
- **File names:** project proposal dot docx; claw-test dot txt; second semester results.
- **Short commands:** Stop. Cancel. Open Chrome.
- **Long instruction:** one sentence of at least 25 words combining two actions.

## What to measure

Record all four. A single percentage hides the thing that matters.

| Measure | How | Why it matters |
|---|---|---|
| **Word error rate** | standard WER against the reference, after lowercasing and stripping punctuation | comparable to published figures |
| **Command intent accuracy** | did Claw's planner choose the right tool and target from the transcript? | a transcript can be wrong and the task still right — and the reverse |
| **Number, money and date accuracy** | exact match on the numeric span | "two" vs "2" vs "to" decides a sale |
| **Product and place name accuracy** | exact match on the name span | the difference between finding a product and not |

Report each **per condition and per speaker**, not pooled. A pooled average hides
the laptop-microphone-plus-generator case, which is the one that will decide
whether this is usable.

## Comparing engines

Claw ships one engine but the interface takes others (`claw/speech/base.py`).
Compare at least two before concluding anything:

1. **sherpa-onnx + Whisper base** — what Claw ships by default.
2. **sherpa-onnx + Whisper small** — the accuracy option in the catalogue.
3. **sherpa-onnx + streaming zipformer** — the Live model. Expect it to be the
   weakest on names: it is an English-only transducer and it decides words before
   hearing the end of the sentence. Measure it anyway, because live feedback may
   be worth a few points of WER when the user can see and fix the text as they
   speak. Record **both** its partial text and its final text — a model whose
   partials thrash about is unpleasant to use even when the final answer is right.
4. Optionally whisper.cpp with the same weights, to separate the runtime from
   the model.

Run every engine over the identical files. Record model version, quantisation,
CPU, RAM, and seconds taken per utterance alongside each score — a model that is
two points better and four times slower is not better for a command bar.

## Writing up

Put results in `docs/TEST_RESULTS.md` with: date, Claw version, model id and
quantisation, machine, microphone, number of speakers and utterances, and the
four measures per condition. State the sample size next to every percentage.

If an accuracy number appears anywhere in this repository without a recording
set behind it, it is wrong and should be deleted.

## If accuracy turns out to be poor

Options, cheapest first:

1. Offer **Whisper small** as the default on machines with enough memory.
2. Add an initial-prompt / hotword bias listing Nigerian place names, common
   personal names, "TechDesk" and "Claw" — sherpa-onnx supports context biasing,
   and it is the cheapest fix for the name errors that will dominate.
3. Add a correction step: the user edits the text in the bar before submitting,
   which the design already requires — measure how often they have to.
4. Only then consider fine-tuning on Nigerian English, which needs a licensed
   dataset and is a project of its own.
