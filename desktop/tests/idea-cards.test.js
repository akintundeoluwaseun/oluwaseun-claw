'use strict';
// The six example cards under the task box.
//
// Each shows a short line of sample text and carries the real, fully specified
// prompt in data-task. Those were once the same string, and the string was too
// long: the home column is capped at 780px, the three-column grid gives each
// card a 177px text column - about 25 characters a line - and the clamp allows
// two lines. All six examples were 58 to 70 characters, so every card on the
// default window showed half a sentence and an ellipsis.
//
// The real check is tests/idea-cards.mjs, which loads the page in Chromium and
// measures scrollHeight against clientHeight. This is the guard that runs in
// the ordinary suite, which has no browser: a character budget derived from
// that measurement, plus the invariant that matters more than either - the text
// on the card may be short, but what clicking it puts in the box must not be.

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const html = fs.readFileSync(path.join(__dirname, '..', 'src', 'renderer', 'index.html'), 'utf8');

/** The home screen's example cards: visible label, sample line, real prompt. */
function cards() {
  const out = [];
  const re = /<button class="idea" type="button" data-task="([^"]*)">([\s\S]*?)<\/button>/g;
  for (const m of html.matchAll(re)) {
    const name = /<span class="idea-name">([^<]*)</.exec(m[2]);
    const eg = /<span class="idea-eg">([^<]*)</.exec(m[2]);
    assert.ok(name && eg, `a card is missing its name or example: ${m[2].slice(0, 80)}`);
    const unescape = (s) => s.replace(/&#39;/g, "'").replace(/&amp;/g, '&').replace(/&quot;/g, '"');
    out.push({ task: unescape(m[1]), name: name[1], eg: unescape(eg[1]) });
  }
  return out;
}

const ideas = cards();

test('all six cards are found', () => {
  assert.strictEqual(ideas.length, 6, 'the card markup changed shape; this file parses it by hand');
});

// 177px text column / ~7px per character = ~25 characters a line, two lines of
// clamp = ~50. 48 leaves a character of margin at each end for a wide glyph.
const BUDGET = 48;

test('no sample line can overflow the two lines it is given', () => {
  for (const i of ideas) {
    assert.ok(i.eg.length <= BUDGET,
      `"${i.name}" sample is ${i.eg.length} characters; over ${BUDGET} it clips mid-phrase in the ` +
      `three-column grid. Shorten the card and keep the detail in data-task. ` +
      `Confirm with: node tests/idea-cards.mjs`);
  }
});

test('a single word cannot be wider than the column', () => {
  // A 26-character word does not wrap; it overflows the card sideways, which the
  // line clamp does nothing about.
  for (const i of ideas) {
    for (const word of i.eg.split(/\s+/)) {
      assert.ok(word.length <= 24, `"${i.name}" contains "${word}", too long to wrap in a 177px column`);
    }
  }
});

test('clicking a card still fills the box with a properly specified task', () => {
  // The point of shortening the label was that the two need not match. The
  // prompt is what the planner actually receives, so it keeps the detail: a
  // place to look, or a place to put the result.
  for (const i of ideas) {
    assert.ok(i.task.length >= 40,
      `"${i.name}" would put only "${i.task}" in the box — too vague to plan from`);
    assert.ok(i.task.length <= 4000, `"${i.name}" exceeds the task box maxlength`);
  }
});

test('every card names a verb, so it reads as something to do', () => {
  for (const i of ideas) {
    assert.ok(/^(List|Find|Search|Open|Write|Make|Add|Put|Compare|Which|Check|Tell|Save)\b/.test(i.eg),
      `"${i.name}" sample does not start with something to do: "${i.eg}"`);
  }
});

test('the sample is not simply the prompt again', () => {
  // If they are equal the budget has been satisfied by shortening the prompt,
  // which makes the planner's input worse to fix a layout problem.
  for (const i of ideas) {
    assert.notStrictEqual(i.eg, i.task, `"${i.name}" uses one string for both again`);
  }
});
