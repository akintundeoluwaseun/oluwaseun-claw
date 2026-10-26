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
