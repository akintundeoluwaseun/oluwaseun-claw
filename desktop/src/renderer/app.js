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
const STATUS_LABEL = {
  planned: 'Plan ready', failed: 'Failed', planning: 'Planning', created: 'Created', running: 'Running',
  awaiting_approval: 'Waiting for you', completed: 'Finished', stopped: 'Stopped', cancelled: 'Stopped by you',
  incomplete: 'Step limit reached', interrupted: 'Interrupted',
};
const STATUS_TONE = {
  planned: 'tag-ok', completed: 'tag-ok', failed: 'tag-bad', stopped: 'tag-bad', cancelled: 'tag-muted',
  incomplete: 'tag-warn', interrupted: 'tag-warn', awaiting_approval: 'tag-warn', running: 'tag-muted', planning: 'tag-muted',
};
const RUN_STATUSES = new Set(['running', 'awaiting_approval', 'completed', 'stopped', 'cancelled', 'incomplete', 'interrupted']);
const ACTIVE_STATUSES = new Set(['created', 'planning', 'running', 'awaiting_approval']);
const TOOL_LABEL = {
  web_search: 'Search the web', open_url: 'Open a web page', open_search_result: 'Open a search result',
  read_page: 'Read the page', extract_links: 'Collect links', click_link: 'Follow a link', click_button: 'Click a button',
  list_tabs: 'List tabs', new_tab: 'Open a new tab', switch_tab: 'Switch tab', close_tab: 'Close a tab',
  search_browser_history: 'Search your browsing history', save_links: 'Save links to a file',
};
const OUTCOME_TAG = {
  verified: ['Done · checked', 'tag-ok'], done_unverified: ['Done · not checked', 'tag-warn'],
  failed: ['Failed', 'tag-bad'], rejected: ['Rejected', 'tag-bad'], denied: ['Not allowed', 'tag-bad'],
};

const state = {
  backend: { state: 'starting', message: 'Starting agent…' },
  settings: null,
  busy: false,
  currentTaskId: null,
  run: null, // { id, after, events, status, timer }
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
    resumeRunningTask();
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

function isRunning() {
  return !!(state.run && ACTIVE_STATUSES.has(state.run.status));
}

function updatePlanButton() {
  const text = $('task-input').value.trim();
  const blocked = state.busy || isRunning() || state.backend.state !== 'ready' || text.length < 3;
  $('plan-btn').disabled = blocked;
  $('run-btn').disabled = blocked;
  $('plan-btn').textContent = state.busy ? 'Planning…' : 'Plan only';
  $('run-btn').textContent = isRunning() ? 'Running…' : 'Run task';
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
  if (task.length < 3 || state.busy || isRunning()) return;
  clearError();
  stopWatching();
  state.busy = true;
  updatePlanButton();
  $('empty-state').hidden = true;
  $('results').hidden = true;
  $('run-panel').hidden = true;
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

function renderTask(task, { runMode = false } = {}) {
  state.currentTaskId = task.id;
  $('empty-state').hidden = true;
  $('results').hidden = !task.plan && runMode;
  const statusTag = $('plan-status');
  statusTag.hidden = runMode;
  statusTag.textContent = STATUS_LABEL[task.status] || task.status;
  statusTag.className = `tag ${STATUS_TONE[task.status] || 'tag-muted'}`;

  const plan = task.plan;
  $('plan-goal').textContent = plan ? plan.goal : task.task_text;
  $('plan-notice').textContent = !plan
    ? `No plan was produced. ${task.error || ''}`.trim()
    : runMode
      ? 'The plan the agent started from. What actually happened is listed under the task above.'
      : 'A plan only: none of these steps have been carried out. Use Run task to have the agent do it.';

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
          ...(runMode ? [] : [el('span', { className: 'tag tag-muted', text: 'Not run' })]),
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
  const task = res.body;
  if (RUN_STATUSES.has(task.status) || task.result || task.events.some((e) => e.kind === 'requested_task')) {
    $('progress').hidden = true;
    startWatching(task.id, task.task_text);
    return;
  }
  stopWatching();
  $('run-panel').hidden = true;
  $('progress').hidden = false;
  setProgress(progressFromEvents(task));
  renderTask(task);
}

// ---------- Running tasks ----------
async function runTask() {
  const task = $('task-input').value.trim();
  if (task.length < 3 || state.busy || isRunning()) return;
  clearError();
  const res = await api.api('POST', '/tasks/run', { task });
  if (!res.ok) {
    showError(res.body, 'The task could not be started.');
    return;
  }
  $('task-input').value = '';
  startWatching(res.body.id, task);
  loadHistory();
}

function startWatching(id, title) {
  stopWatching();
  state.run = { id, title, after: 0, events: [], status: 'created', timer: null, approvals: [] };
  state.currentTaskId = id;
  $('empty-state').hidden = true;
  $('progress').hidden = true;
  $('results').hidden = true;
  $('run-panel').hidden = false;
  $('run-title').textContent = title;
  $('activity').replaceChildren();
  $('run-summary').hidden = true;
  $('approval-card').hidden = true;
  markHistorySelection();
  pollRun();
}

function stopWatching() {
  if (state.run && state.run.timer) clearTimeout(state.run.timer);
  state.run = null;
}

async function pollRun() {
  const run = state.run;
  if (!run) return;
  const res = await api.api('GET', `/tasks/${run.id}/events?after=${run.after}`);
  if (state.run !== run) return; // user switched tasks meanwhile
  if (res.ok) {
    const body = res.body;
    for (const e of body.events) {
      run.events.push(e);
      run.after = Math.max(run.after, e.id);
    }
    run.status = body.status;
    run.approvals = body.approvals;
    renderRun(body);
  }
  updatePlanButton();
  if (ACTIVE_STATUSES.has(run.status)) {
    run.timer = setTimeout(pollRun, 600);
  } else {
    loadHistory();
  }
}

function formatArgValue(v) {
  if (typeof v === 'string') return v;
  if (Array.isArray(v) && v.every((x) => x && typeof x === 'object' && 'url' in x)) {
    return v.map((x) => `• ${x.title || x.url}\n  ${x.url}${x.note ? `\n  ${x.note}` : ''}`).join('\n');
  }
  return JSON.stringify(v, null, 1);
}

function describeArgs(args) {
  return Object.entries(args || {})
    .map(([k, v]) => `${k}: ${typeof v === 'string' ? v : JSON.stringify(v)}`)
    .join(' · ');
}

function renderRun(body) {
  const run = state.run;
  const status = $('run-status');
  status.textContent = STATUS_LABEL[run.status] || run.status;
  status.className = `tag ${STATUS_TONE[run.status] || 'tag-muted'}`;
  $('stop-btn').hidden = !ACTIVE_STATUSES.has(run.status);

  // Activity: one row per step, updated as its events arrive.
  const steps = new Map();
  const notes = [];
  for (const e of run.events) {
    const d = e.data || {};
    if (e.kind === 'planned') notes.push(`Planned ${d.steps} step(s).`);
    if (e.kind === 'model_reply_rejected') notes.push(`The model's reply was rejected: ${d.problem}`);
    if (d.step === undefined) continue;
    const row = steps.get(d.step) || { step: d.step, tool: d.tool, args: null, outcome: null, detail: '', waiting: false, attempts: 0 };
    if (e.kind === 'requested') Object.assign(row, { tool: d.tool, args: d.args });
    if (e.kind === 'awaiting_approval') row.waiting = true;
    if (e.kind === 'approved') row.waiting = false;
    if (e.kind === 'attempted') row.attempts = d.attempt;
    if (e.kind === 'retrying') row.detail = `Retrying: ${d.reason}`;
    if (['verified', 'done_unverified', 'failed', 'rejected', 'denied'].includes(e.kind)) {
      row.outcome = e.kind;
      row.waiting = false;
      row.detail = d.detail || d.reason || (e.kind === 'denied' ? (d.by === 'settings' ? 'Blocked by your settings.' : d.by === 'timeout' ? 'No answer in time.' : 'You declined.') : '');
    }
    steps.set(d.step, row);
  }
  const rows = notes.map((n) => el('li', { className: 'act-note' }, [el('span', { className: 'act-num', text: '·' }), el('p', { className: 'small muted', text: n })]));
  for (const row of [...steps.values()].sort((a, b) => a.step - b.step)) {
    const [label, tone] = row.outcome
      ? OUTCOME_TAG[row.outcome] || [row.outcome, 'tag-muted']
      : row.waiting ? ['Waiting for you', 'tag-warn'] : row.attempts ? ['Working…', 'tag-muted'] : ['Requested', 'tag-muted'];
    rows.push(
      el('li', {}, [
        el('span', { className: 'act-num', text: String(row.step) }),
        el('div', {}, [
          el('p', { className: 'act-title', text: TOOL_LABEL[row.tool] || row.tool || 'Unknown action' }),
          el('p', { className: 'act-detail', text: row.detail || describeArgs(row.args) }),
        ]),
        el('span', { className: `tag ${tone}`, text: label }),
      ]),
    );
  }
  $('activity').replaceChildren(...rows);

  // Approval card
  const appr = (run.approvals || [])[0];
  const card = $('approval-card');
  if (appr) {
    const firstShow = card.hidden || card.dataset.id !== appr.id;
    card.dataset.id = appr.id;
    $('approval-title').textContent = `${TOOL_LABEL[appr.tool] || appr.tool} — ${RISK_LABEL[appr.risk] || appr.risk}${appr.sensitive_scope === 'browser_history' ? ' · private data' : ''}`;
    $('approval-desc').textContent = appr.description;
    $('approval-args').replaceChildren(
      ...Object.entries(appr.args || {})
        .filter(([, v]) => v !== null && v !== undefined && v !== '')
        .flatMap(([k, v]) => [el('dt', { text: k.replace(/_/g, ' ') }), el('dd', { text: formatArgValue(v) })]),
    );
    $('approval-reason').textContent = appr.reason ? `Agent's reason: ${appr.reason}` : '';
    card.hidden = false;
    $('approve-btn').disabled = false;
    $('deny-btn').disabled = false;
    if (firstShow) $('approve-btn').focus();
  } else {
    card.hidden = true;
  }

  // Plan (secondary) and outcome
  if (body.plan) renderTask({ id: run.id, status: run.status, plan: body.plan, task_text: run.title, events: run.events, error: body.error }, { runMode: true });
  const done = !ACTIVE_STATUSES.has(run.status);
  $('run-summary').hidden = !done;
  if (done) {
    const counts = (body.result && body.result.counts) || {};
    const parts = [
      counts.verified ? `${counts.verified} done and checked` : '',
      counts.done_unverified ? `${counts.done_unverified} done but not checked` : '',
      counts.failed ? `${counts.failed} failed` : '',
      counts.rejected ? `${counts.rejected} rejected` : '',
      counts.denied ? `${counts.denied} not allowed` : '',
    ].filter(Boolean);
    $('summary-counts').textContent = parts.length ? parts.join(' · ') : 'No steps were carried out.';
    $('summary-error').textContent = body.error || '';
    const answer = body.result && body.result.final_answer;
    $('summary-answer-wrap').hidden = !answer;
    $('summary-answer').textContent = answer || '';
  }
}

async function answerApproval(approve) {
  const id = $('approval-card').dataset.id;
  if (!id) return;
  $('approve-btn').disabled = true;
  $('deny-btn').disabled = true;
  const res = await api.api('POST', `/approvals/${id}`, { approve });
  if (!res.ok) showError(res.body, 'Your answer could not be sent.');
}

async function stopRun() {
  if (!state.run) return;
  $('stop-btn').disabled = true;
  const res = await api.api('POST', `/tasks/${state.run.id}/cancel`);
  $('stop-btn').disabled = false;
  if (!res.ok && res.status !== 409) showError(res.body, 'The task could not be stopped.');
}

async function resumeRunningTask() {
  const res = await api.api('GET', '/runner');
  if (res.ok && res.body.busy && res.body.current_id && !state.run) {
    const task = await api.api('GET', `/tasks/${res.body.current_id}`);
    startWatching(res.body.current_id, task.ok ? task.body.task_text : 'Running task');
  }
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
  const b = s.browser || {};
  $('b-channel').value = b.channel || 'msedge';
  $('b-visible').checked = !b.headless;
  $('b-engine').value = b.search_engine || 'duckduckgo';
  $('b-custom').value = b.custom_search_url || '';
  $('b-custom-wrap').hidden = $('b-engine').value !== 'custom';
  $('b-history').value = b.history_access || 'ask';
  const a = s.agent || {};
  $('a-max-steps').value = a.max_steps ?? 20;
  $('a-step-timeout').value = a.step_timeout_s ?? 60;
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
    browser: {
      ...((state.settings && state.settings.browser) || {}),
      channel: $('b-channel').value,
      headless: !$('b-visible').checked,
      search_engine: $('b-engine').value,
      custom_search_url: $('b-custom').value.trim(),
      history_access: $('b-history').value,
    },
    agent: {
      ...((state.settings && state.settings.agent) || {}),
      max_steps: Number($('a-max-steps').value),
      step_timeout_s: Number($('a-step-timeout').value),
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
      runTask();
    }
  });
  $('plan-btn').addEventListener('click', planTask);
  $('run-btn').addEventListener('click', runTask);
  $('stop-btn').addEventListener('click', stopRun);
  $('approve-btn').addEventListener('click', () => answerApproval(true));
  $('deny-btn').addEventListener('click', () => answerApproval(false));
  $('b-engine').addEventListener('change', () => {
    $('b-custom-wrap').hidden = $('b-engine').value !== 'custom';
  });
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
