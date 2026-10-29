'use strict';
// A botched insertion once pasted the whole .pill-hide rule into the middle of
// two unrelated selector lists, three copies in all. CSS swallows it without
// complaint: a comment between a selector and its `{` is legal, so
//
//   body[data-phase="working"] .pill-stop, body[data-phase="attention"] /*…*/
//   .pill-hide { … }
//
// parses fine and quietly means something else entirely. The leftover tails
// (`.pill-stop { display: none; }`) then applied to every state instead of one,
// which killed the Stop button and left the collapsed pill showing behind the
// open panel. Nothing was watching for it, so these tests watch now.

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const css = fs.readFileSync(
  path.join(__dirname, '..', 'src', 'renderer', 'quickbar.css'), 'utf8',
);

/** Every rule in the sheet as {selector, body}, selectors kept verbatim. */
function rules() {
  const out = [];
  for (const m of css.matchAll(/(^|\})([^{}]*)\{([^{}]*)\}/g)) {
    out.push({ selector: m[2].trim(), body: m[3].trim() });
  }
  return out;
}

test('no rule is a verbatim duplicate of another', () => {
  // Repeating a selector with a DIFFERENT body is ordinary CSS - a later rule
  // refining an earlier one. Repeating selector and body together is never
  // meant: it is a paste that went wrong.
  const seen = new Map();
  for (const { selector, body } of rules()) {
    if (!body) continue;
    const key = `${selector.replace(/\s+/g, ' ')} {${body.replace(/\s+/g, ' ')}}`;
    seen.set(key, (seen.get(key) || 0) + 1);
  }
  const dupes = [...seen].filter(([, n]) => n > 1).map(([k, n]) => `${k.slice(0, 70)}… (×${n})`);
  assert.deepStrictEqual(dupes, [], `pasted twice: ${dupes.join('; ')}`);
});

test('no comment sits inside a selector list', () => {
  // This is the shape that made the corruption invisible: CSS allows a comment
  // between a selector and its brace, so the rule parses and quietly applies to
  // something other than what it appears to.
  // A comment before a rule is ordinary documentation. The bug is a comment
  // that appears after the selector list has already begun.
  const bad = rules()
    .map((r) => ({ ...r, tail: r.selector.replace(/^\s*(?:\/\*[\s\S]*?\*\/\s*)*/, '') }))
    .filter((r) => r.tail.includes('/*'))
    .map((r) => r.tail.replace(/\s+/g, ' ').slice(0, 80));
  assert.deepStrictEqual(
    bad,
    [],
    `a comment interrupts these selector lists, so the rule after it does not `
      + `mean what it looks like: ${bad.join('; ')}`,
  );
});

test('the Stop button and the collapsed pill are only ever hidden conditionally', () => {
  // An unqualified `.pill-stop { display: … }` was the leftover tail of the bad
  // paste, and it overrode the state-dependent rules for every phase at once.
  // A bare `.pill-stop` rule that sets size and colour is fine; one that sets
  // display is not.
  // The base `.pill-stop` rule starts hidden and says much else besides; that
  // is the intended default. What the bad paste left behind was a rule whose
  // only declaration was display, which then beat every state-dependent rule.
  const loose = rules().filter(
    (r) => r.selector === '.pill-stop'
      && /^display\s*:[^;]+;?$/.test(r.body.trim()),
  );
  assert.strictEqual(
    loose.length,
    0,
    'a bare `.pill-stop` rule sets display for every state at once; qualify it '
      + 'with data-phase or data-mode',
  );
  assert.match(
    css,
    /body\[data-phase="working"\] \.pill-stop, body\[data-phase="attention"\] \.pill-stop \{ display: inline-flex; \}/,
    'the Stop button must appear while a task is working or waiting',
  );
  assert.match(
    css,
    /body\[data-mode="expanded"\] \.pill, body\[data-mode="expanded"\] \.pill-stop \{ display: none; \}/,
    'the collapsed pill must be hidden while the panel is open, or both show at once',
  );
});

test('the close button can be seen without hovering first', () => {
  const block = /\.pill-hide \{([^}]*)\}/.exec(css);
  assert.ok(block, '.pill-hide is no longer declared');
  const opacity = /opacity:\s*([\d.]+)/.exec(block[1]);
  assert.ok(opacity, '.pill-hide declares no resting opacity');
  assert.ok(
    Number(opacity[1]) > 0,
    'the close button rests at opacity 0, so nobody can tell it is there',
  );
});
