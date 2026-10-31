'use strict';
// The S-CLAW phone app. Talks only to the computer it was paired with, on the home Wi-Fi.
const $ = (id) => document.getElementById(id);
let key = '';
try { key = localStorage.getItem('claw.key') || ''; } catch { /* private mode */ }
const fromHash = new URLSearchParams(location.hash.slice(1)).get('k');
if (fromHash) { key = fromHash; try { localStorage.setItem('claw.key', key); } catch { /* ok */ } history.replaceState(null, '', location.pathname); }
const ui = { view: 'chats', thread: null, task: null, timer: null, shownApproval: null };

async function api(method, path, body) {
  try {
    const r = await fetch(path, { method, headers: { 'x-claw-key': key, 'content-type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
    const data = await r.json().catch(() => ({}));
    return { ok: r.ok, status: r.status, body: data };
  } catch { return { ok: false, status: 0, body: { error: 'Your computer is not reachable. Is it on the same Wi-Fi?' } }; }
}
const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
const STATE = { completed: ['Done', 'ok'], failed: ['Failed', 'bad'], cancelled: ['Stopped', 'bad'], stopped: ['Stopped', 'bad'],
  incomplete: ['Ran out of steps', 'bad'], planning: ['Thinking', ''], running: ['Working', ''], awaiting_approval: ['Needs you', ''], created: ['Starting', ''] };

function show(view) {
  ui.view = view;
  document.body.dataset.view = view;
  for (const v of ['pair', 'chats', 'chat']) $(v).hidden = v !== view;
  $('composer').hidden = view === 'pair';
  $('back').hidden = view !== 'chat';
  $('new').hidden = view === 'pair';
}

async function hello() {
  if (!key) { show('pair'); $('sub').textContent = 'Not paired'; return; }
  const r = await api('GET', '/api/hello');
  if (r.status === 401) { show('pair'); $('sub').textContent = 'Not paired'; return; }
  $('sub').textContent = r.ok ? `Connected to ${r.body.computer}` : (r.body.error || 'Not connected');
  if (ui.view === 'pair') show('chats');
  if (ui.view === 'chats') loadChats();
}

async function loadChats() {
  const r = await api('GET', '/api/chats');
  if (!r.ok) return;
  $('chat-list').replaceChildren(...r.body.chats.map((c) => {
    const b = el('button', 'item');
    b.type = 'button';
    b.append(el('b', '', c.title), el('span', '', `${(STATE[c.status] || [c.status])[0]}${c.messages > 1 ? ` · ${c.messages} messages` : ''}`));
    b.addEventListener('click', () => openChat(c.thread_id, c.title));
    return b;
  }));
  $('chats-empty').hidden = r.body.chats.length > 0;
}

async function openChat(thread, title) {
  ui.thread = thread;
  $('title').textContent = title || 'Chat';
  show('chat');
  const r = await api('GET', `/api/chat/${thread}`);
  if (!r.ok) return;
  renderTurns(r.body.messages);
  const last = r.body.messages[r.body.messages.length - 1];
  if (last && ['created', 'planning', 'running', 'awaiting_approval'].includes(last.status)) follow(last.id);
}

function renderTurns(messages) {
  $('turns').replaceChildren(...messages.flatMap((m) => {
    const you = el('div', 'turn you'); you.append(el('p', 'bubble', m.text));
    const claw = el('div', 'turn claw'); const b = el('p', 'bubble');
    const [label, tone] = STATE[m.status] || [m.status, ''];
    b.append(el('span', `state ${tone}`, label), document.createTextNode(m.answer || (tone ? '' : 'Working on it…')));
    claw.append(b);
    return [you, claw];
  }));
  window.scrollTo({ top: document.body.scrollHeight });
}

function follow(taskId) {
  ui.task = taskId;
  clearTimeout(ui.timer);
  const tick = async () => {
    if (ui.task !== taskId) return;
    const r = await api('GET', `/api/task/${taskId}`);
    if (!r.ok) { ui.timer = setTimeout(tick, 3000); return; }
    const t = r.body;
    document.body.dataset.working = String(t.active);
    $('working').hidden = !t.active || t.approvals.length > 0;
    const a = t.approvals[0];
    $('approval').hidden = !a;
    if (a && ui.shownApproval !== a.id) {
      ui.shownApproval = a.id;
      $('ap-title').textContent = `Allow Claw to ${a.description || a.tool}?`;
      $('ap-args').replaceChildren(...Object.entries(a.args || {}).filter(([, v]) => v !== null && v !== '').slice(0, 6)
        .flatMap(([k, v]) => [el('dt', '', k.replace(/_/g, ' ')), el('dd', '', typeof v === 'string' ? v : JSON.stringify(v))]));
      $('allow').onclick = () => answer(a.id, true);
      $('deny').onclick = () => answer(a.id, false);
    }
    if (t.active) { ui.timer = setTimeout(tick, 1500); return; }
    const c = await api('GET', `/api/chat/${ui.thread}`);
    if (c.ok) renderTurns(c.body.messages);
    if (navigator.vibrate) navigator.vibrate(60);
  };
  tick();
}

async function answer(id, approve) {
  $('approval').hidden = true;
  await api('POST', `/api/approve/${id}`, { approve });
}

async function send(e) {
  e.preventDefault();
  const text = $('input').value.trim();
  if (text.length < 3) return;
  $('send').disabled = true;
  const r = await api('POST', '/api/run', { task: text, thread_id: ui.view === 'chat' ? ui.thread : null });
  if (!r.ok) { alertLine(r.body.error || 'Could not start that.'); $('send').disabled = false; return; }
  $('input').value = '';
  await openChat(r.body.thread_id, ui.view === 'chat' ? $('title').textContent : text.slice(0, 40));
  follow(r.body.id);
}

function alertLine(text) { $('sub').textContent = text; }

$('composer').addEventListener('submit', send);
$('input').addEventListener('input', () => { $('send').disabled = $('input').value.trim().length < 3; });
$('back').addEventListener('click', () => { ui.task = null; $('title').textContent = 'S-CLAW'; show('chats'); loadChats(); });
$('new').addEventListener('click', () => { ui.task = null; ui.thread = null; $('title').textContent = 'S-CLAW'; show('chats'); $('input').focus(); });
$('stop').addEventListener('click', () => api('POST', '/api/stop'));
show(key ? 'chats' : 'pair');
hello();
setInterval(() => { if (ui.view === 'chats') hello(); }, 8000);
