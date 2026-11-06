'use strict';
// "The dictation is not even working."
//
// voiceEnabled was read once, at startup, and never again. Anyone who turned
// voice on and downloaded a model without restarting then had the microphone
// refused for the whole session: the window asks /speech itself, so the button
// said ready, while the main process still believed voice was off and denied
// the permission. getUserMedia then failed and the renderer reported "Windows
// has not given Claw the microphone" - blaming Windows for Claw's own stale
// flag. Restarting was the only cure, and nothing on screen said so.
//
// These assert the two halves of the fix: the answer is refreshed when it can
// change, and the request handler asks at the moment permission is wanted.

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const main = fs.readFileSync(path.join(__dirname, '..', 'src', 'main.js'), 'utf8');

test('the microphone answer is not frozen at startup', () => {
  assert.match(main, /async function refreshVoiceEnabled\s*\(/,
    'there is no way to re-read whether voice is on');
  const calls = main.match(/refreshVoiceEnabled\(\)/g) || [];
  assert.ok(calls.length >= 3,
    `refreshVoiceEnabled is only referenced ${calls.length} time(s); it must be called when settings `
    + 'change, when a voice model changes, and when permission is asked');
});

test('saving settings re-reads it', () => {
  const at = main.indexOf("method === 'PUT' && route === '/settings'");
  assert.notStrictEqual(at, -1, 'the settings-save hook has moved');
  assert.ok(main.slice(at, at + 400).includes('refreshVoiceEnabled'),
    'turning voice on in Settings would not reach the permission handler');
});

test('changing a voice model re-reads it', () => {
  assert.match(main, /startsWith\('\/speech'\)\)\s*refreshVoiceEnabled\(\)/,
    'downloading a voice model would not reach the permission handler');
});

test('the permission request asks what is true now', () => {
  const at = main.indexOf('setPermissionRequestHandler');
  assert.notStrictEqual(at, -1);
  const block = main.slice(at, at + 500);
  assert.ok(/async\s*\(/.test(block), 'the request handler cannot await, so it cannot re-check');
  assert.ok(block.includes('await refreshVoiceEnabled()'),
    'the request handler still answers from the cached flag');
});

test('it still refuses everything that is not our microphone', () => {
  const at = main.indexOf('setPermissionRequestHandler');
  const block = main.slice(at, at + 500);
  assert.ok(block.includes("permission !== 'media'") && block.includes('callback(false)'),
    'the handler no longer refuses other permissions outright');
  assert.ok(block.includes('!ours(contents)'), 'it no longer checks the request came from our windows');
});

test('a backend that cannot be reached does not silently revoke the microphone', () => {
  const at = main.indexOf('async function refreshVoiceEnabled');
  const fn = main.slice(at, main.indexOf('\n}', at));
  assert.ok(/catch\s*\{/.test(fn), 'a failed request would throw out of the permission handler');
  assert.ok(!/catch\s*\{[^}]*voiceEnabled\s*=\s*false/.test(fn),
    'a momentary backend hiccup would turn the microphone off mid-session');
});
