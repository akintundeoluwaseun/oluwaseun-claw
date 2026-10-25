'use strict';

const q = window.quick;
const $ = (id) => document.getElementById(id);
let phase = 'idle';
let shortcut = 'Ctrl+Shift+Space';
let stopKeys = 'Ctrl+Alt+X';

function setMode(mode) {
  document.body.dataset.mode = mode;
  if (mode === 'expanded') {
    $('task').focus();
    $('task').select();
  }
}

function renderStatus(s) {
  phase = s && s.phase ? s.phase : 'idle';
  document.body.dataset.phase = phase;
  const pill = $('pill');
  if (phase === 'working') {
    $('pill-text').textContent = s.activity || 'Working';
    $('pill-meta').textContent = s.usingInput ? `${stopKeys} stops` : s.step ? `step ${s.step}` : '';
    pill.setAttribute('aria-label', `Claw is working: ${s.activity}. Open Claw`);
  } else if (phase === 'attention') {
    $('pill-text').textContent = 'Needs your OK';
    $('pill-meta').textContent = 'Review';
    pill.setAttribute('aria-label', 'Claw is waiting for your approval. Open Claw');
  } else if (phase === 'offline') {
    $('pill-text').textContent = 'Claw is starting';
    $('pill-meta').textContent = '';
  } else {
    $('pill-text').textContent = 'Ask Claw';
    $('pill-meta').textContent = shortcut;
    pill.setAttribute('aria-label', 'Give Claw a task');
  }
}

function foot(text, tone) {
  $('foot-text').textContent = text;
  if (tone) $('panel-foot').dataset.tone = tone;
  else delete $('panel-foot').dataset.tone;
}

$('pill').addEventListener('click', () => {
  if (phase === 'working' || phase === 'attention') q.openApp();
  else q.setMode('expanded');
});
$('pill-stop').addEventListener('click', () => q.stop());
$('open-app').addEventListener('click', () => q.openApp());
$('task').addEventListener('input', () => {
  $('run').disabled = $('task').value.trim().length < 3;
  foot('Claw asks before it saves files or changes anything online.');
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') q.setMode('collapsed');
});
$('panel').addEventListener('submit', async (e) => {
  e.preventDefault();
  const task = $('task').value.trim();
  if (task.length < 3) return;
  $('run').disabled = true;
  foot('Starting…');
  const res = await q.run(task);
  if (res && res.ok) {
    $('task').value = '';
    foot('On it. You will get a notification when it is done.', 'ok');
  } else {
    $('run').disabled = false;
    foot((res && res.message) || 'Could not start the task.', 'bad');
  }
});

q.onMode((mode) => {
  setMode(mode);
  if (mode === 'collapsed') foot('Claw asks before it saves files or changes anything online.');
});
q.onStatus(renderStatus);
q.stopShortcut().then((k) => {
  stopKeys = k || stopKeys;
});
q.shortcut().then((s) => {
  shortcut = s || shortcut;
  q.status().then(renderStatus);
});
