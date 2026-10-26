// End-to-end test: launches the real Electron app, which starts the real
// Python backend, which drives a real Chromium against a local test website.
// Model replies come from the labelled TEST DOUBLE in
// backend/tests/run_e2e_servers.py (no real model weights in CI).
//
// Usage:  node tests/e2e.mjs [screenshotDir]
// Linux CI needs a display (xvfb-run) and, when run as root, CLAW_E2E_NO_SANDBOX=1.
// If Playwright's own Chromium is not installed, set CLAW_BROWSER_EXECUTABLE.

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

const servers = spawn(python, ['-m', 'tests.run_e2e_servers'], { cwd: backendDir, stdio: ['ignore', 'pipe', 'inherit'] });
const { model_port: modelPort, site_url: siteUrl } = await new Promise((resolve, reject) => {
  servers.stdout.once('data', (d) => resolve(JSON.parse(String(d).trim())));
  servers.once('exit', (c) => reject(new Error('test servers exited ' + c)));
});

const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'claw-e2e-'));
const saveDir = fs.mkdtempSync(path.join(os.tmpdir(), 'claw-saved-'));
fs.writeFileSync(
  path.join(dataDir, 'settings.json'),
  JSON.stringify({
    // Developer mode pointed at the stand-in model server (the built-in brain needs real weights).
    model: { mode: 'custom', provider: 'ollama', base_url: `http://127.0.0.1:${modelPort}`, model: 'qwen2.5:7b' },
    permissions: { authorized_folders: [saveDir] },
    browser: { channel: 'chromium', headless: true, search_engine: 'custom', custom_search_url: `${siteUrl}/search?q={query}` },
  }),
);

const args = [desktopDir];
if (process.env.CLAW_E2E_NO_SANDBOX) args.unshift('--no-sandbox');
const app = await electron.launch({ args, env: { ...process.env, CLAW_DATA_DIR: dataDir, CLAW_E2E: '1' } });
let exitCode = 0;

async function windowByFile(name) {
  for (let i = 0; i < 100; i++) {
    const w = app.windows().find((x) => x.url().endsWith(name));
    if (w) return w;
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error('window not found: ' + name);
}

try {
  const win = await windowByFile('index.html');
  const bar = await windowByFile('quickbar.html');
  await win.setViewportSize({ width: 1240, height: 860 });
  await win.waitForSelector('#backend-pill[data-state="ready"]', { timeout: 30000 });
  check(true, 'backend started from the desktop app and reported ready');
  await win.waitForSelector('#home:not([hidden])', { timeout: 10000 });
  check(true, 'first launch opens straight to the task box (no key or setup questions)');
  await win.waitForSelector('#model-pill[data-state="ready"]', { timeout: 10000 });
  check((await win.textContent('#model-pill')).includes('qwen2.5:7b'), 'brain status shows ready');

  const bridge = await win.evaluate(() => Object.keys(window.claw).join(','));
  check(!/token/i.test(bridge), 'renderer bridge exposes no token: ' + bridge);
  const blocked = await win.evaluate(() => window.claw.api('DELETE', '/settings'));
  check(blocked.status === 400, 'disallowed route refused by main process');

  // 1. Plan only
  await win.fill('#task-input', 'Find the latest PDF in my Downloads folder and summarize it');
  await win.click('#plan-btn');
  await win.waitForSelector('#results[open] .plan-step', { timeout: 20000 });
  check((await win.$$eval('.plan-step', (n) => n.length)) === 3, 'plan-only shows 3 proposed steps');
  check((await win.textContent('#run-status')) === 'Plan ready', 'plan-only status says Plan ready');
  await win.screenshot({ path: path.join(shotDir, '0-plan.png') });
  await win.click('#new-task');
  check(await win.isVisible('#home'), 'New task returns to the task box');
  await win.screenshot({ path: path.join(shotDir, '0-home.png') });

  // 2. Run: search, open result, save links (needs approval), finish
  await win.fill('#task-input', 'Search for free motion graphics templates and save the useful links');
  await win.click('#run-btn');
  await win.waitForSelector('#approval-card:not([hidden])', { timeout: 30000 });
  check((await win.textContent('#approval-title')).includes('save links to a file'), 'approval requested before saving a file');
  await bar.waitForFunction(() => document.body.dataset.phase === 'attention', null, { timeout: 10000 });
  check(true, 'quick bar shows that Claw needs you');
  await bar.screenshot({ path: path.join(shotDir, 'qb-attention.png') });
  check((await win.textContent('#run-status')) === 'Waiting for you', 'status shows waiting for approval');
  await win.screenshot({ path: path.join(shotDir, '1-approval.png') });
  await win.click('#approve-btn');
  await win.waitForFunction(() => document.querySelector('#run-status').textContent === 'Finished', null, { timeout: 30000 });
  const tags = await win.$$eval('#activity .tl-item:not([data-kind="note"]) .tl-tag', (n) => n.map((x) => x.textContent));
  check(tags.length === 3 && tags.every((t) => t === 'Done'), `3 steps done and checked (${tags.join(', ')})`);
  check((await win.textContent('#summary-counts')).includes('3 done and checked'), 'outcome counts come from recorded steps');
  const saved = fs.readFileSync(path.join(saveDir, 'motion templates.md'), 'utf8');
  check(saved.includes(`${siteUrl}/articles/motion-templates`), 'links file really written to the authorized folder');
  await win.screenshot({ path: path.join(shotDir, '2-finished.png') });

  // 3. Run that needs approval to click a form button; stop it instead
  await win.click('#new-task');
  await win.fill('#task-input', 'Open the contact page and send the form');
  await win.click('#run-btn');
  await win.waitForSelector('#approval-card:not([hidden])', { timeout: 30000 });
  check((await win.textContent('#approval-title')).includes('click a button'), 'clicking a form button asks first');
  await win.click('#stop-btn');
  await win.waitForFunction(() => document.querySelector('#run-status').textContent === 'Stopped by you', null, { timeout: 20000 });
  const submissions = await (await fetch(`${siteUrl}/__submissions`)).text();
  check(submissions === '0', 'stopped task never submitted the form');
  check(await win.isHidden('#approval-card'), 'approval card cleared after stop');
  await win.screenshot({ path: path.join(shotDir, '3-stopped.png') });
  check((await win.$$eval('#history-list .history-item', (n) => n.length)) === 3, 'all three tasks in history');

  // 3b. Quick bar: expand, type a task, it starts and opens in the main window
  await bar.waitForFunction(() => document.body.dataset.phase === 'idle', null, { timeout: 10000 });
  await bar.screenshot({ path: path.join(shotDir, 'qb-idle.png') });
  await bar.click('#pill');
  await bar.waitForFunction(() => document.body.dataset.mode === 'expanded');
  check(true, 'quick bar opens into a task box');
  await bar.fill('#task', 'Check whether anything needs doing');
  await bar.screenshot({ path: path.join(shotDir, 'qb-expanded.png') });
  await bar.press('#task', 'Enter');
  await win.waitForFunction(() => document.querySelector('#run-title').textContent === 'Check whether anything needs doing', null, { timeout: 15000 });
  check(true, 'task from the quick bar opens in the main window');
  await win.waitForFunction(() => document.querySelector('#run-status').textContent === 'Finished', null, { timeout: 20000 });
  check((await win.textContent('#summary-counts')) === 'No steps were carried out', 'outcome is honest when nothing was done');

  // 3c. Desktop step where desktop control is unavailable: reported, not faked
  await win.click('#new-task');
  await win.fill('#task-input', 'Tell me which windows are open');
  await win.click('#run-btn');
  await win.waitForFunction(() => document.querySelector('#run-status').textContent === 'Finished', null, { timeout: 20000 });
  const deskDetail = await win.textContent('#activity .tl-item[data-tone="bad"] .tl-detail');
  check(/Windows only|locked|not available/.test(deskDetail), `desktop step failure explained: "${deskDetail}"`);
  check((await win.textContent('#summary-counts')).includes('1 failed'), 'failed desktop step counted as failed');

  // 4. Settings validation
  await win.click('#open-settings');
  await win.waitForSelector('#settings:not([hidden])');
  check((await win.textContent('#brain-summary')).includes('developer model server'), 'settings describe the brain in plain words');
  await win.click('.dev > summary');
  await win.click('#s-test');
  await win.waitForFunction(() => document.querySelector('#s-test-result').dataset.tone === 'ok');
  check(true, 'developer custom server test connection works');
  await win.check('#s-custom');
  await win.fill('#s-base-url', 'http://203.0.113.9:11434');
  await win.click('#save-settings');
  await win.waitForSelector('#settings-error:not([hidden])');
  check((await win.textContent('#settings-error')).includes('not on this computer'), 'remote server refused with readable message');
  await win.screenshot({ path: path.join(shotDir, '4-settings.png') });
  await win.check('#d-quickbar').catch(() => {});
  await win.click('#cancel-settings');

  // 5. Model server goes away: report it, do not invent a result
  servers.kill();
  await new Promise((r) => setTimeout(r, 500));
  await win.click('#new-task');
  await win.fill('#task-input', 'Open my browser and search for motion graphics templates');
  await win.click('#run-btn');
  await win.waitForFunction(() => document.querySelector('#run-status').textContent === 'Failed', null, { timeout: 20000 });
  check((await win.textContent('#summary-error')).includes('Could not connect'), 'brain outage shown as a failure');
  await win.waitForSelector('#model-pill[data-state="failed"]', { timeout: 10000 });
  check(true, 'model chip updates to offline after the failure');
  await win.screenshot({ path: path.join(shotDir, '5-model-down.png') });
  // Dark theme screenshots for visual review (Windows dark mode)
  await win.emulateMedia({ colorScheme: 'dark' });
  await bar.emulateMedia({ colorScheme: 'dark' });
  await win.click('#history-list .history-item:nth-of-type(1)').catch(() => {});
  await win.screenshot({ path: path.join(shotDir, '6-dark.png') });
  await bar.screenshot({ path: path.join(shotDir, 'qb-dark.png') });
  console.log('screenshots in', shotDir);
} catch (err) {
  console.error(err);
  await (await windowByFile('index.html')).screenshot({ path: path.join(shotDir, 'failure.png') }).catch(() => {});
  exitCode = 1;
} finally {
  await app.close();
  servers.kill();
}
process.exit(exitCode);
