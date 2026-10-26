'use strict';
// electron-builder settings for Oluwaseun Claw.
//
// The build script (scripts/build-release.ps1) first fills a staging folder:
//   <stage>/backend    frozen Python backend (PyInstaller), so users need no Python
//   <stage>/engine     llama.cpp llama-server + its DLLs (MIT)
//   <stage>/tesseract  Tesseract OCR + tessdata (eng, osd) (Apache-2.0)
//   <stage>/models     the edition's brain: models/<id>/manifest.json + GGUF files
// and then runs electron-builder with CLAW_STAGE and CLAW_EDITION set.
// electron-builder only makes the unpacked app ("dir"); the installer is made by
// Inno Setup (packaging/claw.iss), because NSIS installers cannot exceed 2 GB and the
// brains are 3–7 GB.

const path = require('node:path');

const stage = process.env.CLAW_STAGE || path.resolve(__dirname, '..', 'build', 'stage');
const edition = process.env.CLAW_EDITION || 'Standard';

const extra = ['backend', 'engine', 'tesseract', 'models'].map((dir) => ({
  from: path.join(stage, dir),
  to: dir,
  filter: ['**/*'],
}));

module.exports = {
  appId: 'com.oluwaseun.claw',
  productName: 'Oluwaseun Claw',
  copyright: 'Copyright © 2026 Oluwaseun Claw contributors',
  directories: { output: path.resolve(__dirname, '..', 'build', `app-${edition.toLowerCase()}`) },
  files: ['src/**/*', 'package.json', '!**/*.map'],
  asar: true,
  // Offline build machines can point at an already-downloaded Electron (e.g. node_modules/electron/dist).
  ...(process.env.CLAW_ELECTRON_DIST ? { electronDist: process.env.CLAW_ELECTRON_DIST } : {}),
  extraResources: extra,
  extraMetadata: { claw: { edition } },
  win: {
    target: [{ target: 'dir', arch: ['x64'] }],
    icon: 'src/assets/icon.ico',
  },
  linux: {
    // Only used to check the packaging layout on Linux build machines; Claw ships for Windows.
    target: [{ target: 'dir', arch: ['x64'] }],
    icon: 'src/assets/icon.png',
    category: 'Utility',
  },
};
