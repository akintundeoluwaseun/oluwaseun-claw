'use strict';
// Renderer logic. All text from the agent or model is inserted with
// textContent (never innerHTML) because it is untrusted.

const $ = (id) => document.getElementById(id);
const api = window.claw;

const RISK_LABEL = {
  read_only: 'Reading only',
  local_write: 'Changes local files',
  external: 'Changes things online',
  destructive: 'Deletes / sends / buys',
};
const PERMISSION_TAG = {
  allow: ['Runs without asking', 'tag-ok'],
  ask: ['Will ask you first', 'tag-warn'],
  deny: ['Blocked by your settings', 'tag-bad'],
};
const CAPABILITY_LABEL = { browser: 'Browser', desktop: 'Desktop app', files: 'Files', reasoning: 'Thinking' };
const STATUS_LABEL = { planned: 'Plan ready', failed: 'Failed', planning: 'Planning', created: 'Created' };

const state = {
  backend: { state: 'starting', message: 'Starting agent…' },
  settings: null,
  busy: false,
  currentTaskId: null,
  draftFolders: [],
};

function el(tag, opts = {}, children = []) {
  const node = document.createElement(tag);
  if (opts.className) node.className = opts.className;
  if (opts.text !== undefined) node.textContent = opts.text;
  if (opts.attrs) for (const [k, v] of Object.entries(opts.attrs)) node.setAttribute(k, v);
  for (const child of children) node.append(child);
  return node;
}

function setPill(id, pillState, text, title) {
  const pill = $(id);
  pill.dataset.state = pillState;
  pill.querySelector('.pill-text').textContent = text;
  pill.title = title || text;
}

// ---------- Errors ----------
function showError(error, fallback = 'Something went wrong.') {
  const e = (error && error.error) || error || {};
  $('error-title').textContent = e.message || fallback;
  $('error-hint').textContent = e.hint || '';
  const list = $('error-details');
  list.replaceChildren(...(e.details || []).map((d) => el('li', { text: d })));
  $('error-banner').hidden = false;
}
function clearError() {
  $('error-banner').hidden = true;
}

// ---------- Backend + model status ----------
function applyBackendStatus(status) {
  if (!status) return;
  state.backend = status;
  const map = { ready: 'ready', starting: 'starting', failed: 'failed' };
  setPill('backend-pill', map[status.state] || 'unknown', status.message, [status.message, status.detail].filter(Boolean).join('\n'));
  updatePlanButton();
  if (status.state === 'ready') {
    loadSettings();
    refreshModelStatus();
    loadHistory();
  } else if (status.state === 'failed') {
    setPill('model-pill', 'unknown', 'Model: unknown');
    showError({ message: status.message, hint: status.detail ? status.detail : 'Click the agent status to try again.' });
  }
}

async function refreshModelStatus() {
  const res = await api.api('GET', '/models/status');
  if (!res.ok) {
    setPill('model-pill', 'failed', 'Model: error', res.body?.error?.message);
    return;
  }
  const s = res.body;
  if (s.model_available) setPill('model-pill', 'ready', `Model: ${s.model}`, s.message);
  else if (!s.server_reachable) setPill('model-pill', 'failed', 'Model server offline', s.message);
  else setPill('model-pill', 'missing', s.model ? `Model missing: ${s.model}` : 'No model selected', s.message);
}

function updatePlanButton() {
  const text = $('task-input').value.trim();
  $('plan-btn').disabled = state.busy || state.backend.state !== 'ready' || text.length < 3;
  $('plan-btn').textContent = state.busy ? 'Planning…' : 'Plan task';
}

// ---------- Planning ----------
function setProgress(statuses) {
  for (const li of document.querySelectorAll('.progress-steps li')) {
    const s = statuses[li.dataset.stage];
    if (s) li.dataset.status = s;
    else delete li.dataset.status;
  }
}

function progressFromEvents(task) {
  const kinds = new Set((task.events || []).map((e) => e.kind));
  const st = {};
  if (kinds.has('requested')) st.send = 'done';
  if (kinds.has('planned')) Object.assign(st, { model: 'done', validate: 'done', done: 'done' });
  else if (kinds.has('failed')) {
    st.model = 'failed';
  }
  return st;
}

async function planTask() {
  const task = $('task-input').value.trim();
  if (task.length < 3 || state.busy) return;
  clearError();
  state.busy = true;
  updatePlanButton();
  $('empty-state').hidden = true;
  $('results').hidden = true;
  $('progress').hidden = false;
  setProgress({ send: 'active' }); // waiting for the agent's real reply

  const res = await api.api('POST', '/tasks/plan', { task });
  state.busy = false;
  updatePlanButton();

  if (res.ok) {
    setProgress(progressFromEvents(res.body));
    renderTask(res.body);
    $('task-input').value = '';
    updatePlanButton();
  } else {
    setProgress({ send: res.status === 0 || res.status === 503 ? 'failed' : 'done', model: res.status >= 500 || res.status === 422 ? 'failed' : undefined });
    showError(res.body, 'The task could not be planned.');
  }
  loadHistory();
  refreshModelStatus();
}

function renderTask(task) {
  state.currentTaskId = task.id;
  $('empty-state').hidden = true;
  $('results').hidden = false;
  const statusTag = $('plan-status');
  statusTag.textContent = STATUS_LABEL[task.status] || task.status;
  statusTag.className = `tag ${task.status === 'planned' ? 'tag-ok' : task.status === 'failed' ? 'tag-bad' : 'tag-muted'}`;

  const plan = task.plan;
  $('plan-goal').textContent = plan ? plan.goal : task.task_text;
  $('plan-notice').textContent = plan
    ? 'This is a proposed plan. Step execution is not built yet, so none of these steps have been carried out.'
    : `No plan was produced. ${task.error || ''}`.trim();

  const steps = (plan?.steps || []).map((step) => {
    const [permText, permClass] = PERMISSION_TAG[step.permission] || [step.permission, 'tag-muted'];
    return el('li', { className: 'plan-step' }, [
      el('span', { className: 'plan-step-num', text: String(step.index) }),
      el('div', {}, [
        el('p', { className: 'plan-step-desc', text: step.description }),
        el('p', { className: 'plan-step-expect', text: `Expected: ${step.expected_result}` }),
        el('div', { className: 'tags' }, [
          el('span', { className: 'tag', text: CAPABILITY_LABEL[step.capability] || step.capability }),
          el('span', { className: 'tag', text: RISK_LABEL[step.risk] || step.risk }),
          el('span', { className: `tag ${permClass}`, text: permText }),
          el('span', { className: 'tag tag-muted', text: 'Not run' }),
        ]),
      ]),
    ]);
  });
  $('plan-steps').replaceChildren(...steps);

  const questions = plan?.questions || [];
  $('plan-questions').hidden = questions.length === 0;
  $('plan-questions').querySelector('ul').replaceChildren(...questions.map((q) => el('li', { text: q })));

  const events = (task.events || []).map((e) => {
    const time = new Date(e.ts).toLocaleTimeString();
    const extra = e.data && (e.data.message || e.data.model || (e.data.steps !== undefined ? `${e.data.steps} steps` : ''));
    return el('li', { text: `${time}  ${e.kind}${extra ? ' · ' + extra : ''}` });
  });
  $('plan-events').replaceChildren(...events);
  markHistorySelection();
}

// ---------- History ----------
let historyTimer = null;
async function loadHistory() {
  if (state.backend.state !== 'ready') return;
  const q = $('history-search').value.trim();
  const route = q ? `/tasks?q=${encodeQuery(q)}&limit=100` : '/tasks?limit=100';
  const res = await api.api('GET', route);
  if (!res.ok) return;
  const items = res.body.tasks.map((t) => {
    const btn = el('button', { attrs: { type: 'button', 'data-id': t.id } }, [
      el('span', { className: 'history-item-text', text: t.task_text }),
      el('span', { className: 'history-item-meta', text: `${STATUS_LABEL[t.status] || t.status} · ${new Date(t.created_at).toLocaleString()}` }),
    ]);
    btn.addEventListener('click', () => openTask(t.id));
    return el('li', {}, [btn]);
  });
  $('history-list').replaceChildren(...items);
  $('history-empty').hidden = items.length > 0;
  $('history-empty').textContent = q ? 'No tasks match that search.' : 'Your planned tasks will appear here.';
  markHistorySelection();
}

function encodeQuery(q) {
  return encodeURIComponent(q).replace(/[!'()*~]/g, (c) => '%' + c.charCodeAt(0).toString(16).toUpperCase());
}

function markHistorySelection() {
  for (const b of document.querySelectorAll('#history-list button')) {
    b.setAttribute('aria-current', b.dataset.id === state.currentTaskId ? 'true' : 'false');
  }
}

async function openTask(id) {
  const res = await api.api('GET', `/tasks/${id}`);
  if (!res.ok) return showError(res.body);
  clearError();
  $('progress').hidden = false;
  setProgress(progressFromEvents(res.body));
  renderTask(res.body);
}

// ---------- Settings ----------
async function loadSettings() {
  const res = await api.api('GET', '/settings');
  if (!res.ok) return;
  state.settings = res.body.settings;
  $('data-dir').textContent = `Settings and history are stored in ${res.body.data_dir}`;
  if (res.body.error) {
    showError({ message: res.body.error.message, hint: 'Open Settings, correct them, and save.', details: res.body.error.details });
  }
}

const DEFAULT_URLS = { ollama: 'http://127.0.0.1:11434', openai_compatible: 'http://127.0.0.1:8080' };

function fillSettingsForm(s) {
  $('s-provider').value = s.model.provider;
  $('s-base-url').value = s.model.base_url;
  $('s-model').value = s.model.model;
  $('s-timeout').value = s.model.request_timeout_s;
  $('s-temperature').value = s.model.temperature;
  $('s-remote').checked = !!s.model.allow_remote_server;
  for (const level of ['read_only', 'local_write', 'external', 'destructive']) {
    $(`p-${level}`).value = s.permissions.modes[level];
  }
  state.draftFolders = [...s.permissions.authorized_folders];
  renderFolders();
  $('s-test-result').textContent = '';
  $('settings-error').hidden = true;
}

function readModelForm() {
  return {
    provider: $('s-provider').value,
    base_url: $('s-base-url').value.trim(),
    model: $('s-model').value.trim(),
    request_timeout_s: Number($('s-timeout').value),
    temperature: Number($('s-temperature').value),
    allow_remote_server: $('s-remote').checked,
  };
}

function readSettingsForm() {
  return {
    version: 1,
    model: readModelForm(),
    permissions: {
      modes: Object.fromEntries(['read_only', 'local_write', 'external', 'destructive'].map((l) => [l, $(`p-${l}`).value])),
      authorized_folders: state.draftFolders,
    },
  };
}

function renderFolders() {
  const items = state.draftFolders.map((folder, i) => {
    const remove = el('button', { className: 'btn btn-ghost btn-small', text: 'Remove', attrs: { type: 'button', 'aria-label': `Remove ${folder}` } });
    remove.addEventListener('click', () => {
      state.draftFolders.splice(i, 1);
      renderFolders();
    });
    return el('li', {}, [el('span', { text: folder, attrs: { title: folder } }), remove]);
  });
  $('folder-list').replaceChildren(...items);
  $('folder-empty').hidden = items.length > 0;
}

let lastFocus = null;
function openSettings() {
  lastFocus = document.activeElement;
  fillSettingsForm(state.settings || defaultSettings());
  $('settings').hidden = false;
  $('settings-scrim').hidden = false;
  $('s-provider').focus();
}
function closeSettings() {
  $('settings').hidden = true;
  $('settings-scrim').hidden = true;
  if (lastFocus) lastFocus.focus();
}
function defaultSettings() {
  return {
    model: { provider: 'ollama', base_url: DEFAULT_URLS.ollama, model: '', request_timeout_s: 120, temperature: 0.2, allow_remote_server: false },
    permissions: { modes: { read_only: 'allow', local_write: 'ask', external: 'ask', destructive: 'ask' }, authorized_folders: [] },
  };
}

async function testConnection() {
  const note = $('s-test-result');
  note.dataset.tone = '';
  note.textContent = 'Checking…';
  const res = await api.api('POST', '/models/probe', readModelForm());
  if (!res.ok) {
    note.dataset.tone = 'bad';
    const e = res.body?.error || {};
    note.textContent = [e.message, ...(e.details || [])].filter(Boolean).join(' — ');
    return;
  }
  const s = res.body;
  $('s-model-list').replaceChildren(...s.available_models.map((m) => el('option', { attrs: { value: m } })));
  note.dataset.tone = s.model_available ? 'ok' : 'bad';
  const listed = s.available_models.length ? ` · Installed: ${s.available_models.join(', ')}` : '';
  note.textContent = s.message + (s.server_reachable ? listed : '');
}

async function saveSettings() {
  const res = await api.api('PUT', '/settings', readSettingsForm());
  const box = $('settings-error');
  if (!res.ok) {
    const e = res.body?.error || {};
    box.replaceChildren(el('div', {}, [el('strong', { text: e.message || 'Settings could not be saved.' }), el('ul', {}, (e.details || []).map((d) => el('li', { text: d })))]));
    box.hidden = false;
    box.scrollIntoView({ block: 'nearest' });
    return;
  }
  state.settings = res.body.settings;
  clearError();
  closeSettings();
  refreshModelStatus();
}

// ---------- Wiring ----------
function wire() {
  $('task-input').addEventListener('input', updatePlanButton);
  $('task-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      planTask();
    }
  });
  $('plan-btn').addEventListener('click', planTask);
  $('error-dismiss').addEventListener('click', clearError);
  $('open-settings').addEventListener('click', openSettings);
  $('close-settings').addEventListener('click', closeSettings);
  $('cancel-settings').addEventListener('click', closeSettings);
  $('settings-scrim').addEventListener('click', closeSettings);
  $('save-settings').addEventListener('click', saveSettings);
  $('s-test').addEventListener('click', testConnection);
  for (const id of ['s-provider', 's-base-url', 's-model', 's-remote']) {
    $(id).addEventListener('input', () => {
      $('s-test-result').textContent = '';
      $('s-test-result').dataset.tone = '';
    });
  }
  $('s-provider').addEventListener('change', () => {
    const url = $('s-base-url').value.trim();
    if (!url || Object.values(DEFAULT_URLS).includes(url)) $('s-base-url').value = DEFAULT_URLS[$('s-provider').value];
  });
  $('add-folder').addEventListener('click', async () => {
    const folder = await api.pickFolder();
    if (folder && !state.draftFolders.includes(folder)) {
      state.draftFolders.push(folder);
      renderFolders();
    }
  });
  $('history-search').addEventListener('input', () => {
    clearTimeout(historyTimer);
    historyTimer = setTimeout(loadHistory, 200);
  });
  $('backend-pill').addEventListener('click', async () => {
    if (state.backend.state !== 'failed') return;
    clearError();
    applyBackendStatus({ state: 'starting', message: 'Restarting agent…' });
    applyBackendStatus(await api.restartBackend());
  });
  $('model-pill').addEventListener('click', () => {
    if ($('model-pill').dataset.state !== 'ready') openSettings();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !$('settings').hidden) closeSettings();
  });

  api.onBackendStatus(applyBackendStatus);
  api.backendStatus().then(applyBackendStatus);
}

wire();
