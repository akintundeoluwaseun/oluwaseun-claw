// Visual review: real app, test model (TEST DOUBLE from backend/tests/run_e2e_servers.py).
// Captures dark and light screens, the quick bar, and a frame sequence of the orb.
//   node tests/showcase.mjs outDir
import { _electron as electron } from 'playwright-core';
import { spawn } from 'node:child_process';
import fs from 'node:fs'; import os from 'node:os'; import path from 'node:path';
import { fileURLToPath } from 'node:url';
const here = path.dirname(fileURLToPath(import.meta.url));
const desktopDir = path.resolve(here, '..'); const backendDir = path.resolve(desktopDir, '..', 'backend');
const out = process.argv[2]; fs.mkdirSync(out, { recursive: true });
const python = path.join(backendDir, '.venv', 'bin/python');
const servers = spawn(python, ['-m', 'tests.run_e2e_servers'], { cwd: backendDir, stdio: ['ignore', 'pipe', 'inherit'] });
const { model_port: modelPort, site_url: siteUrl } = await new Promise((res) => servers.stdout.once('data', (d) => res(JSON.parse(String(d).trim()))));
const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'claw-show-')); const saveDir = fs.mkdtempSync(path.join(os.tmpdir(), 'Documents-'));
fs.writeFileSync(path.join(dataDir, 'settings.json'), JSON.stringify({
  model: { mode: 'custom', provider: 'openai_compatible', base_url: `http://127.0.0.1:${modelPort}`, model: 'qwen2.5:7b' },
  permissions: { authorized_folders: [saveDir] },
  browser: { channel: 'chromium', headless: true, search_engine: 'custom', custom_search_url: `${siteUrl}/search?q={query}` },
}));
const args = [desktopDir]; if (process.env.CLAW_E2E_NO_SANDBOX) args.unshift('--no-sandbox');
const app = await electron.launch({ args, env: { ...process.env, CLAW_DATA_DIR: dataDir, CLAW_E2E: '1' } });
const find = async (n) => { for (let i = 0; i < 100; i++) { const w = app.windows().find((x) => x.url().endsWith(n)); if (w) return w; await new Promise((r) => setTimeout(r, 100)); } };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
try {
  const win = await find('index.html'); const bar = await find('quickbar.html');
  await win.setViewportSize({ width: 1280, height: 820 });
  await win.waitForSelector('#backend-pill[data-state="ready"]', { timeout: 40000 });
  await win.waitForSelector('#model-pill[data-state="ready"]', { timeout: 15000 });
  await sleep(1500);
  await win.screenshot({ path: path.join(out, 'dark-home.png') });
  // orb frames
  const orb = await win.$('.home-mark');
  for (let i = 0; i < 24; i++) { await orb.screenshot({ path: path.join(out, `orb-${String(i).padStart(2, '0')}.png`) }); await sleep(110); }
  await bar.screenshot({ path: path.join(out, 'dark-bar.png') });
  await bar.click('#pill'); await sleep(400);
  await bar.screenshot({ path: path.join(out, 'dark-bar-open.png') });
  await bar.press('#task', 'Escape').catch(() => {});
  // the scripted model answers in a fixed order: a plan-only request comes first
  await win.fill('#task-input', 'Find the latest PDF in my Downloads folder and summarize it');
  await win.click('#plan-btn');
  await win.waitForSelector('#results[open] .plan-step', { timeout: 20000 });
  await win.click('#new-task'); await sleep(300);
  // a task, approved
  await win.fill('#task-input', 'Search for free motion graphics templates and save the useful links');
  await win.click('#run-btn');
  await win.waitForSelector('#approval-card:not([hidden])', { timeout: 30000 });
  await sleep(500);
  await win.screenshot({ path: path.join(out, 'dark-approval.png') });
  await win.click('#approve-btn');
  await win.waitForFunction(() => document.querySelector('#run-status').textContent === 'Finished', null, { timeout: 30000 });
  await sleep(600);
  await win.screenshot({ path: path.join(out, 'dark-finished.png') });
  // light
  await win.click('#toggle-theme'); await sleep(300);
  const t = await win.evaluate(() => document.documentElement.dataset.theme || 'system');
  if (t !== 'light') { await win.click('#toggle-theme'); await sleep(300); }
  await win.screenshot({ path: path.join(out, 'light-finished.png') });
  await win.click('#toggle-chats'); await sleep(400);
  await win.click('#new-task'); await sleep(500);
  await win.screenshot({ path: path.join(out, 'light-home.png') });
  await sleep(500);
  await bar.screenshot({ path: path.join(out, 'light-bar.png') });
  await bar.click('#pill'); await sleep(400);
  await bar.screenshot({ path: path.join(out, 'light-bar-open.png') });
  await win.click('#open-settings'); await sleep(800);
  await win.screenshot({ path: path.join(out, 'light-settings.png') });
} finally { await app.close(); servers.kill(); }
console.log('done', out);
