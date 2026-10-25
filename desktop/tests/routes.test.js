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
