'use strict';
// An earlier turn in a chat shows a status pill and, beneath it, what Claw said.
//
// The pill and the line under it were drawn from the same value: the line fell
// back to the status text whenever a task had neither a final answer nor an
// error. Every stopped run, and every finished run whose answer came back
// empty, therefore printed its status twice, stacked - "Stopped" over
// "Stopped". It reads like a rendering fault, and on the screenshot the user
// sent it was one of the things that made the history look broken.
//
// The decision is now a pure function returning '' for "nothing to add", and
// the caller omits the second line entirely. These tests run that function for
// real rather than matching its source, because the bug was in what it
// returned, not in how it was written.

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const js = fs.readFileSync(path.join(__dirname, '..', 'src', 'renderer', 'app.js'), 'utf8');

/** Lift one top-level function out of the renderer and make it callable here.
 *  app.js is a browser script with no exports; pastReply touches no DOM and no
 *  module scope, which is the whole reason it was pulled out as a function. */
function lift(name) {
  const start = js.indexOf(`function ${name}(`);
  assert.notStrictEqual(start, -1, `app.js no longer declares ${name}`);
  const open = js.indexOf('{', start);
  let depth = 0;
  for (let i = open; i < js.length; i += 1) {
    if (js[i] === '{') depth += 1;
    else if (js[i] === '}') {
      depth -= 1;
      if (depth === 0) {
        // eslint-disable-next-line no-new-func
        return new Function(`${js.slice(start, i + 1)}; return ${name};`)();
      }
    }
  }
  throw new Error(`could not find the end of ${name}`);
}

const pastReply = lift('pastReply');

test('a real answer is shown', () => {
  const t = { result: { final_answer: 'Saved the report to Documents.' } };
  assert.strictEqual(pastReply(t, 'Done'), 'Saved the report to Documents.');
});

test('an error is shown when there is no answer', () => {
  assert.strictEqual(pastReply({ error: 'Could not reach the brain.' }, 'Failed'),
                     'Could not reach the brain.');
});

test('an answer wins over an error, because it is the later word', () => {
  const t = { result: { final_answer: 'Finished anyway.' }, error: 'step 2 failed' };
  assert.strictEqual(pastReply(t, 'Done'), 'Finished anyway.');
});

test('nothing to add returns nothing - the original bug', () => {
  // Stopped mid-run: no answer, no error. Previously returned 'Stopped', which
  // the caller then printed directly below the 'Stopped' pill.
  assert.strictEqual(pastReply({ status: 'cancelled' }, 'Stopped'), '');
});

test('an answer that merely repeats the status is not repeated', () => {
  assert.strictEqual(pastReply({ result: { final_answer: 'Done' } }, 'Done'), '');
  assert.strictEqual(pastReply({ result: { final_answer: '  Done  ' } }, 'Done'), '');
});

test('an answer of only whitespace counts as no answer', () => {
  assert.strictEqual(pastReply({ result: { final_answer: '   \n ' } }, 'Done'), '');
});

test('a missing result object does not throw', () => {
  assert.strictEqual(pastReply({}, 'Working'), '');
  assert.strictEqual(pastReply({ result: null }, 'Working'), '');
});

test('a long answer is still cut to 600 characters', () => {
  const long = 'x'.repeat(900);
  assert.strictEqual(pastReply({ result: { final_answer: long } }, 'Done').length, 600);
});

test('a non-string answer is not allowed to crash the history', () => {
  // The backend types this as a string, but history is the one screen that must
  // render whatever is in the database, including rows written by older builds.
  assert.strictEqual(pastReply({ error: 404 }, 'Failed'), '404');
});

test('the caller only renders the second line when there is one', () => {
  const start = js.indexOf('const reply = pastReply(');
  assert.notStrictEqual(start, -1, 'loadEarlier no longer calls pastReply');
  const near = js.slice(start, start + 700);
  assert.ok(/if\s*\(reply\)\s*body\.push/.test(near),
            'the turn-text line is pushed unconditionally again, so \'\' would print as an empty paragraph');
});
