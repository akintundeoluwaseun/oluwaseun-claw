'use strict';
// Dark mode is declared twice: once for "Windows is dark and the person has not
// forced light", once for "the person chose dark". CSS has no way to share a
// block between two selectors without a preprocessor, so the duplication is
// deliberate — and this test is what stops the copies drifting, which would
// otherwise show up as one colour being wrong in only one of the two paths.

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const tokens = fs.readFileSync(path.join(__dirname, '..', 'src', 'renderer', 'tokens.css'), 'utf8');

/** The custom properties declared inside one block, as a map. */
function declarations(css) {
  const out = new Map();
  for (const line of css.split('\n')) {
    const m = /^\s*(--[a-z0-9-]+|color-scheme)\s*:\s*(.+?);\s*$/i.exec(line);
    if (m) out.set(m[1], m[2].trim());
  }
  return out;
}

function blockAfter(marker) {
  const at = tokens.indexOf(marker);
  assert.notStrictEqual(at, -1, `missing: ${marker}`);
  const open = tokens.indexOf('{', at + marker.length - 1);
  let depth = 0;
  for (let i = open; i < tokens.length; i += 1) {
    if (tokens[i] === '{') depth += 1;
    if (tokens[i] === '}') {
      depth -= 1;
      if (depth === 0) return tokens.slice(open + 1, i);
    }
  }
  throw new Error(`unclosed block: ${marker}`);
}

test('the two dark themes declare exactly the same things', () => {
  const bySystem = declarations(blockAfter(':root:not([data-theme="light"]) {'));
  const byChoice = declarations(blockAfter(':root[data-theme="dark"] {'));
  assert.ok(bySystem.size > 20, 'the system dark block looks empty');
  assert.deepStrictEqual([...byChoice.keys()].sort(), [...bySystem.keys()].sort(),
    'one dark block declares something the other does not');
  for (const [name, value] of bySystem) {
    assert.strictEqual(byChoice.get(name), value, `${name} differs between the two dark blocks`);
  }
});

test('both dark blocks tell the browser they are dark', () => {
  for (const sel of [':root:not([data-theme="light"]) {', ':root[data-theme="dark"] {']) {
    assert.match(blockAfter(sel), /color-scheme:\s*dark/, `${sel} does not set color-scheme`);
  }
});

test('choosing light wins over a dark system', () => {
  // The guard is what makes the choice win; without it, a dark Windows would
  // repaint the app dark however the person set it.
  assert.match(tokens, /@media \(prefers-color-scheme: dark\) \{\s*:root:not\(\[data-theme="light"\]\)/);
});

test('the logo tile follows the theme in both paths', () => {
  assert.match(tokens, /:root:not\(\[data-theme="light"\]\) \.mark-tile/);
  assert.match(tokens, /:root\[data-theme="dark"\] \.mark-tile/);
});
