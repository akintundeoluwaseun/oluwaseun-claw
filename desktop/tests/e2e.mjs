// End-to-end smoke test: launches the real Electron app, which starts the real
// Python backend. The model server is the labelled TEST DOUBLE from
// backend/tests/run_fake_server.py (no real model weights in CI).
//
// Usage:  node tests/e2e.mjs [screenshotDir]
// Linux CI needs a display (xvfb-run) and, when run as root, CLAW_E2E_NO_SANDBOX=1.

import { _electron as electron } from 'playwright-core';
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const desktopDir = path.resolve(here, '..');
const backendDir = path.resolve(desktopDir, '..', 'backend');
const shotDir = process.argv[2] || fs.mkdtempSync(path.join(os.tmpdir(), 'claw-shots-'));
const isWin = process.platform === 'win32';
const python = process.env.CLAW_PYTHON || path.join(backendDir, '.venv', isWin ? 'Scripts/python.exe' : 'bin/python');

function check(cond, msg) {
  if (!cond) throw new Error('FAILED: ' + msg);
  console.log('ok -', msg);
}

const fake = spawn(python, ['-m', 'tests.run_fake_server'], { cwd: backendDir, stdio: ['ignore', 'pipe', 'inherit'] });
const port = await new Promise((resolve, reject) => {
  fake.stdout.once('data', (d) => resolve(Number(String(d).trim())));
  fake.once('exit', (c) => reject(new Error('fake server exited ' + c)));
});

const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'claw-e2e-'));
fs.writeFileSync(
  path.join(dataDir, 'settings.json'),
  JSON.stringify({ model: { provider: 'ollama', base_url: `http://127.0.0.1:${port}`, model: 'qwen2.5:7b' } }),
);

const args = [desktopDir];
if (process.env.CLAW_E2E_NO_SANDBOX) args.unshift('--no-sandbox');
const app = await electron.launch({ args, env: { ...process.env, CLAW_DATA_DIR: dataDir } });
let exitCode = 0;
try {
  const win = await app.firstWindow();
  await win.setViewportSize({ width: 1240, height: 820 });
  await win.waitForSelector('#backend-pill[data-state="ready"]', { timeout: 30000 });
  check(true, 'backend started from the desktop app and reported ready');
  await win.waitForSelector('#model-pill[data-state="ready"]', { timeout: 10000 });
  check((await win.textContent('#model-pill')).includes('qwen2.5:7b'), 'model status shows configured model');

  const tokenVisible = await win.evaluate(() => Object.keys(window.claw).join(','));
  check(!/token/i.test(tokenVisible), 'renderer bridge exposes no token: ' + tokenVisible);
  const blocked = await win.evaluate(() => window.claw.api('DELETE', '/settings'));
  check(blocked.status === 400, 'disallowed route refused by main process');

  await win.screenshot({ path: path.join(shotDir, '1-empty.png') });
  await win.fill('#task-input', 'Find the latest PDF in my Downloads folder and summarize it');
  await win.click('#plan-btn');
  await win.waitForSelector('#results:not([hidden]) .plan-step', { timeout: 20000 });
  const steps = await win.$$eval('.plan-step', (n) => n.length);
  check(steps === 3, `plan rendered with ${steps} steps`);
  check((await win.textContent('#plan-status')) === 'Plan ready', 'status tag says Plan ready');
  check((await win.textContent('.plan-step .tag-ok')).includes('without asking'), 'read-only step shows allowed permission');
  const history = await win.$$eval('#history-list li', (n) => n.length);
  check(history === 1, 'task saved to history');
  await win.screenshot({ path: path.join(shotDir, '2-plan.png') });

  await win.click('#open-settings');
  await win.waitForSelector('#settings:not([hidden])');
  await win.click('#s-test');
  await win.waitForFunction(() => document.querySelector('#s-test-result').dataset.tone === 'ok');
  check(true, 'settings test connection reports ready');
  await win.fill('#s-base-url', 'http://203.0.113.9:11434');
  await win.click('#save-settings');
  await win.waitForSelector('#settings-error:not([hidden])');
  check((await win.textContent('#settings-error')).includes('not on this computer'), 'remote server refused with readable message');
  await win.screenshot({ path: path.join(shotDir, '3-settings-error.png') });
  await win.click('#cancel-settings');

  // Model server goes away: the app must report it, not invent a plan.
  fake.kill();
  await new Promise((r) => setTimeout(r, 500));
  await win.fill('#task-input', 'Open my browser and search for motion graphics templates');
  await win.click('#plan-btn');
  await win.waitForSelector('#error-banner:not([hidden])', { timeout: 20000 });
  check((await win.textContent('#error-title')).includes('Could not connect'), 'model outage shown as an error');
  await win.waitForFunction(() => document.querySelectorAll('#history-list li').length === 2);
  check(true, 'failed task recorded in history');
  await win.screenshot({ path: path.join(shotDir, '4-model-down.png') });
  console.log('screenshots in', shotDir);
} catch (err) {
  console.error(err);
  exitCode = 1;
} finally {
  await app.close();
  fake.kill();
}
process.exit(exitCode);
