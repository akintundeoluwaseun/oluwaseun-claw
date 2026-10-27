# S-CLAW — the mark

**Product:** S-CLAW, an all-in-one AI agent for Windows 10/11.
**Creator:** Oluwaseun.
**The promise the mark has to carry:** the agent completes the task, it does not
merely discuss it. So the mark is decisive and made of metal, not a mascot.

## The mark

Three claw blades in rotation. Each blade is two surfaces — a lit facet and a
body — so it reads as folded metal rather than a flat triangle, and the three
together turn around a common centre. Rotational symmetry is what lets it stay
legible when Windows draws it at 16 px in the tray.

It was chosen over seven other directions, each drawn and judged at the sizes
the app actually uses (tray 16, title bar 22, taskbar 32, about 64, installer
128), not at poster size:

| Rejected | Why |
|---|---|
| A letter S, plain or clawed | Legible, but any company could use it. |
| A four-point spark | Clean at every size — and the sparkle every AI product already uses. |
| A twisted ribbon loop | Becomes a bean below 64 px. |
| Three flat slashes | Reads instantly, but closer to a generic claw than to this product. |

## Files

`desktop/src/assets/brand/`

| File | Use |
|---|---|
| `s-claw-mark.svg` | **Primary.** The full mark, with facets and bloom. 32 px and up. |
| `s-claw-mark-small.svg` | One surface per blade, no bloom. **16–32 px**, where the facets turn to mud. |
| `s-claw-mark-mono.svg` | Flat, one colour, takes `currentColor`. Tray icons, stencils, print. |
| `s-claw-lockup.svg` / `-dark.svg` | Mark plus wordmark, light and dark. |

Windows icons are **generated from these files**, never redrawn:

```
backend/.venv/bin/python scripts/assets/make_icons.py
```

It renders the SVGs with the Chromium already present for the browser tools and
writes `icon.ico` (16, 24, 32, 48, 64, 128, 256), `icon.png`, and the three tray
states. Re-run it after changing any brand file, or the taskbar and the brand
drift apart.

**Before the lockup leaves the app** — a website, a print file, a store listing
— convert its text to outlines. It is set in a serif *stack*, which is right
inside the app, where the app controls its fonts, and wrong anywhere else.

## Colour

| | Hex | Where |
|---|---|---|
| Tile | `#0E0F12` | the squircle behind the mark |
| Highlight | `#FFFFFF` → `#BFD2FF` | the lit facet of each blade |
| Body | `#9DB4FF` → `#AE93FF` → `#36479B` | the blade itself |
| Bloom | `#7E9BFF` at 42% | the glow, which is light and not a shadow |

The interface keeps its ink-and-brass palette; the mark is the one place the
cool blue appears, which is what makes it read as the badge of the product
rather than as another interface element.

## Type and naming

The wordmark is **S-CLAW**: capitals, letter-spaced, serif, with the hyphen in
blue. Never "S-Claw", never "sclaw".

In ordinary sentences inside the app — "Claw works through it step by step" —
**"Claw" on its own is correct and preferred**, the way people say "Word" for
Microsoft Word. The full name belongs on the title bar, the installer, the
documentation and anywhere the product is being named rather than talked about.

## Motion

The mark is the app's status indicator, so it has four states and is only ever
in one of them. All of it is transform and opacity, so it stays on the
compositor and costs no layout.

| State | What it does | When |
|---|---|---|
| idle | still, after a short settle on first paint | nothing is happening |
| listening | the bloom follows the voice; a ring leaves the mark on each phrase | the microphone is open |
| working | the blades turn, slowly and evenly | a task is running |
| needs you | a slower, warmer pulse | an approval is waiting |

**The listening state is driven by the microphone itself.** The quick bar already
has the raw samples in hand for transcription, so it takes their RMS, smooths it
— fast on the way up, slow on the way down, or the mark flickers on every
consonant — and writes it to a `--level` CSS variable. The bloom scales and
brightens with it. It is the person's own voice moving the mark, not a loop
pretending to listen.

`prefers-reduced-motion: reduce` stops every animation. The states remain
distinguishable by brightness alone.

## Rules

- **Minimum 16 px**, and below 32 px use the simplified mark.
- **Clear space** of half the tile's width on every side.
- Do not recolour the blades, add a drop shadow, or put the mark on a mid-tone
  background — the bloom is light and needs darkness to be light against.
- Do not animate it outside the four states above. A logo that never stops
  moving is one people stop seeing.
- Do not rebuild it by hand. Edit the SVG and re-run the icon script.
