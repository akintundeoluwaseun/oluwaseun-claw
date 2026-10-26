'use strict';
// Main window. Every piece of text from the agent, model or web is inserted with
// textContent (never innerHTML) because it is untrusted.

const $ = (id) => document.getElementById(id);
const api = window.claw;

const RISK_LABEL = {
  read_only: 'Only looks',
  local_write: 'Saves to your computer',
  external: 'Changes something online',
  destructive: 'Deletes, sends or buys',
};
const PERMISSION_TEXT = { allow: ['Goes ahead', 'perm-allow'], ask: ['Will ask you', 'perm-ask'], deny: ['Blocked by you', 'perm-deny'] };
const CAPABILITY_LABEL = { browser: 'Browser', desktop: 'Desktop app', files: 'Files', reasoning: 'Thinking' };
const STATUS = {
  created: ['Starting', 'live'], planning: ['Planning', 'live'], planned: ['Plan ready', 'ok'], running: ['Working', 'live'],
  awaiting_approval: ['Waiting for you', 'warn'], completed: ['Finished', 'ok'], failed: ['Failed', 'bad'],
  stopped: ['Stopped', 'bad'], cancelled: ['Stopped by you', 'muted'], incomplete: ['Ran out of steps', 'warn'],
  interrupted: ['Interrupted', 'warn'],
};
const ACTIVE = new Set(['created', 'planning', 'running', 'awaiting_approval']);
const TOOL_LABEL = {
  web_search: 'Searched the web', open_url: 'Opened a page', open_search_result: 'Opened a search result',
  read_page: 'Read the page', extract_links: 'Collected links', click_link: 'Followed a link', click_button: 'Clicked a button',
  list_tabs: 'Checked tabs', new_tab: 'Opened a tab', switch_tab: 'Switched tab', close_tab: 'Closed a tab',
  search_browser_history: 'Searched your history', save_links: 'Saved links to a file',
  list_folder: 'Looked in a folder', read_file: 'Read a file', find_files: 'Found files',
  write_text_file: 'Wrote a file', save_report: 'Saved a report', create_spreadsheet: 'Made a spreadsheet',
  edit_text_file: 'Edited a file',
  list_windows: 'Checked open windows', focus_window: 'Switched window', launch_app: 'Opened an app',
  look_at_window: 'Looked at a window', click_control: 'Clicked in an app', type_into: 'Typed in an app',
  type_text: 'Typed in an app', press_keys: 'Pressed keys', read_control: 'Read from an app',
  take_screenshot: 'Took a screenshot', describe_screen: 'Looked at the screen', click_at: 'Clicked on the screen',
};
const TOOL_ASK = {
  web_search: 'Search the web', open_url: 'Open a page', save_links: 'Save links to a file', click_button: 'Click a button',
  search_browser_history: 'Search your browsing history',
  launch_app: 'Open an app', click_control: 'Click in an app', type_into: 'Type in an app', type_text: 'Type in an app',
  press_keys: 'Press keys', click_at: 'Click on the screen',
  write_text_file: 'Write a file', save_report: 'Save a report', create_spreadsheet: 'Make a spreadsheet',
  edit_text_file: 'Edit a file',
};
const OUTCOME = {
  verified: ['Done', 'ok', 'check'], done_unverified: ['Done, not checked', 'warn-done', 'check'],
  failed: ['Failed', 'bad', 'x'], rejected: ['Rejected', 'bad', 'x'], denied: ['Not allowed', 'bad', 'x'],
};

const state = {
  backend: { state: 'starting', message: 'Starting' },
  settings: null,
  modelReady: false,
  busy: false,
  view: 'home',
  currentTaskId: null,
  run: null,
  draftFolders: [],
  brain: null,
  brainTimer: null,
};

function el(tag, opts = {}, children = []) {
  const node = document.createElement(tag);
  if (opts.className) node.className = opts.className;
  if (opts.text !== undefined) node.textContent = opts.text;
  if (opts.attrs) for (const [k, v] of Object.entries(opts.attrs)) node.setAttribute(k, v);
  for (const child of children) if (child) node.append(child);
  return node;
}

function icon(name) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('aria-hidden', 'true');
  const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
  use.setAttribute('href', `#i-${name}`);
  svg.append(use);
  return svg;
}

function setChip(id, chipState, text, title) {
  const chip = $(id);
  chip.dataset.state = chipState;
  chip.querySelector('.pill-text').textContent = text;
  chip.title = title || text;
}

function timeAgo(iso) {
  const d = new Date(iso);
  const mins = Math.round((Date.now() - d.getTime()) / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins} min ago`;
  if (mins < 60 * 24 && d.getDate() === new Date().getDate()) return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  return d.toLocaleDateString([], { day: 'numeric', month: 'short' }) + ', ' + d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}

// ---------- Views ----------
function showView(view) {
  state.view = view;
  document.body.dataset.view = view;
  $('home').hidden = view !== 'home';
  $('task-view').hidden = view !== 'task';
  renderReady();
}

function goHome() {
  stopWatching();
  state.currentTaskId = null;
  showView('home');
  markHistorySelection();
  $('task-input').focus();
}

// ---------- Errors ----------
function showError(error, fallback = 'Something went wrong.') {
  const e = (error && error.error) || error || {};
  $('error-title').textContent = e.message || fallback;
  $('error-hint').textContent = e.hint || '';
  $('error-details').replaceChildren(...(e.details || []).map((d) => el('li', { text: d })));
  $('error-banner').hidden = false;
}
function clearError() {
  $('error-banner').hidden = true;
}

// ---------- Status ----------
function applyBackendStatus(status) {
  if (!status) return;
  const was = state.backend.state;
  state.backend = status;
  const label = status.state === 'ready' ? 'Agent running' : status.state === 'failed' ? 'Agent stopped' : 'Starting';
  setChip('backend-pill', status.state, label, [status.message, status.detail].filter(Boolean).join('\n'));
  updateButtons();
  if (status.state === 'ready' && was !== 'ready') {
    loadSettings();
    loadBrain();
    loadHistory();
    resumeRunningTask();
  } else if (status.state === 'failed') {
    setChip('model-pill', 'unknown', 'Model unknown');
    showError({ message: status.message, hint: status.detail || 'Click "Agent stopped" to try again.' });
  }
}

async function refreshModelStatus() {
  const res = await api.api('GET', '/models/status');
  if (!res.ok) {
    setChip('model-pill', 'failed', 'Brain unavailable', res.body?.error?.message);
    state.modelReady = false;
  } else {
    const s = res.body;
    state.modelReady = s.model_available;
    const mode = s.mode;
    if (s.model_available) setChip('model-pill', 'ready', mode === 'custom' ? s.model : 'Brain ready', s.message);
    else if (!s.server_reachable) setChip('model-pill', 'failed', 'Brain not running', s.message);
    else setChip('model-pill', 'missing', 'Getting ready', s.message);
  }
  renderContext();
}

// ---------- Brain (built-in) ----------
function fmtGB(bytes) {
  return (bytes / 1024 ** 3).toFixed(1);
}

async function loadBrain() {
  const res = await api.api('GET', '/brain');
  if (!res.ok) return;
  state.brain = res.body;
  renderReady();
  renderBrainSettings();
  refreshModelStatus();
  clearTimeout(state.brainTimer);
  const b = state.brain;
  if (b.mode === 'builtin' && !b.builtin.ready) state.brainTimer = setTimeout(loadBrain, 1500);
}

function renderReady() {
  const card = $('ready-card');
  const b = state.brain;
  const info = b && b.builtin;
  if (!b || b.mode !== 'builtin' || !info || info.ready) {
    card.hidden = true;
    return;
  }
  const think = info.roles.think;
  const actions = [];
  $('ready-meter').hidden = true;
  if (info.ollama_reachable === false) {
    $('ready-title').textContent = "Claw's brain isn't running";
    $('ready-detail').textContent = 'Close Claw from the tray and open it again. If this keeps happening, reinstall Claw.';
  } else if (think.status === 'downloading') {
    const pct = Math.round(think.progress * 100);
    $('ready-title').textContent = `Setting up Claw's brain · ${pct}%`;
    $('ready-detail').textContent = 'This happens once. Keep Claw open.';
    $('ready-meter').hidden = false;
    $('ready-bar').style.width = `${pct}%`;
  } else if (think.status === 'failed') {
    $('ready-title').textContent = "Claw's brain could not be set up";
    $('ready-detail').textContent = think.error || 'Try again.';
    const retry = el('button', { className: 'btn btn-primary btn-sm', text: 'Try again', attrs: { type: 'button' } });
    retry.addEventListener('click', async () => {
      await api.api('POST', '/models/auto/retry');
      loadBrain();
    });
    actions.push(retry);
  } else {
    $('ready-title').textContent = 'Getting Claw ready';
    $('ready-detail').textContent = 'Checking this computer and starting the brain.';
  }
  $('ready-actions').replaceChildren(...actions);
  card.hidden = false;
}

function renderBrainSettings() {
  const b = state.brain;
  if (!b) return;
  const info = b.builtin || {};
  const think = info.roles && info.roles.think;
  $('brain-summary').textContent = b.mode === 'custom'
    ? 'Using a developer model server.'
    : `Claw's built-in brain, sized for this computer (${info.hardware_text || 'this computer'})${think && think.model ? `: ${think.model}` : ''}. It runs entirely on this computer.`;
}

function renderContext() {
  const mode = state.settings?.model?.mode;
  const m = mode === 'custom' ? state.settings?.model?.model : 'Built-in brain';
  const folders = state.settings?.permissions?.authorized_folders || [];
  const mc = $('ctx-model');
  mc.querySelector('span').textContent = state.modelReady ? m : `${m} · getting ready`;
  mc.dataset.ok = String(!!m && state.modelReady);
  const fc = $('ctx-folder');
  fc.querySelector('span').textContent = folders.length ? folders[0].split(/[\\/]/).filter(Boolean).pop() + (folders.length > 1 ? ` +${folders.length - 1}` : '') : 'No folder to save in';
  fc.title = folders.join('\n');
  fc.dataset.ok = String(folders.length > 0);
}

function isRunning() {
  return !!(state.run && ACTIVE.has(state.run.status));
}

function updateButtons() {
  const text = $('task-input').value.trim();
  const blocked = state.busy || state.backend.state !== 'ready' || text.length < 3;
  $('plan-btn').disabled = blocked;
  $('run-btn').disabled = blocked;
  $('plan-btn').textContent = state.busy ? 'Planning…' : 'Plan only';
}

// ---------- Plan only ----------
async function planTask() {
  const task = $('task-input').value.trim();
  if (task.length < 3 || state.busy) return;
  clearError();
  state.busy = true;
  updateButtons();
  const res = await api.api('POST', '/tasks/plan', { task });
  state.busy = false;
  updateButtons();
  if (res.ok) {
    $('task-input').value = '';
    updateButtons();
    renderPlanOnly(res.body);
  } else {
    showError(res.body, 'Claw could not plan that task.');
  }
  loadHistory();
  refreshModelStatus();
}

function renderPlanOnly(task) {
  stopWatching();
  state.currentTaskId = task.id;
  showView('task');
  $('run-title').textContent = task.task_text;
  setState(task.status);
  $('run-when').textContent = timeAgo(task.created_at);
  $('stop-btn').hidden = true;
  $('approval-card').hidden = true;
  $('activity').replaceChildren();
  $('run-summary').hidden = true;
  renderPlan(task, false);
  $('results').open = true;
  renderAudit(task.events || []);
  markHistorySelection();
}

function setState(status) {
  const [label, tone] = STATUS[status] || [status, 'muted'];
  $('run-status').textContent = label;
  $('run-status').dataset.tone = tone;
}

function renderPlan(task, runMode) {
  const plan = task.plan;
  $('results').hidden = !plan && runMode;
  $('plan-summary-label').textContent = runMode ? 'The plan Claw started from' : 'Plan';
  $('plan-status').textContent = !runMode && plan ? `${plan.steps.length} steps` : '';
  $('plan-goal').textContent = plan ? plan.goal : task.task_text;
  $('plan-notice').textContent = !plan
    ? `No plan was produced. ${task.error || ''}`.trim()
    : runMode
      ? 'What actually happened is shown above.'
      : 'Nothing has been done yet. Start the task to have Claw carry it out.';
  $('plan-steps').replaceChildren(
    ...(plan?.steps || []).map((step) => {
      const [permText, permClass] = PERMISSION_TEXT[step.permission] || [step.permission, ''];
      const meta = el('p', { className: 'plan-step-meta' }, [
        document.createTextNode(`${CAPABILITY_LABEL[step.capability] || step.capability} · ${RISK_LABEL[step.risk] || step.risk} · `),
        el('span', { className: permClass, text: permText }),
      ]);
      return el('li', { className: 'plan-step' }, [el('p', { className: 'plan-step-desc', text: step.description }), meta]);
    }),
  );
  const questions = plan?.questions || [];
  $('plan-questions').hidden = questions.length === 0;
  $('plan-questions').querySelector('ul').replaceChildren(...questions.map((q) => el('li', { text: q })));
}

function renderAudit(events) {
  $('plan-events').replaceChildren(
    ...events.map((e) => {
      const time = new Date(e.ts).toLocaleTimeString();
      const d = e.data || {};
      const extra = d.message || d.detail || d.tool || d.model || (d.steps !== undefined ? `${d.steps} steps` : '');
      return el('li', { text: `${time}  ${e.kind}${extra ? ' — ' + extra : ''}` });
    }),
  );
}

// ---------- Running tasks ----------
async function runTask(taskText) {
  const task = (taskText ?? $('task-input').value).trim();
  if (task.length < 3 || state.busy) return;
  clearError();
  const res = await api.api('POST', '/tasks/run', { task });
  if (!res.ok) {
    showError(res.body, 'The task could not be started.');
    return;
  }
  $('task-input').value = '';
  updateButtons();
  startWatching(res.body.id, task);
  loadHistory();
}

function startWatching(id, title) {
  stopWatching();
  state.run = { id, title, after: 0, events: [], status: 'created', timer: null, approvals: [], createdAt: null };
  state.currentTaskId = id;
  showView('task');
  $('run-title').textContent = title;
  $('run-when').textContent = '';
  setState('created');
  $('activity').replaceChildren();
  $('run-summary').hidden = true;
  $('approval-card').hidden = true;
  $('results').hidden = true;
  $('results').open = false;
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
  if (state.run !== run) return;
  if (res.ok) {
    for (const e of res.body.events) {
      run.events.push(e);
      run.after = Math.max(run.after, e.id);
    }
    const changed = run.status !== res.body.status;
    run.status = res.body.status;
    run.approvals = res.body.approvals;
    renderRun(res.body);
    if (changed && !ACTIVE.has(run.status)) {
      loadHistory();
      refreshModelStatus();
    }
  }
  if (ACTIVE.has(run.status)) run.timer = setTimeout(pollRun, 600);
}

function formatArgValue(v) {
  if (typeof v === 'string') return v;
  if (Array.isArray(v) && v.every((x) => x && typeof x === 'object' && 'url' in x)) {
    return v.map((x) => `${x.title || x.url}\n${x.url}${x.note ? `\n${x.note}` : ''}`).join('\n\n');
  }
  return JSON.stringify(v, null, 1);
}

function describeArgs(args) {
  return Object.entries(args || {})
    .filter(([, v]) => v !== null && v !== '')
    .map(([, v]) => (typeof v === 'string' ? v : Array.isArray(v) ? `${v.length} item(s)` : JSON.stringify(v)))
    .join(' · ');
}

function collectSteps(events) {
  const steps = new Map();
  const notes = [];
  for (const e of events) {
    const d = e.data || {};
    if (e.kind === 'planned') notes.push({ at: e.id, text: `Made a plan with ${d.steps} step(s)` });
    if (e.kind === 'model_reply_rejected') notes.push({ at: e.id, text: "Claw's reply wasn't usable, so it tried again" });
    if (e.kind === 'replanned') notes.push({ at: e.id, text: `Changed approach: ${d.diagnosis}` });
    if (e.kind === 'injection_warning') notes.push({ at: e.id, text: 'Something Claw read tried to give it orders. Claw ignored it and will ask before any change.', warn: true });
    if (d.step === undefined) continue;
    const row = steps.get(d.step) || { at: e.id, step: d.step, tool: d.tool, args: null, outcome: null, detail: '', waiting: false, attempts: 0 };
    if (e.kind === 'requested') Object.assign(row, { tool: d.tool, args: d.args });
    if (e.kind === 'awaiting_approval') row.waiting = true;
    if (e.kind === 'approved') row.waiting = false;
    if (e.kind === 'attempted') row.attempts = d.attempt;
    if (e.kind === 'retrying') row.detail = `Trying again: ${d.reason}`;
    if (OUTCOME[e.kind]) {
      row.outcome = e.kind;
      row.waiting = false;
      row.detail = d.detail || d.reason || (e.kind === 'denied' ? (d.by === 'settings' ? 'Your settings do not allow this.' : d.by === 'timeout' ? 'No answer in time.' : 'You chose not to allow it.') : '');
    }
    steps.set(d.step, row);
  }
  return [...notes.map((n) => ({ ...n, note: true })), ...steps.values()].sort((a, b) => a.at - b.at);
}

function renderRun(body) {
  const run = state.run;
  setState(run.status);
  if (!run.createdAt && run.events[0]) {
    run.createdAt = run.events[0].ts;
  }
  $('run-when').textContent = run.createdAt ? timeAgo(run.createdAt) : '';
  $('stop-btn').hidden = !ACTIVE.has(run.status);

  const items = collectSteps(run.events).map((row) => {
    if (row.note) {
      return el('li', { className: 'tl-item', attrs: { 'data-kind': 'note', 'data-tone': row.warn ? 'warn-note' : '' } }, [
        el('span', { className: 'tl-node' }),
        el('div', {}, [el('p', { className: 'tl-title', text: row.text })]),
      ]);
    }
    let label, tone, glyph;
    if (row.outcome) [label, tone, glyph] = OUTCOME[row.outcome];
    else if (row.waiting) [label, tone, glyph] = ['Waiting for you', 'warn', null];
    else [label, tone, glyph] = ['Working', 'live', null];
    const title = row.outcome || row.attempts ? TOOL_LABEL[row.tool] || row.tool : TOOL_ASK[row.tool] || TOOL_LABEL[row.tool] || row.tool;
    return el('li', { className: 'tl-item', attrs: { 'data-tone': tone } }, [
      el('span', { className: 'tl-node' }, glyph ? [icon(glyph)] : []),
      el('div', {}, [
        el('p', { className: 'tl-title', text: title || 'Unknown action' }),
        el('p', { className: 'tl-detail', text: row.detail || describeArgs(row.args) }),
      ]),
      el('span', { className: 'tl-tag', text: label }),
    ]);
  });
  $('activity').replaceChildren(...items);

  const appr = (run.approvals || [])[0];
  const card = $('approval-card');
  if (appr) {
    const firstShow = card.hidden || card.dataset.id !== appr.id;
    card.dataset.id = appr.id;
    $('approval-title').textContent = `Allow Claw to ${(TOOL_ASK[appr.tool] || appr.tool).toLowerCase()}?`;
    $('approval-risk').textContent = appr.sensitive_scope === 'browser_history' ? 'Private data' : RISK_LABEL[appr.risk] || appr.risk;
    $('approval-desc').textContent = appr.description;
    $('approval-args').replaceChildren(
      ...Object.entries(appr.args || {})
        .filter(([, v]) => v !== null && v !== undefined && v !== '')
        .flatMap(([k, v]) => [el('dt', { text: k.replace(/_/g, ' ') }), el('dd', { text: formatArgValue(v) })]),
    );
    $('approval-reason').textContent = [appr.caution, appr.reason ? `Why: ${appr.reason}` : ''].filter(Boolean).join(' ');
    card.hidden = false;
    $('approve-btn').disabled = false;
    $('deny-btn').disabled = false;
    if (firstShow) $('approve-btn').focus();
  } else {
    card.hidden = true;
  }

  if (body.plan) {
    renderPlan({ plan: body.plan, task_text: run.title, error: body.error }, true);
  }
  renderAudit(run.events);

  const done = !ACTIVE.has(run.status);
  $('run-summary').hidden = !done;
  if (done) {
    const c = (body.result && body.result.counts) || {};
    const parts = [
      c.verified ? `${c.verified} done and checked` : '',
      c.done_unverified ? `${c.done_unverified} done, not checked` : '',
      c.failed ? `${c.failed} failed` : '',
      c.rejected ? `${c.rejected} rejected` : '',
      c.denied ? `${c.denied} not allowed` : '',
    ].filter(Boolean);
    $('summary-counts').textContent = parts.length ? parts.join(', ') : 'No steps were carried out';
    $('summary-error').textContent = body.error || '';
    const answer = body.result && body.result.final_answer;
    $('summary-answer-wrap').hidden = !answer;
    $('summary-answer').textContent = answer || '';
    renderFiles(run.id, (body.result && body.result.files) || []);
    const warnings = (body.result && body.result.warnings) || [];
    $('summary-warnings').hidden = warnings.length === 0;
    $('summary-warnings').replaceChildren(...warnings.map((w) => el('p', { text: w })));
  }
  $('run-again').hidden = !done;
}

const FILE_KIND = { report: 'Report', spreadsheet: 'Spreadsheet', text: 'File', links: 'Saved links', edited: 'Edited file' };

function renderFiles(taskId, files) {
  const box = $('summary-files');
  box.hidden = files.length === 0;
  const items = files.map((f) => {
    const name = f.path.split(/[\\/]/).pop();
    const open = el('button', { className: 'btn btn-quiet btn-sm', text: 'Open', attrs: { type: 'button' } });
    const show = el('button', { className: 'btn btn-quiet btn-sm', text: 'Show in folder', attrs: { type: 'button' } });
    const say = async (how) => {
      const r = await api.openOutput(taskId, f.path, how);
      if (!r || !r.ok) showError({ message: (r && r.message) || 'The file could not be opened.' });
    };
    open.addEventListener('click', () => say('open'));
    show.addEventListener('click', () => say('show'));
    return el('li', { className: 'file-row' }, [
      el('div', { className: 'file-text' }, [
        el('p', { className: 'file-name', text: name, attrs: { title: f.path } }),
        el('p', { className: 'file-meta', text: `${FILE_KIND[f.kind] || 'File'}${f.verified ? ' · checked' : ' · not checked'}` }),
        f.note ? el('p', { className: 'file-note', text: f.note }) : null,
      ]),
      el('div', { className: 'file-actions' }, [open, show]),
    ]);
  });
  $('files-list').replaceChildren(...items);
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
    const t = await api.api('GET', `/tasks/${res.body.current_id}`);
    startWatching(res.body.current_id, t.ok ? t.body.task_text : 'Running task');
  }
}

// ---------- History ----------
let historyTimer = null;
async function loadHistory() {
  if (state.backend.state !== 'ready') return;
  const q = $('history-search').value.trim();
  const route = q ? `/tasks?q=${encodeQuery(q)}&limit=100` : '/tasks?limit=100';
  const res = await api.api('GET', route);
  if (!res.ok) return;
  const groups = new Map();
  const today = new Date().toDateString();
  const yesterday = new Date(Date.now() - 864e5).toDateString();
  for (const t of res.body.tasks) {
    const day = new Date(t.created_at).toDateString();
    const label = day === today ? 'Today' : day === yesterday ? 'Yesterday' : 'Earlier';
    if (!groups.has(label)) groups.set(label, []);
    groups.get(label).push(t);
  }
  const sections = [...groups.entries()].map(([label, tasks]) =>
    el('section', { className: 'history-group' }, [
      el('h3', { text: label }),
      ...tasks.map((t) => {
        const [statusText, tone] = STATUS[t.status] || [t.status, 'muted'];
        const btn = el('button', { className: 'history-item', attrs: { type: 'button', 'data-id': t.id, 'data-tone': tone } }, [
          el('span', { className: 'h-dot' }),
          el('span', { className: 'h-text', text: t.task_text }),
          el('span', { className: 'h-sub', text: `${statusText} · ${timeAgo(t.created_at)}` }),
        ]);
        btn.addEventListener('click', () => openTask(t.id));
        return btn;
      }),
    ]),
  );
  $('history-list').replaceChildren(...sections);
  $('history-empty').hidden = res.body.tasks.length > 0;
  $('history-empty').textContent = q ? 'No tasks match that search.' : 'Tasks you give Claw are kept here.';
  markHistorySelection();
}

function encodeQuery(q) {
  return encodeURIComponent(q).replace(/[!'()*~]/g, (c) => '%' + c.charCodeAt(0).toString(16).toUpperCase());
}

function markHistorySelection() {
  for (const b of document.querySelectorAll('#history-list .history-item')) {
    b.setAttribute('aria-current', b.dataset.id === state.currentTaskId ? 'true' : 'false');
  }
}

async function openTask(id) {
  const res = await api.api('GET', `/tasks/${id}`);
  if (!res.ok) return showError(res.body);
  clearError();
  const task = res.body;
  if (task.status === 'planned' || (task.status === 'failed' && !task.events.some((e) => e.kind === 'requested_task'))) {
    renderPlanOnly(task);
  } else {
    startWatching(task.id, task.task_text);
  }
}

// ---------- Settings ----------
async function loadSettings() {
  const res = await api.api('GET', '/settings');
  if (!res.ok) return;
  state.settings = res.body.settings;
  $('data-dir').textContent = `Settings, history and logs are kept in ${res.body.data_dir}`;
  renderContext();
  if (res.body.error) {
    showError({ message: res.body.error.message, hint: 'Open Settings, correct them, and save.', details: res.body.error.details });
  }
}

const DEFAULT_URLS = { ollama: 'http://127.0.0.1:11434', openai_compatible: 'http://127.0.0.1:8080' };

function fillSettingsForm(s) {
  $('s-custom').checked = s.model.mode === 'custom';
  renderBrainSettings();
  $('s-provider').value = s.model.provider;
  $('s-base-url').value = s.model.base_url;
  $('s-model').value = s.model.model;
  $('s-timeout').value = s.model.request_timeout_s;
  $('s-temperature').value = s.model.temperature;
  $('s-remote').checked = !!s.model.allow_remote_server;
  for (const level of ['read_only', 'local_write', 'external', 'destructive']) $(`p-${level}`).value = s.permissions.modes[level];
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
  const d = s.desktop || {};
  $('d-quickbar').checked = d.show_quick_bar !== false;
  $('d-startup').checked = !!d.start_with_windows;
  $('d-awake').checked = d.keep_awake_while_running !== false;
  $('d-notify').checked = d.notifications !== false;
  $('d-tray').checked = d.close_to_tray !== false;
  state.draftFolders = [...s.permissions.authorized_folders];
  renderFolders();
  $('s-test-result').textContent = '';
  $('settings-error').hidden = true;
}

function readModelForm() {
  const mode = $('s-custom').checked ? 'custom' : 'builtin';
  return {
    mode,
    provider: $('s-provider').value,
    base_url: $('s-base-url').value.trim(),
    model: $('s-model').value.trim(),
    request_timeout_s: Number($('s-timeout').value),
    temperature: Number($('s-temperature').value),
    allow_remote_server: $('s-remote').checked,
  };
}

function readSettingsForm() {
  const prev = state.settings || {};
  return {
    version: 1,
    model: readModelForm(),
    permissions: {
      modes: Object.fromEntries(['read_only', 'local_write', 'external', 'destructive'].map((l) => [l, $(`p-${l}`).value])),
      authorized_folders: state.draftFolders,
    },
    browser: {
      ...(prev.browser || {}),
      channel: $('b-channel').value,
      headless: !$('b-visible').checked,
      search_engine: $('b-engine').value,
      custom_search_url: $('b-custom').value.trim(),
      history_access: $('b-history').value,
    },
    agent: { ...(prev.agent || {}), max_steps: Number($('a-max-steps').value), step_timeout_s: Number($('a-step-timeout').value) },
    desktop: {
      show_quick_bar: $('d-quickbar').checked,
      start_with_windows: $('d-startup').checked,
      keep_awake_while_running: $('d-awake').checked,
      notifications: $('d-notify').checked,
      close_to_tray: $('d-tray').checked,
    },
  };
}

function renderFolders() {
  const items = state.draftFolders.map((folder, i) => {
    const remove = el('button', { className: 'btn btn-quiet btn-sm', text: 'Remove', attrs: { type: 'button', 'aria-label': `Remove ${folder}` } });
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
  $('close-settings').focus();
}
function closeSettings() {
  $('settings').hidden = true;
  $('settings-scrim').hidden = true;
  if (lastFocus) lastFocus.focus();
}
function defaultSettings() {
  return {
    model: { mode: 'builtin', provider: 'ollama', base_url: DEFAULT_URLS.ollama, model: '', request_timeout_s: 120, temperature: 0.2, allow_remote_server: false },
    permissions: { modes: { read_only: 'allow', local_write: 'ask', external: 'ask', destructive: 'ask' }, authorized_folders: [] },
  };
}

async function testConnection() {
  const note = $('s-test-result');
  note.dataset.tone = '';
  note.textContent = 'Checking…';
  const res = await api.api('POST', '/models/probe', { ...readModelForm(), mode: 'custom' });
  if (!res.ok) {
    note.dataset.tone = 'bad';
    const e = res.body?.error || {};
    note.textContent = [e.message, ...(e.details || [])].filter(Boolean).join(' ');
    return;
  }
  const s = res.body;
  $('s-model-list').replaceChildren(...s.available_models.map((m) => el('option', { attrs: { value: m } })));
  note.dataset.tone = s.model_available ? 'ok' : 'bad';
  const listed = s.server_reachable && s.available_models.length ? ` Installed: ${s.available_models.join(', ')}.` : '';
  note.textContent = s.message + listed;
}

async function saveSettings() {
  const res = await api.api('PUT', '/settings', readSettingsForm());
  const box = $('settings-error');
  if (!res.ok) {
    const e = res.body?.error || {};
    box.replaceChildren(
      el('div', { className: 'banner-body' }, [
        el('strong', { text: e.message || 'Settings could not be saved.' }),
        el('ul', {}, (e.details || []).map((d) => el('li', { text: d }))),
      ]),
    );
    box.hidden = false;
    box.scrollIntoView({ block: 'nearest' });
    return;
  }
  state.settings = res.body.settings;
  clearError();
  closeSettings();
  loadBrain();
}

// ---------- Wiring ----------
function wire() {
  const input = $('task-input');
  input.addEventListener('input', updateButtons);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      runTask();
    }
  });
  $('plan-btn').addEventListener('click', planTask);
  $('run-btn').addEventListener('click', () => runTask());
  $('stop-btn').addEventListener('click', stopRun);
  $('run-again').addEventListener('click', () => {
    if (state.run && !isRunning()) runTask(state.run.title);
  });
  $('approve-btn').addEventListener('click', () => answerApproval(true));
  $('deny-btn').addEventListener('click', () => answerApproval(false));
  $('new-task').addEventListener('click', goHome);
  for (const idea of document.querySelectorAll('.idea')) {
    idea.addEventListener('click', () => {
      input.value = idea.textContent;
      updateButtons();
      input.focus();
    });
  }
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
  $('b-engine').addEventListener('change', () => {
    $('b-custom-wrap').hidden = $('b-engine').value !== 'custom';
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
    applyBackendStatus({ state: 'starting', message: 'Restarting' });
    applyBackendStatus(await api.restartBackend());
  });
  $('model-pill').addEventListener('click', () => {
    if ($('model-pill').dataset.state !== 'ready') openSettings();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !$('settings').hidden) closeSettings();
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'n') {
      e.preventDefault();
      goHome();
    }
  });

  api.onBackendStatus(applyBackendStatus);
  api.backendStatus().then(applyBackendStatus);
  api.onTaskStarted(({ id }) => {
    loadHistory();
    if (state.view === 'home' || !isRunning()) openTask(id);
  });
  api.onNavigate((route) => {
    if (route && route.taskId) openTask(route.taskId);
  });
  api.onAgentStatus((s) => {
    if (s && s.phase === 'idle') loadHistory();
  });
  api.shortcut().then((k) => {
    $('new-task-kbd').textContent = 'Ctrl N';
    $('home-hint').textContent = k ? `Tip: press ${k.replace(/\+/g, ' + ')} anywhere in Windows to give Claw a task from the quick bar.` : '';
    $('shortcut-note').textContent = k ? `Open the quick bar from anywhere with ${k.replace(/\+/g, ' + ')}.` : '';
  });
  input.focus();
}

wire();
