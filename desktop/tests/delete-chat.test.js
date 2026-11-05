'use strict';
// Deleting a chat from the history.
//
// Three things about the control are easy to get wrong and invisible once it
// looks right, so they are asserted here rather than eyeballed:
//
// 1. The delete button must be a SIBLING of the chat button, not a child. A
//    button inside a button is invalid markup and, in Chromium, the inner one
//    cannot be clicked at all - it would look finished and do nothing.
// 2. Its click must stop propagating, or deleting a chat also opens the chat
//    being deleted on the way out.
// 3. It must ask first. There is no undo, and the thing people fear losing is
//    their work, so the dialog has to say what stays as well as what goes.

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const dir = path.join(__dirname, '..', 'src', 'renderer');
const js = fs.readFileSync(path.join(dir, 'app.js'), 'utf8');
const css = fs.readFileSync(path.join(dir, 'styles.css'), 'utf8');
const html = fs.readFileSync(path.join(dir, 'index.html'), 'utf8');

function body(name) {
  let start = js.indexOf(`function ${name}(`);
  if (start === -1) start = js.indexOf(`async function ${name}(`);
  assert.notStrictEqual(start, -1, `app.js no longer declares ${name}`);
  const open = js.indexOf('{', start);
  let depth = 0;
  for (let i = open; i < js.length; i += 1) {
    if (js[i] === '{') depth += 1;
    else if (js[i] === '}' && --depth === 0) return js.slice(open, i + 1);
  }
  throw new Error(`could not find the end of ${name}`);
}

test('the delete button is a sibling of the chat button, never inside it', () => {
  const row = js.match(/el\('div', \{ className: 'history-row' \}, \[([^\]]*)\]\)/);
  assert.ok(row, 'the history row is no longer built as a div holding the two buttons');
  assert.ok(/\bbtn\b/.test(row[1]) && /deleteChatButton/.test(row[1]),
    `the row must hold the chat button and the delete button side by side, got: ${row[1]}`);
  // and the chat button itself must not be given the delete button as a child
  assert.ok(!/history-item'.*deleteChatButton/s.test(js.slice(js.indexOf("className: 'history-item'"), js.indexOf("history-row"))),
    'the delete button was nested inside the chat button');
});

test('clicking delete does not also open the chat', () => {
  const src = body('deleteChatButton');
  assert.ok(/stopPropagation/.test(src),
    'without stopPropagation the row click fires too and opens the chat being deleted');
});

test('it asks before deleting, and says what is kept', () => {
  const src = body('removeChat');
  assert.ok(/api\.confirm\(/.test(src), 'a chat is deleted with no confirmation');
  assert.ok(/if \(!sure\) return;/.test(src), 'the answer to the confirmation is ignored');
  for (const promise of [/stay in your folders/, /stays remembered/, /cannot be brought back/]) {
    assert.ok(promise.test(src), `the dialog does not say: ${promise}`);
  }
  // the confirmation must come before the request, not after it
  assert.ok(src.indexOf('api.confirm') < src.indexOf("'DELETE'"),
    'the chat is deleted before the person is asked');
});

test('it deletes the chat, not one message of it', () => {
  const src = body('removeChat');
  assert.ok(/thread_id \|\| task\.id/.test(src), 'it must address the whole chat by its thread');
  assert.ok(/\/chats\//.test(src) && !/\/tasks\//.test(src),
    'deleting a single task would leave a conversation of answers without questions');
});

test('deleting the chat on screen leaves the home screen, not a dead one', () => {
  const src = body('removeChat');
  assert.ok(/goHome\(\)/.test(src), 'the deleted chat would stay on screen with nothing behind it');
  assert.ok(/loadHistory\(\)/.test(src), 'the history list would still show the deleted chat');
});

test('a failed delete is reported rather than swallowed', () => {
  const src = body('removeChat');
  assert.ok(/if \(!res\.ok\) return showError/.test(src),
    'a refused delete (a chat still working) would look like nothing happened');
});

test('the control works without a mouse', () => {
  const src = body('deleteChatButton');
  assert.ok(/aria-label/.test(src), 'a screen reader would announce an unlabelled button');
  assert.ok(/attrs: \{ type: 'button'/.test(src), 'a button with no type submits');
  assert.ok(/\.history-del:focus-visible/.test(css),
    'the button is revealed on hover only, so a keyboard user can never see it');
});

test('the icon it uses exists', () => {
  assert.ok(/icon\('trash'\)/.test(body('deleteChatButton')));
  assert.ok(/<symbol id="i-trash"/.test(html), 'i-trash is referenced but not defined');
});

test('a long chat title cannot run underneath the button', () => {
  assert.ok(/\.history-row:hover \.h-text/.test(css) && /padding-right/.test(css),
    'the title needs room made for the control when it appears');
});
