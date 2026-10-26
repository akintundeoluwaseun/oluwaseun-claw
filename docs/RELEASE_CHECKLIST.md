# Release checklist

Tick every line before publishing an installer. ✅ = already done in the build workspace (Linux).

## A. Code and tests
- [x] ✅ `scripts/check.sh` passes: 151 backend, 5 desktop unit, 52 end-to-end (2026-10-26)
- [x] ✅ Static security scan clean (no 0.0.0.0 binds, no shell=True/eval, no innerHTML, TLS checks on)
- [x] ✅ `pip-audit -r requirements.txt` and `npm audit`: no known vulnerabilities (2026-10-26)
- [ ] `scripts\check.ps1` passes on Windows 10
- [ ] Version numbers match: `backend/claw/__init__.py`, `desktop/package.json`, CHANGELOG

## B. Windows, development copy
- [ ] `scripts\setup.ps1` completes (llama.cpp downloaded and checksum-verified, Tesseract installed)
- [ ] App starts; Standard brain downloads in Settings (size shown, cancel/resume work)
- [ ] Real brain: Plan only and three sample tasks from `docs/DESKTOP.md` and the user guide
- [ ] Memory and speed noted on an 8 GB laptop (Standard) and a 16 GB laptop (Pro)
- [ ] Scanned PDF read, searched, summarised; searchable copy opens in Edge with selectable text
- [ ] Force-close the backend in Task Manager → `llama-server.exe` also disappears (job object)
- [ ] `docs/DESKTOP.md` checklist (UI Automation) completed

## C. Build (not done yet — by request)
- [ ] `scripts\build-release.ps1 -Edition Standard` and `-Edition Pro` finish
- [ ] Bundled brain was checksum-verified and its licence is Apache-2.0/MIT (the script refuses otherwise)
- [ ] `resources\tesseract\tessdata` has `eng`, `osd`, `configs\`, `pdf.ttf`
- [ ] Licence files of the llama.cpp and Tesseract Windows builds are in `resources\engine` and `resources\tesseract`; list their DLLs in THIRD_PARTY_NOTICES
- [ ] `SHA256SUMS.txt` written
- [ ] Code signing (if a certificate is available)

## D. Clean-machine install (Windows 10 with no Python, Node.js, Ollama or Tesseract)
- [ ] Install without administrator rights; app opens; brain ready without any download
- [ ] `desktop/tests/packaged-smoke.mjs` checks repeated by hand: OCR works, engine on 127.0.0.1 only
- [ ] Works with the network unplugged (except web tasks)
- [ ] Upgrade over the previous version keeps settings, history and downloaded brains
- [ ] Uninstall removes the app and keeps `%APPDATA%\OluwaseunClaw`
- [ ] Windows Defender doesn't flag the installer or the app; SmartScreen behaviour noted

## E. Paperwork
- [x] ✅ THIRD_PARTY_NOTICES.md updated with versions and licences
- [x] ✅ User guide, developer guide, known issues written
- [ ] CHANGELOG entry for the release; PROJECT_STATUS and TEST_RESULTS updated with the Windows results
- [ ] Release notes say clearly what was and wasn't tested
