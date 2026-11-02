S-CLAW - licences of the video libraries inside this installer
==============================================================

S-CLAW's own code is under the MIT licence (see LICENSE). This installer also contains
FFmpeg libraries and video encoders, delivered inside PyAV 19.0.2 (BSD-3-Clause):

- FFmpeg 9.0.2 libraries (libavcodec, libavformat, libavutil, ...): built with
  --enable-version3 and linked with GPL encoders, so treat this FFmpeg build as covered
  by the GNU GPL version 3 or later (FFmpeg-COPYING.GPLv3.txt); FFmpeg's own code is
  LGPL-3.0-or-later (FFmpeg-COPYING.LGPLv3.txt).
- x264 (commit b35605ace3ddf7c1a5d67a2eb553f034aef41d55): GNU GPL version 2 or later
  (x264-COPYING.txt). Used for H.264 video.
- x265 4.3: GNU GPL version 2 or later (GPL-2.0.txt). Present in the library bundle;
  S-CLAW does not use it.
- Also bundled by PyAV, under permissive or LGPL terms: libvpx, libopus, dav1d, SVT-AV1,
  libwebp, vmaf, lame (bwlame), GnuTLS, nettle, GMP, libunistring.

Source code
-----------
The complete corresponding source for these GPL/LGPL components is published with every
S-CLAW release on GitHub, as "S-CLAW-third-party-sources.zip" next to the installer:
https://github.com/akintundeoluwaseun/oluwaseun-claw/releases

It contains the exact source archives used to build PyAV 19.0.2's FFmpeg
(build recipe: https://github.com/PyAV-Org/pyav-ffmpeg, tag 9.0.2-1):
  ffmpeg-9.0.2.tar.xz
  x264-b35605ace3ddf7c1a5d67a2eb553f034aef41d55.tar.bz2
  x265_4.3.tar.gz
  pyav-ffmpeg-9.0.2-1 (the build scripts and patches)
  PyAV-19.0.2

If you cannot get it there, open an issue at
https://github.com/akintundeoluwaseun/oluwaseun-claw/issues and it will be sent to you,
for at least three years after the last release that contained this version.

S-CLAW is not affiliated with these projects. These programs come with NO WARRANTY,
to the extent permitted by law; see the licence texts in this folder.
