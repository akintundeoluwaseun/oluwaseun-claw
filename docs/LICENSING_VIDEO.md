# Video encoders in the installer: what the licences require (reuse plan step 6, 2 Nov 2026)

These are facts from inspecting the PyAV 19.0.2 wheel that the build uses, plus the options. It is
not legal advice. The decision belongs to the owner.

## What is shipped

- FFmpeg's libraries report "LGPL version 3 or later". The build was configured with `--enable-version3`, `--enable-libx264` and `--enable-libx265`.
- The wheel carries separate shared libraries, among them `libx264` and `libx265`. Both are **GPL-2.0-or-later**.
  - libavcodec links to them, so they cannot simply be left out of the installer: FFmpeg would then fail to load.
- S-CLAW's own code is MIT, which is compatible with the GPL. Distributing the whole installer is therefore possible, but it brings the GPL's conditions for those parts.

## Options

1. **Comply as is (recommended: the least work, and nothing breaks).**
   - Ship the GPL-2.0 text and the x264/x265 copyright notices with the installer.
   - Offer their source: a link to the exact x264/x265 versions and to PyAV's FFmpeg build scripts, or a written offer.
   - State in THIRD_PARTY_NOTICES that the installer as a whole is distributed under terms compatible with the GPL for those parts.
   - S-CLAW stays MIT.
2. **Build our own FFmpeg without GPL parts** (LGPL only). Encode video with OpenH264 (BSD; Cisco's binary carries the patent licence) or with VP9 (libvpx, BSD) in WebM/MP4.
   - It is clean, but it means a custom FFmpeg build, which is more CI work and more risk.
   - VP9 MP4s play in browsers and VLC but in fewer phone gallery apps.
3. **No video encoding in the installer.** Make videos only through After Effects when installed. This loses the tested built-in video maker (3.14 PASSED). Not recommended.

## Note on patents

H.264 and HEVC are patent-encumbered in some countries. S-CLAW never encodes HEVC, though libx265 is present in the bundle. Option 2 with OpenH264 is the usual way to avoid both concerns.

## Decision (2 Nov 2026): option 1

The owner chose option 1. What was done:
- `packaging/licenses/` holds the GPL-2.0, GPL-3.0 and LGPL-3.0 texts, x264's COPYING, and a README naming each component, its exact version and where its source is. The installer copies it into `resources/licenses`, together with THIRD_PARTY_NOTICES and S-CLAW's own MIT licence.
- Every release built by build-windows now also carries `S-CLAW-third-party-sources.zip`. It holds the exact sources behind PyAV 19.0.2's FFmpeg build (pyav-ffmpeg tag 9.0.2-1): ffmpeg-9.0.2, x264 at commit b35605a, x265 4.3, the build scripts and PyAV 19.0.2.
- The README also offers the source on request, through the repository's issues, for three years.

## Before the decision

THIRD_PARTY_NOTICES now states the licences accurately; the earlier note said "LGPL-2.1+ only", which was wrong. No code was changed.
