// Reproduces the reported Settings problems in the real app: fresh install, switch where Claw thinks,
// save, reopen; and records every console error and failed request from the window.
import { _electron as electron } from 'playwright-core';
import fs from 'node:fs'; import os from 'node:os'; import path from 'node:path';
import { fileURLToPath } from 'node:url';
const here = path.dirname(fileURLToPath(import.meta.url));
const shots = process.argv[2] || fs.mkdtempSync(path.join(os.tmpdir(), 'repro-'));
const data = fs.mkdtempSync(path.join(os.tmpdir(), 'claw-repro-'));
const args = [path.resolve(here, '..')]; if (process.env.CLAW_E2E_NO_SANDBOX) args.unshift('--no-sandbox');
const app = await electron.launch({ args, env: { ...process.env, CLAW_DATA_DIR: data, CLAW_E2E: '1' } });
const log = (...a) => console.log(...a);
let win; for (let i = 0; i < 100 && !win; i++) { win = app.windows().find((w) => w.url().endsWith('index.html')); if (!win) await new Promise((r) => setTimeout(r, 100)); }
win.on('console', (m) => { if (['error', 'warning'].includes(m.type())) log('CONSOLE', m.type(), m.text()); });
win.on('pageerror', (e) => log('PAGEERROR', e.message));
await win.setViewportSize({ width: 1280, height: 860 });
await win.waitForSelector('#backend-pill[data-state="ready"]', { timeout: 40000 });
await new Promise((r) => setTimeout(r, 2500));
log('model pill:', await win.textContent('#model-pill'), '| state', await win.getAttribute('#model-pill', 'data-state'));
log('ready card visible:', await win.isVisible('#ready-card'), await win.textContent('#ready-title').catch(() => ''));
await win.screenshot({ path: path.join(shots, '1-fresh.png') });
const settingsMode = async () => (await win.evaluate(() => window.claw.api('GET', '/settings'))).body.settings.model.mode;
log('saved mode at start:', await settingsMode());
await win.click('#open-settings'); await win.waitForSelector('#settings:not([hidden])');
log('form shows:', await win.inputValue('#s-think'), '| options:', await win.$$eval('#s-think option', (o) => o.filter((x) => !x.hidden && !x.disabled).map((x) => x.value).join(',')));
await win.screenshot({ path: path.join(shots, '2-settings.png') });
// choose online model, fill, save
await win.selectOption('#s-think', 'cloud');
await win.fill('#s-cloud-url', 'https://api.example.com/v1'); await win.fill('#s-cloud-model', 'hosted-model'); await win.fill('#s-cloud-key', 'sk-test-1234567890');
await win.click('#save-settings'); await new Promise((r) => setTimeout(r, 1500));
log('after saving cloud: saved mode', await settingsMode(), '| sheet hidden', await win.isHidden('#settings'), '| error', (await win.textContent('#settings-error')).trim().slice(0, 300));
if (!(await win.isHidden('#settings'))) await win.click('#cancel-settings');
// back to builtin
await win.click('#open-settings'); await win.waitForSelector('#settings:not([hidden])');
await win.selectOption('#s-think', 'builtin');
await win.click('#save-settings'); await new Promise((r) => setTimeout(r, 1500));
log('after choosing builtin: saved mode', await settingsMode(), '| sheet hidden', await win.isHidden('#settings'), '| error', (await win.textContent('#settings-error')).trim().slice(0, 300));
await win.screenshot({ path: path.join(shots, '3-after-builtin.png') });
if (!(await win.isHidden('#settings'))) await win.click('#cancel-settings');
await win.click('#open-settings'); await win.waitForSelector('#settings:not([hidden])');
log('reopened form shows:', await win.inputValue('#s-think'));
await win.click('#cancel-settings');
// a task with no working brain: what does the user see, and does retry duplicate the chat?
await win.fill('#task-input', 'Find PDF files in my Documents folder');
await win.click('#run-btn'); await new Promise((r) => setTimeout(r, 4000));
log('task status:', await win.textContent('#run-status').catch(() => '?'), '| error:', (await win.textContent('#summary-error').catch(() => '')).slice(0, 300));
await win.screenshot({ path: path.join(shots, '4-task.png') });
if (await win.isVisible('#run-again')) { await win.click('#run-again'); await new Promise((r) => setTimeout(r, 4000)); }
await win.fill('#reply-input', 'Now count how many there are');
await win.click('#reply-btn'); await new Promise((r) => setTimeout(r, 4000));
log('earlier turns:', await win.$$eval('#chat-earlier .bubble', (n) => n.map((x) => x.textContent)), '| chat title:', await win.textContent('#chat-title'));
await win.screenshot({ path: path.join(shots, '5-chat.png') });
await win.click('#toggle-chats'); await new Promise((r) => setTimeout(r, 500));
await win.screenshot({ path: path.join(shots, '6-chats-drawer.png') });
log('history items:', await win.$$eval('#history-list .history-item .h-text', (n) => n.map((x) => x.textContent)));
await app.close();
