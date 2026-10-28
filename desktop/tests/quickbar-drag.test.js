'use strict';
// The quick bar sits collapsed on the desktop all day, and collapsed it is a
// single <button> filling the window. A drag guard written as
// `closest('input, button, a, .link')` therefore excludes the only thing there
// is to grab, and the bar cannot be moved at all — which is exactly what
// shipped. These tests pin the two halves of the rule that replaced it:
// every real control refuses a drag, and the pill does not.

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const here = (...p) => path.join(__dirname, '..', 'src', 'renderer', ...p);
const js = fs.readFileSync(here('quickbar.js'), 'utf8');
const html = fs.readFileSync(here('quickbar.html'), 'utf8');

/** The NO_GRAB selector list, as the individual selectors it is made of. */
function noGrab() {
  const m = /const NO_GRAB = '([^']+)'/.exec(js);
  assert.ok(m, 'quickbar.js no longer declares NO_GRAB');
  return m[1].split(',').map((s) => s.trim()).filter(Boolean);
}

/** Every <button> and <input> in the quick bar's markup, as {tag, id}. */
function controls() {
  const out = [];
  for (const m of html.matchAll(/<(button|input)\b[^>]*\bid="([^"]+)"/g)) {
    out.push({ tag: m[1], id: m[2] });
  }
  assert.ok(out.length > 4, 'found almost no controls; the markup scan is broken');
  return out;
}

test('a drag can start on the collapsed pill', () => {
  const selectors = noGrab();
  assert.ok(
    !selectors.includes('button'),
    'NO_GRAB contains a bare `button` selector, which matches the collapsed pill — '
      + 'the whole bar — and makes it impossible to move',
  );
  assert.ok(!selectors.includes('#pill'), 'the pill must stay grabbable');
});

test('every other control refuses to start a drag', () => {
  const selectors = new Set(noGrab());
  // A control is covered either by its own id or by a bare tag selector, which
  // is how every <input> is covered at once.
  const missing = controls()
    .filter(({ id }) => id !== 'pill')
    .filter(({ tag, id }) => !selectors.has(`#${id}`) && !selectors.has(tag))
    .map(({ id }) => id);
  assert.deepStrictEqual(
    missing,
    [],
    `these controls would start a drag when pressed: ${missing.join(', ')}. `
      + 'Add each to NO_GRAB in quickbar.js, or the bar will slide around '
      + 'while someone is trying to press them.',
  );
});

test('the drag guard is applied everywhere, not just on mousedown', () => {
  // Double-click-to-reset used the same inline selector list and would drift
  // from it; both call sites now go through grabbable().
  assert.strictEqual(
    (js.match(/grabbable\(/g) || []).length >= 3,
    true,
    'grabbable() should be declared once and used by both mousedown and dblclick',
  );
  assert.ok(
    !/closest\('input, button, a, \.link'\)/.test(js),
    'an inline copy of the old guard is back; use grabbable() instead',
  );
});
