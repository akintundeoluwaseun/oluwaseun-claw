'use strict';
// electron-builder settings for S-CLAW.
//
// The build script (scripts/build-release.ps1) first fills a staging folder:
//   <stage>/backend    frozen Python backend (PyInstaller), so users need no Python
//   <stage>/engine     llama.cpp llama-server + its DLLs (MIT)
//   <stage>/tesseract  Tesseract OCR + tessdata (eng, osd) (Apache-2.0)
//   <stage>/models     the edition's brain: models/<id>/manifest.json + GGUF files (Local only)
//   <stage>/edition.json  which edition this build is (Online or Local)
// and then runs electron-builder with CLAW_STAGE and CLAW_EDITION set.
// electron-builder only makes the unpacked app ("dir"); the installer is made by
// Inno Setup (packaging/claw.iss), because NSIS installers cannot exceed 2 GB and the
// brains are 3–7 GB.

const path = require('node:path');
const { CREATOR } = require('./src/creator');

const stage = process.env.CLAW_STAGE || path.resolve(__dirname, '..', 'build', 'stage');
const edition = process.env.CLAW_EDITION || 'Standard';

const extra = ['backend', 'engine', 'tesseract', 'models'].map((dir) => ({
  from: path.join(stage, dir),
  to: dir,
  filter: ['**/*'],
}));
// Which edition this build is. claw/edition.py reads it from resources/edition.json and
// it is the only difference between Claw Online and Claw Local at run time.
extra.push({ from: path.join(stage, 'edition.json'), to: 'edition.json' });

module.exports = {
  appId: 'com.oluwaseun.sclaw',
  productName: 'S-CLAW',
  // Written into the .exe's version resource, where Windows shows it under
  // Properties > Details. Same string as the installer and the About panel.
  copyright: CREATOR.copyright,
  directories: { output: path.resolve(__dirname, '..', 'build', `app-${edition.toLowerCase()}`) },
  files: ['src/**/*', 'package.json', '!**/*.map'],
  asar: true,
  // Offline build machines can point at an already-downloaded Electron (e.g. node_modules/electron/dist).
  ...(process.env.CLAW_ELECTRON_DIST ? { electronDist: process.env.CLAW_ELECTRON_DIST } : {}),
  extraResources: extra,
  extraMetadata: { claw: { edition } },
  // Nothing is published by electron-builder itself; without this it tries to guess a
  // publish target from the repository and crashes ("reading 'channel'") on Linux and Mac.
  publish: null,
  win: {
    target: [{ target: 'dir', arch: ['x64'] }],
    icon: 'src/assets/icon.ico',
  },
  // Linux and macOS: scripts/build-release.sh sets CLAW_UNIX_TARGET (AppImage / dmg).
  linux: {
    target: [{ target: process.env.CLAW_UNIX_TARGET || 'dir', arch: ['x64'] }],
    icon: 'src/assets/icon.png',
    category: 'Utility',
    artifactName: 'S-CLAW-${version}-linux-x64.${ext}',
  },
  mac: {
    target: [{ target: process.env.CLAW_UNIX_TARGET || 'dir', arch: ['arm64'] }],
    icon: 'src/assets/icon-512.png',  // macOS needs at least 512x512
    category: 'public.app-category.productivity',
    artifactName: 'S-CLAW-${version}-mac-arm64.${ext}',
    // Not signed: macOS will ask the person to open it with right-click > Open the first time.
    identity: null,
  },
};
