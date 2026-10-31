'use strict';
// Two defects the first real Windows run found, both in how a task is started.
//
// 1. The minimum was three characters. "hi" is two, so the first thing anyone
//    types to find out whether the program is alive left the Run button
//    disabled, with nothing on screen saying why.
//
// 2. runTask READ state.busy and never SET it. Between the POST leaving and the
//    reply arriving, nothing was marked busy, so a second press started a second
//    task - which is how "Try again" piled up identical runs.
//
// The second is a race, and the invariant that kills it is positional: the flag
// has to be claimed synchronously, before the function's first await. A guard on
// the far side of an await guards nothing, because that is precisely the window
// in which the other press arrives. So that is what these assert.

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const js = fs.readFileSync(path.join(__dirname, '..', 'src', 'renderer', 'app.js'), 'utf8');

/** Comments stripped: the prose in this file explains the await window, and a
 *  positional check that counts the word "await" inside a comment measures the
 *  comment rather than the code. (It did, on the first run of this test.) */
function stripComments(src) {
  return src.replace(/\/\*[\s\S]*?\*\//g, ' ').replace(/(^|[^:])\/\/[^\n]*/g, '$1');
}

/** The source of one async function, from its signature to its closing brace. */
function body(name) {
  const start = js.indexOf(`async function ${name}(`);
  assert.notStrictEqual(start, -1, `app.js no longer declares ${name}`);
  const open = js.indexOf('{', start);
  let depth = 0;
  for (let i = open; i < js.length; i++) {
    if (js[i] === '{') depth++;
    else if (js[i] === '}' && --depth === 0) return stripComments(js.slice(open, i + 1));
  }
  throw new Error(`could not find the end of ${name}`);
}

test('a task that starts one claims the busy flag before it awaits anything', () => {
  const src = body('runTask');
  const claim = src.indexOf('state.busy = true');
  const firstAwait = src.indexOf('await');
  assert.notStrictEqual(claim, -1, 'runTask does not set state.busy at all — the original bug');
  assert.notStrictEqual(firstAwait, -1, 'runTask no longer awaits; this test needs rewriting');
  assert.ok(
    claim < firstAwait,
    'state.busy is set after the first await, which leaves the double-submit window open',
  );
});

test('the busy flag is released however the request ends', () => {
  const src = body('runTask');
  assert.ok(/finally\s*{/.test(src), 'no finally block: an early return would leave the UI stuck busy');
  assert.ok(/finally\s*{[^}]*state\.busy\s*=\s*false/.test(src), 'finally does not release state.busy');
});

test('planTask claims and releases its flag too', () => {
  const src = body('planTask');
  assert.ok(src.includes('state.busy = true'), 'planTask no longer marks itself busy');
  assert.ok(src.includes('state.busy = false'), 'planTask never releases busy');
});

test('two characters is a task', () => {
  const m = /const MIN_TASK = (\d+)/.exec(js);
  assert.ok(m, 'app.js no longer declares MIN_TASK');
  const min = Number(m[1]);
  assert.ok(min <= 2, `MIN_TASK is ${min}, so "hi" is still refused`);
  assert.ok(min >= 1, 'an empty task is still nothing to run');
});

test('no hand-written length minimum survives beside the named one', () => {
  // The old literal appeared in three places and they drifted apart; the point
  // of naming it is that there is now one of it.
  const stray = js.split('\n')
    .map((line, i) => [i + 1, line])
    .filter(([, line]) => /task\w*\.length\s*<\s*\d/.test(line) && !line.includes('MIN_TASK'));
  assert.deepStrictEqual(stray, [], `task-length checks not using MIN_TASK: ${JSON.stringify(stray)}`);
});
