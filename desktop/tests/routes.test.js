'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { isAllowedRoute } = require('../src/backend');

test('allowed routes pass', () => {
  assert.ok(isAllowedRoute('GET', '/health'));
  assert.ok(isAllowedRoute('PUT', '/settings'));
  assert.ok(isAllowedRoute('POST', '/tasks/plan'));
  assert.ok(isAllowedRoute('GET', '/tasks?q=pdf%20report&limit=100'));
  assert.ok(isAllowedRoute('GET', '/tasks/0123456789abcdef0123456789abcdef'));
  assert.ok(isAllowedRoute('POST', '/tasks/run'));
  assert.ok(isAllowedRoute('POST', '/tasks/0123456789abcdef0123456789abcdef/cancel'));
  assert.ok(isAllowedRoute('GET', '/tasks/0123456789abcdef0123456789abcdef/events?after=42'));
  assert.ok(isAllowedRoute('POST', '/approvals/0123456789abcdef0123456789abcdef'));
});

test('run routes are tight', () => {
  assert.ok(!isAllowedRoute('GET', '/tasks/run'));
  assert.ok(!isAllowedRoute('POST', '/approvals/abc'));
  assert.ok(!isAllowedRoute('GET', '/tasks/0123456789abcdef0123456789abcdef/events?after=1&x=2'));
});

test('everything else is refused', () => {
  assert.ok(!isAllowedRoute('DELETE', '/settings'));
  assert.ok(!isAllowedRoute('GET', '/tasks/../settings'));
  assert.ok(!isAllowedRoute('GET', '/tasks/abc'));
  assert.ok(!isAllowedRoute('POST', '/health'));
  assert.ok(!isAllowedRoute('GET', 'http://evil.example/'));
  assert.ok(!isAllowedRoute('GET', '/tasks?q=<script>'));
  assert.ok(!isAllowedRoute(undefined, '/health'));
  assert.ok(!isAllowedRoute('GET', '/health' + 'x'.repeat(400)));
});

const DOC = '0123456789abcdef0123456789abcdef';

test('brain and document routes the page may use', () => {
  for (const r of ['/brain/download', '/brain/download/cancel', '/brain/select', '/brain/remove', '/brain/restart']) assert.ok(isAllowedRoute('POST', r), r);
  assert.ok(isAllowedRoute('GET', `/documents/${DOC}`));
  assert.ok(isAllowedRoute('GET', `/documents/${DOC}?pages=1`));
  assert.ok(isAllowedRoute('GET', `/documents/${DOC}/search?q=invoice%20total`));
  assert.ok(isAllowedRoute('POST', `/documents/${DOC}/cancel`));
  assert.ok(!isAllowedRoute('GET', `/documents/${DOC}/search?q=a&x=1`));
  assert.ok(!isAllowedRoute('GET', '/models/auto'));
});

test('routes that take a file path are main-process only', () => {
  for (const [m, r] of [['POST', '/brain/import'], ['POST', '/documents/open'], ['POST', `/documents/${DOC}/searchable`]]) {
    assert.ok(!isAllowedRoute(m, r), `page must not reach ${r}`);
    assert.ok(isAllowedRoute(m, r, true), `main process may reach ${r}`);
  }
});

test('whatsapp routes', () => {
  assert.ok(isAllowedRoute('GET', '/messages/whatsapp'));
  assert.ok(isAllowedRoute('POST', '/messages/whatsapp/check'));
  assert.ok(!isAllowedRoute('POST', '/messages/whatsapp/send'));
});

test('speech routes', () => {
  // The bar may read status and manage models…
  assert.ok(isAllowedRoute('GET', '/speech'));
  assert.ok(isAllowedRoute('POST', '/speech/models/download'));
  assert.ok(isAllowedRoute('POST', '/speech/models/download/cancel'));
  assert.ok(isAllowedRoute('POST', '/speech/models/remove'));
  // …but audio never goes through the generic JSON route: sendAudio() is the only way in.
  assert.ok(!isAllowedRoute('POST', '/speech/transcribe'));
  assert.ok(!isAllowedRoute('POST', '/speech/transcribe', true));
  // No traversal or lookalikes.
  assert.ok(!isAllowedRoute('GET', '/speech/../settings'));
  assert.ok(!isAllowedRoute('DELETE', '/speech'));
  assert.ok(!isAllowedRoute('GET', '/speechx'));
});

test('live speech routes', () => {
  assert.ok(isAllowedRoute('POST', '/speech/stream/start'));
  assert.ok(isAllowedRoute('POST', '/speech/stream/cancel'));
  // Audio chunks are bytes: they go through postBytes, never the JSON allowlist.
  assert.ok(!isAllowedRoute('POST', '/speech/stream/abc123/chunk'));
  assert.ok(!isAllowedRoute('POST', '/speech/stream/abc123/finish'));
  assert.ok(!isAllowedRoute('POST', '/speech/stream/../settings'));
});

// ---------- where the quick bar sits ----------
// The bar can be dragged anywhere, and a position is remembered between launches.
// The failure that matters is silent: a bar left somewhere it cannot be grabbed.
const { clampBounds, defaultBounds } = require('../src/quickbar-position');

const SCREEN = { x: 0, y: 0, width: 1920, height: 1040 };
const BAR = { w: 660, h: 160 };

test('with no saved position the bar is centred at the top', () => {
  const b = defaultBounds(BAR, SCREEN);
  assert.equal(b.x, Math.round((1920 - 660) / 2));
  assert.equal(b.y, 10);
});

test('a saved position is used as it is when it fits', () => {
  const b = clampBounds({ x: 300, y: 400 }, BAR, SCREEN);
  assert.deepEqual([b.x, b.y], [300, 400]);
});

test('a bar dragged past the right or bottom edge is pulled back on screen', () => {
  const b = clampBounds({ x: 5000, y: 5000 }, BAR, SCREEN);
  assert.equal(b.x, 1920 - 660);
  assert.equal(b.y, 1040 - 160);
});

test('a bar dragged past the left or top edge is pulled back too', () => {
  const b = clampBounds({ x: -800, y: -400 }, BAR, SCREEN);
  assert.deepEqual([b.x, b.y], [0, 0]);
});

test('a position from a monitor that is gone lands on the screen that is left', () => {
  // Saved while a second display sat to the left at negative coordinates.
  const b = clampBounds({ x: -1700, y: 200 }, BAR, SCREEN);
  assert.ok(b.x >= SCREEN.x && b.x + BAR.w <= SCREEN.x + SCREEN.width);
});

test('the work area offset of a taskbar is respected', () => {
  const withTaskbar = { x: 0, y: 40, width: 1920, height: 1000 };
  const b = clampBounds({ x: 10, y: 0 }, BAR, withTaskbar);
  assert.equal(b.y, 40, 'the bar must not sit under the taskbar');
});

test('nonsense is treated as no position at all', () => {
  for (const bad of [null, {}, { x: 'left', y: 3 }, { x: NaN, y: 0 }]) {
    assert.deepEqual(clampBounds(bad, BAR, SCREEN), defaultBounds(BAR, SCREEN));
  }
});

test('a display narrower than the bar still leaves its left edge reachable', () => {
  const tiny = { x: 0, y: 0, width: 400, height: 300 };
  const b = clampBounds({ x: 900, y: 900 }, BAR, tiny);
  assert.equal(b.x, 0, 'the left edge must stay on screen so it can be grabbed');
});
