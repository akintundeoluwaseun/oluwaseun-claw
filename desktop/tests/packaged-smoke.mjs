// Smoke test of the PACKAGED app (electron-builder "dir" output): frozen backend, bundled
// llama.cpp engine, bundled Tesseract and a bundled brain. Runs with PATH emptied so nothing
// installed on the machine (Python, Tesseract, Ollama) can be used by accident.
// Usage (Linux build machine): xvfb-run -a node tests/packaged-smoke.mjs <app executable> [shotDir]
// The packaged brain may be a TEST model; this checks wiring, not answer quality.
import { _electron as electron } from 'playwright-core';
import fs from 'node:fs'; import os from 'node:os'; import path from 'node:path'; import { execSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
const exe = process.argv[2], shots = process.argv[3] || fs.mkdtempSync(path.join(os.tmpdir(), 'claw-pkg-shots-'));
const backendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'backend');
const scan = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'claw-pkg-doc-')), 'scan1.pdf');
execSync(`"${path.join(backendDir, '.venv/bin/python')}" -c "import sys; from pathlib import Path; from tests.pdf_fixtures import page_image, scanned_pdf; scanned_pdf(Path(sys.argv[1]), [page_image(['RECEIPT 77', 'Paid in full'])])" "${scan}"`, { cwd: backendDir });
const data = fs.mkdtempSync(path.join(os.tmpdir(), 'claw-pkg-'));
const ok = (c, m) => { if (!c) throw new Error('FAILED: ' + m); console.log('ok -', m); };
const app = await electron.launch({ executablePath: exe, args: ['--no-sandbox'], env: { DISPLAY: process.env.DISPLAY, XAUTHORITY: process.env.XAUTHORITY || '', HOME: process.env.HOME, PATH: '/nonexistent', CLAW_DATA_DIR: data, CLAW_E2E: '1',
  CLAW_E2E_OPEN_DOC: scan, CLAW_E2E_SAVE_PDF: path.join(data, 'out.pdf') } });
let code = 0;
try {
  let win; for (let i = 0; i < 100 && !win; i++) { win = app.windows().find((w) => w.url().endsWith('index.html')); if (!win) await new Promise((r) => setTimeout(r, 100)); }
  await win.setViewportSize({ width: 1240, height: 860 });
  await win.waitForSelector('#backend-pill[data-state="ready"]', { timeout: 40000 });
  ok(true, 'packaged app started its frozen backend (no Python installed needed)');
  const ps = execSync('ps -eo args=').toString();
  ok(ps.includes('resources/backend/claw-backend --port'), 'backend runs from resources/backend');
  await win.waitForSelector('#model-pill[data-state="ready"]', { timeout: 20000 });
  ok(true, 'bundled brain recognised: model chip says ready with no download');
  await win.click('#open-settings');
  await win.waitForSelector('#brain-list .brain');
  const meta = await win.textContent('#brain-list .brain-meta');
  ok(/Came with Claw/.test(meta), `brain shown as bundled: "${meta}"`);
  await win.click('#brain-restart');
  await win.waitForFunction(() => /Running/.test(document.querySelector('#engine-line').textContent), null, { timeout: 60000 });
  ok(true, 'bundled llama-server started from resources/engine');
  const eng = execSync('ps -eo args=').toString().split('\n').find((l) => l.includes('llama-server'));
  ok(eng && eng.includes('resources/engine/llama-server') && eng.includes('--host 127.0.0.1'), 'engine bound to 127.0.0.1 only');
  await win.screenshot({ path: path.join(shots, 'pkg-brain.png') });
  await win.click('#close-settings');
  await win.click('#open-docs');
  await win.click('#doc-open');
  await win.waitForSelector('#doc-status[data-tone="ok"], #doc-status[data-tone="bad"]', { timeout: 60000 });
  const badge = await win.textContent('.page-badge');
  ok(/Read from the scan/.test(badge) && /RECEIPT 77/.test(await win.textContent('.page-text')), `bundled Tesseract read the scan with no OCR on PATH: "${badge}"`);
  await win.click('#doc-save');
  await win.waitForFunction(() => /Saved:/.test(document.querySelector('#doc-ask-note').textContent), null, { timeout: 60000 });
  ok(fs.existsSync(path.join(data, 'out.pdf')), 'searchable PDF made with the bundled OCR (needs configs + pdf.ttf)');
} catch (e) { console.error(e); code = 1; }
await app.close();
let left = [];
for (let i = 0; i < 50; i++) {
  left = execSync('ps -eo stat=,args=').toString().split('\n').filter((l) => (l.includes('llama-server') || l.includes('claw-backend --port')) && !l.trim().startsWith('Z'));
  if (!left.length) break;
  await new Promise((r) => setTimeout(r, 200));
}
console.log(left.length ? 'FAILED: engine/backend left running 10 s after quit' : 'ok - backend and engine both stopped after quitting');
process.exit(code || (left.length ? 1 : 0));
