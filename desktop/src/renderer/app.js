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
  read_document_pages: 'Read document pages', search_document: 'Searched a document', summarize_document: 'Summarized a document',
  make_searchable_pdf: 'Saved a searchable PDF', check_whatsapp: 'Checked WhatsApp', send_whatsapp_message: 'Sent a WhatsApp message',
  make_flyer: 'Made a flyer', edit_image: 'Edited a picture', inspect_image: 'Checked a picture',
  fill_field: 'Filled in a form field', download_file: 'Downloaded a file', copy_files: 'Copied files',
  check_file: 'Checked a file', scroll: 'Scrolled', choose_menu: 'Chose a menu item', wait_for_window: 'Waited for a window',
};
const TOOL_ASK = {
  web_search: 'Search the web', open_url: 'Open a page', save_links: 'Save links to a file', click_button: 'Click a button',
  search_browser_history: 'Search your browsing history',
  launch_app: 'Open an app', click_control: 'Click in an app', type_into: 'Type in an app', type_text: 'Type in an app',
  press_keys: 'Press keys', click_at: 'Click on the screen',
  write_text_file: 'Write a file', save_report: 'Save a report', create_spreadsheet: 'Make a spreadsheet',
  edit_text_file: 'Edit a file', make_searchable_pdf: 'Save a searchable copy of a PDF',
  check_whatsapp: 'Check your WhatsApp chats', send_whatsapp_message: 'Send a WhatsApp message',
  make_flyer: 'Make a flyer', edit_image: 'Save an edited picture',
  fill_field: 'Fill in a form field', download_file: 'Download a file', copy_files: 'Copy files', choose_menu: 'Choose a menu item',
};
const OUTCOME = {
  verified: ['Done', 'ok', 'check'], done_unverified: ['Done, not checked', 'warn-done', 'check'],
  failed: ['Failed', 'bad', 'x'], rejected: ['Rejected', 'bad', 'x'], denied: ['Not allowed', 'bad', 'x'],
};

const state = {
  backend: { state: 'starting', message: 'Starting' },
  settings: null,
  // Which edition this install is. One app, two packaging profiles: the page hides
  // what this build cannot do instead of offering it and failing afterwards.
  edition: null,
  modelReady: false,
  busy: false,
  view: 'home',
  theme: 'system',
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
  $('docs-view').hidden = view !== 'docs';
  $('open-docs').setAttribute('aria-current', view === 'docs' ? 'true' : 'false');
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

// One place decides what the status chip says, from the backend's single answer.
// The wording follows the mode: "Brain not running" is nonsense when the user chose a
// hosted model and their key was refused, and it sent people to look at the wrong thing.
function describeModelStatus(s) {
  const online = s.mode !== 'builtin';
  if (s.model_available) return ['ready', online ? (s.model || 'Online model ready') : 'Brain ready'];
  switch (s.reason) {
    case 'auth_failed':    return ['failed', 'API key refused'];
    case 'rate_limited':   return ['missing', 'Rate limited'];
    case 'model_missing':  return ['failed', online ? 'Model not available' : 'Brain not installed'];
    case 'not_configured': return ['missing', online ? 'No model chosen' : 'No brain chosen'];
    case 'unreachable':    return ['failed', online ? 'Service unreachable' : 'Brain not running'];
    default:
      if (!s.server_reachable) return ['failed', online ? 'Service unreachable' : 'Brain not running'];
      return ['missing', online ? 'Not ready' : 'Getting ready'];
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
    const [chipState, label] = describeModelStatus(s);
    setChip('model-pill', chipState, label, s.message);
  }
  renderContext();
}

// ---------- Brain (built-in, runs on this computer with llama.cpp) ----------
function fmtGB(bytes) {
  return (bytes / 1024 ** 3).toFixed(1);
}

const DL_BUSY = new Set(['resolving', 'downloading', 'verifying']);

async function loadBrain() {
  const res = await api.api('GET', '/brain');
  if (!res.ok) return;
  state.brain = res.body;
  renderReady();
  renderBrainSettings();
  refreshModelStatus();
  clearTimeout(state.brainTimer);
  const b = state.brain;
  const loading = b.engine && b.engine.state === 'starting';
  if (b.mode === 'builtin' && (DL_BUSY.has(b.download.status) || loading)) state.brainTimer = setTimeout(loadBrain, 1000);
}

function brainAction(label, primary, fn) {
  const btn = el('button', { className: `btn ${primary ? 'btn-primary' : 'btn-quiet'} btn-sm`, text: label, attrs: { type: 'button' } });
  btn.addEventListener('click', async () => {
    btn.disabled = true;
    try {
      await fn();
    } finally {
      btn.disabled = false;
    }
  });
  return btn;
}

async function brainCall(route, body, okNote) {
  const res = await api.api('POST', route, body);
  const note = $('brain-note');
  if (!res.ok) {
    const e = res.body?.error || {};
    note.dataset.tone = 'bad';
    note.textContent = [e.message || 'That did not work.', e.hint].filter(Boolean).join(' ');
    showBrainProblem(e);
  } else {
    note.dataset.tone = 'ok';
    note.textContent = res.body.message || okNote || '';
  }
  await loadBrain();
  return res;
}

function showBrainProblem(e) {
  if (state.view !== 'home') return;
  showError({ message: e.message || "Claw's brain had a problem.", hint: e.hint });
}

function startDownload(entry) {
  return brainCall('/brain/download', { id: entry.id }, `Downloading the ${entry.name}…`);
}

function renderReady() {
  const card = $('ready-card');
  const b = state.brain;
  if (!b || b.mode !== 'builtin' || b.ready || state.view === 'docs') {
    card.hidden = !b || b.mode !== 'builtin' || !DL_BUSY.has(b?.download?.status) || state.view === 'docs';
    if (!card.hidden) fillDownloadCard(b);
    return;
  }
  const actions = [];
  $('ready-meter').hidden = true;
  const rec = b.catalog.find((e) => e.id === b.recommended) || b.catalog[0];
  if (!b.engine.available) {
    $('ready-title').textContent = "Claw's AI engine is missing";
    $('ready-detail').textContent = `${b.engine.message} Reinstall Claw to repair it.`;
  } else if (DL_BUSY.has(b.download.status)) {
    fillDownloadCard(b);
    return;
  } else {
    const failed = b.download.status === 'failed' ? `${b.download.message} ` : '';
    $('ready-title').textContent = failed ? "The brain download didn't finish" : 'Give Claw a brain';
    $('ready-detail').textContent = failed
      ? `${failed}You can try again; it continues where it stopped.`
      : `Claw thinks on this computer, so it needs its brain once: the ${rec.name} (about ${rec.approx_download_gb} GB from Hugging Face; its licence is checked before downloading). After that, nothing you do is sent anywhere.`;
    actions.push(brainAction(failed ? 'Try again' : `Download ${rec.name} · ${rec.approx_download_gb} GB`, true, () => startDownload(rec)));
    actions.push(brainAction('Use a GGUF file I have', false, importBrain));
  }
  $('ready-actions').replaceChildren(...actions);
  card.hidden = false;
}

function fillDownloadCard(b) {
  const d = b.download;
  const entry = b.catalog.find((e) => e.id === d.id);
  const pct = Math.floor(d.progress * 100);
  $('ready-title').textContent = d.status === 'verifying' ? 'Checking the download…' : d.status === 'resolving' ? 'Preparing the download…' : `Downloading ${entry ? entry.name : 'the brain'} · ${pct}%`;
  $('ready-detail').textContent = d.total_bytes
    ? `${fmtGB(d.done_bytes)} of ${fmtGB(d.total_bytes)} GB. This happens once. You can keep using your computer; if it stops, it continues where it left off.`
    : d.message || 'Contacting Hugging Face…';
  $('ready-meter').hidden = !d.total_bytes;
  $('ready-bar').style.width = `${pct}%`;
  $('ready-actions').replaceChildren(brainAction('Cancel', false, () => brainCall('/brain/download/cancel', {}, 'Download cancelled. It continues where it stopped next time.')));
  $('ready-card').hidden = false;
}

const ENGINE_TEXT = { stopped: 'Sleeping — starts when a task needs it', starting: 'Loading…', ready: 'Running', failed: 'Stopped with a problem' };

function renderBrainSettings() {
  const b = state.brain;
  if (!b) return;
  $('brain-summary').textContent = b.mode === 'custom'
    ? 'Using a developer model server (below). Switch it off to use the built-in brain.'
    : b.mode === 'cloud'
      ? 'Using a hosted model over the internet. The built-in brain is not running.'
      : `Runs entirely on this computer (${b.hardware_text}). No account, no key, nothing sent online.`;
  const eng = b.engine;
  const line = $('engine-line');
  line.dataset.state = !eng.available ? 'failed' : eng.state;
  line.textContent = !eng.available
    ? eng.message
    : `Engine: ${ENGINE_TEXT[eng.state] || eng.state}${eng.state === 'failed' && eng.message ? ` — ${eng.message}` : ''}`;

  const activeId = b.active && b.active.id;
  const rows = [];
  for (const e of b.catalog) {
    const installed = b.installed.find((m) => m.id === e.id && m.present);
    const tags = [
      e.recommended ? el('span', { className: 'tag tag-ok', text: 'Best for this computer' }) : null,
      !e.fits ? el('span', { className: 'tag tag-warn', text: `Needs ${e.min_ram_gb} GB memory` }) : null,
      activeId === e.id ? el('span', { className: 'tag tag-live', text: 'In use' }) : null,
    ];
    const meta = installed
      ? `${installed.kind === 'bundled' ? 'Came with Claw' : 'Downloaded'} · ${installed.size_gb} GB${installed.vision ? ' · can see screenshots' : ''}`
      : `About ${e.approx_download_gb} GB to download · ${e.repo} · licence checked before download`;
    const actions = [];
    if (installed && activeId !== e.id) actions.push(brainAction('Use this', true, () => brainCall('/brain/select', { id: e.id }, `Claw will use the ${e.name}.`)));
    if (!installed && !DL_BUSY.has(b.download.status)) {
      actions.push(brainAction('Download', !!e.recommended, async () => {
        if (!e.fits && !(await api.confirm(`The ${e.name} may be too big for this computer`, `It needs about ${e.min_ram_gb} GB of memory; this computer has ${b.hardware.total_ram_gb ?? '?'} GB. It may be very slow or fail to load.`, 'Download anyway'))) return;
        await startDownload(e);
      }));
    }
    if (installed && installed.kind === 'downloaded') {
      actions.push(brainAction('Remove', false, async () => {
        if (!(await api.confirm(`Remove the ${e.name}?`, `This deletes ${installed.size_gb} GB of brain files from this computer. You can download it again later.`, 'Remove'))) return;
        await brainCall('/brain/remove', { id: e.id });
      }));
    }
    rows.push(el('li', { className: 'brain', attrs: { 'data-active': String(activeId === e.id) } }, [
      el('div', { className: 'brain-text' }, [
        el('p', { className: 'brain-name' }, [document.createTextNode(e.name), ...tags.filter(Boolean)]),
        el('p', { className: 'brain-desc', text: e.description }),
        el('p', { className: 'brain-meta', text: meta }),
      ]),
      el('div', { className: 'brain-actions' }, actions),
    ]));
  }
  for (const m of b.installed.filter((m) => m.kind === 'imported')) {
    const actions = [];
    if (activeId !== m.id) actions.push(brainAction('Use this', true, () => brainCall('/brain/select', { id: m.id }, `Claw will use ${m.name}.`)));
    actions.push(brainAction('Forget', false, async () => {
      if (!(await api.confirm(`Stop using ${m.name}?`, 'Claw forgets this brain. Your file is not deleted.', 'Forget'))) return;
      await brainCall('/brain/remove', { id: m.id });
    }));
    rows.push(el('li', { className: 'brain', attrs: { 'data-active': String(activeId === m.id) } }, [
      el('div', { className: 'brain-text' }, [
        el('p', { className: 'brain-name' }, [document.createTextNode(m.name), activeId === m.id ? el('span', { className: 'tag tag-live', text: 'In use' }) : null].filter(Boolean)),
        el('p', { className: 'brain-meta', text: `Your file · ${m.size_gb} GB${m.present ? '' : ' · file is missing'}${m.vision ? ' · can see screenshots' : ''}`, attrs: { title: m.model_path } }),
      ]),
      el('div', { className: 'brain-actions' }, actions),
    ]));
  }
  $('brain-list').replaceChildren(...rows);

  const d = b.download;
  $('brain-dl').hidden = !DL_BUSY.has(d.status);
  if (DL_BUSY.has(d.status)) {
    const pct = Math.floor(d.progress * 100);
    $('brain-dl-text').textContent = d.total_bytes ? `Downloading · ${pct}% · ${fmtGB(d.done_bytes)} of ${fmtGB(d.total_bytes)} GB` : d.status === 'verifying' ? 'Checking the download…' : 'Preparing…';
    $('brain-dl-bar').style.width = `${pct}%`;
  } else if (d.status === 'failed' && !$('brain-note').textContent) {
    $('brain-note').dataset.tone = 'bad';
    $('brain-note').textContent = d.message;
  }
  $('brain-restart').disabled = !b.active || !eng.available;
}

async function importBrain() {
  const res = await api.importBrain();
  if (!res || res.cancelled) return;
  const note = $('brain-note');
  if (!res.ok) {
    const e = res.body?.error || {};
    note.dataset.tone = 'bad';
    note.textContent = e.message || 'That file could not be used.';
    showBrainProblem(e);
  } else {
    note.dataset.tone = 'ok';
    note.textContent = 'Claw will use your file. It starts the next time a task needs it.';
  }
  loadBrain();
}

function renderContext() {
  const mode = state.settings?.model?.mode;
  const m = mode === 'builtin' ? (state.brain?.active?.name || 'Built-in brain') : state.settings?.model?.model;
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

/* One character is a task. "hi" is two, and it is the first thing anyone types
   to find out whether the thing is alive - which the old minimum of three
   refused, through a disabled button that gave no reason. A button that will
   not press and will not say why reads as a broken program. Empty is still
   nothing to run. */
const MIN_TASK = 1;

function updateButtons() {
  const text = $('task-input').value.trim();
  const blocked = state.busy || state.backend.state !== 'ready' || text.length < MIN_TASK;
  $('plan-btn').disabled = blocked;
  $('run-btn').disabled = blocked;
  $('plan-btn').textContent = state.busy ? 'Planning…' : 'Plan only';
}

// ---------- Plan only ----------
async function planTask() {
  const task = $('task-input').value.trim();
  if (task.length < MIN_TASK || state.busy) return;
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
  if (task.length < MIN_TASK || state.busy) return;
  /* Claimed before the first await, not after it. This function read state.busy
     and never set it, so every press between the request leaving and the reply
     arriving started another task - which is how pressing Run again, or Try
     again, produced a pile of identical runs instead of one. The flag has to be
     taken synchronously; a guard on the far side of an await guards nothing. */
  state.busy = true;
  updateButtons();
  clearError();
  try {
    const res = await api.api('POST', '/tasks/run', { task });
    if (!res.ok) {
      showError(res.body, 'The task could not be started.');
      return;
    }
    $('task-input').value = '';
    startWatching(res.body.id, task);
    loadHistory();
  } finally {
    state.busy = false;
    updateButtons();
  }
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
  // A list of plain values is a sentence, not a document: ["enter"] took three
  // lines of pretty-printed JSON on the approval card, for one word.
  if (Array.isArray(v) && v.every((x) => typeof x === 'string' || typeof x === 'number')) {
    return v.join(', ');
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
    // Two different things wear this card. Asking permission to act is "allow or
    // deny". Asking the person to sign in, or type a code that was texted to them,
    // is not a permission question at all, and wording it as one makes people deny
    // it. The buttons change with it.
    const needsYou = appr.kind === 'needs_you';
    card.dataset.kind = needsYou ? 'needs-you' : 'approval';
    $('approval-title').textContent = needsYou
      ? appr.title || 'S-CLAW needs you'
      : `Allow Claw to ${(TOOL_ASK[appr.tool] || appr.tool).toLowerCase()}?`;
    $('approval-risk').textContent = needsYou
      ? (appr.what || 'over to you')
      : (appr.sensitive_scope ? 'Private data' : RISK_LABEL[appr.risk] || appr.risk);
    $('approval-desc').textContent = needsYou
      ? `Please ${appr.description}. S-CLAW will carry on from where it stopped. It never sees what you type.`
      : appr.description;
    $('approve-btn').textContent = needsYou ? 'I have done it' : 'Allow';
    $('deny-btn').textContent = needsYou ? 'Stop the task' : 'Deny';
    $('approval-args').replaceChildren(
      ...Object.entries(appr.args || {})
        .filter(([, v]) => v !== null && v !== undefined && v !== '')
        .flatMap(([k, v]) => [el('dt', { text: k.replace(/_/g, ' ') }), el('dd', { text: formatArgValue(v) })]),
    );
    $('approval-reason').textContent = needsYou
      ? (appr.detail ? `S-CLAW was: ${appr.detail}` : '')
      : [appr.caution, appr.reason ? `Why: ${appr.reason}` : ''].filter(Boolean).join(' ');
    $('approval-context').textContent = needsYou ? '' : (appr.context || '');
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

// ---------- Documents ----------
const doc = { job: null, timer: null, pagesLoaded: false };
const SOURCE_TEXT = { text: "From the file's text", ocr: 'Read from the scan', empty: 'No text' };
const STAGE_TEXT = { checking: 'Checking pages', ocr: 'Reading scanned pages', done: 'Finishing', searchable: 'Making the searchable copy' };

function openDocsView() {
  stopWatching();
  state.currentTaskId = null;
  markHistorySelection();
  showView('docs');
  clearError();
}

async function openDocument() {
  const res = await api.openDocument();
  if (!res || res.cancelled) return;
  if (!res.ok) return showDocError(res.body?.error?.message || 'That document could not be opened.');
  showDocJob(res.body);
}

function showDocError(message) {
  $('doc-card').hidden = false;
  $('doc-empty').hidden = true;
  $('doc-error').textContent = message;
}

function showDocJob(job) {
  clearTimeout(doc.timer);
  doc.job = job;
  doc.pagesLoaded = false;
  $('doc-empty').hidden = true;
  $('doc-card').hidden = false;
  $('doc-error').textContent = '';
  $('doc-pages').replaceChildren();
  $('doc-hits').replaceChildren();
  $('doc-hits').hidden = true;
  $('doc-q').value = '';
  $('doc-question').value = '';
  $('doc-ask-note').textContent = '';
  renderDoc();
  pollDoc();
}

async function pollDoc() {
  const job = doc.job;
  if (!job) return;
  const done = job.status !== 'reading';
  const res = await api.api('GET', `/documents/${job.id}${done ? '?pages=1' : ''}`);
  if (doc.job !== job) return;
  if (res.ok) {
    doc.job = res.body;
    if (res.body.pages) doc.pagesLoaded = true;
    renderDoc();
  }
  if (doc.job.status === 'reading' || (doc.job.status === 'done' && !doc.pagesLoaded)) doc.timer = setTimeout(pollDoc, doc.job.status === 'reading' ? 500 : 0);
}

function renderDoc() {
  const j = doc.job;
  $('doc-name').textContent = j.name;
  $('doc-name').title = j.path;
  const reading = j.status === 'reading';
  $('doc-cancel').hidden = !reading;
  $('doc-meter').hidden = !reading || !j.total;
  const pct = j.total ? Math.floor((100 * j.done) / j.total) : 0;
  $('doc-bar').style.width = `${pct}%`;
  const status = $('doc-status');
  status.dataset.tone = { done: 'ok', failed: 'bad', cancelled: 'muted', reading: 'live' }[j.status];
  if (reading) status.textContent = j.total ? `${STAGE_TEXT[j.stage] || 'Reading'} · ${j.done} of ${j.total}` : 'Opening…';
  else if (j.status === 'done') status.textContent = j.summary || 'Ready';
  else if (j.status === 'cancelled') status.textContent = 'Stopped. Open it again to read the rest.';
  else status.textContent = 'Could not be read';
  $('doc-error').textContent = j.status === 'failed' ? j.error : '';

  const ready = j.status === 'done';
  $('doc-tools').hidden = !ready;
  const isPdf = /\.pdf$/i.test(j.name);
  $('doc-save').hidden = !(ready && isPdf && j.counts && j.counts.ocr > 0);
  const flags = [];
  if (ready && j.ocr_available === false && j.ocr_note) flags.push(j.ocr_note);
  if (ready && j.problem_pages && j.problem_pages.length) {
    const n = j.problem_pages;
    flags.push(`Check ${n.length === 1 ? 'page' : 'pages'} ${n.join(', ')} yourself: the scan was unclear or could not be read, so the text there may be wrong or missing.`);
  }
  $('doc-flags').hidden = flags.length === 0;
  $('doc-flags').replaceChildren(...flags.map((f) => el('p', { text: f })));
  updateAskButton();
  if (ready && j.pages && !$('doc-pages').childElementCount) renderPages(j.pages);
}

function pageBadge(p) {
  if (p.source === 'ocr') {
    const conf = p.confidence != null ? ` · ${Math.round(p.confidence)}% sure` : '';
    return [`${SOURCE_TEXT.ocr}${conf}${p.rotation ? ` · turned ${p.rotation}°` : ''}`, p.status === 'low_confidence' ? 'warn' : p.status === 'failed' ? 'bad' : 'ocr'];
  }
  if (p.source === 'text') return [SOURCE_TEXT.text, 'ok'];
  return [p.status === 'failed' ? 'Could not be read' : SOURCE_TEXT.empty, p.status === 'failed' ? 'bad' : 'muted'];
}

function renderPages(pages) {
  $('doc-pages').replaceChildren(...pages.map((p) => {
    const [label, tone] = pageBadge(p);
    const body = p.text
      ? el('p', { className: 'page-text', text: p.text })
      : el('p', { className: 'page-text page-none', text: p.note || 'No text was found on this page.' });
    return el('li', { className: 'page', attrs: { id: `page-${p.number}`, 'data-tone': tone } }, [
      el('header', { className: 'page-head' }, [
        el('span', { className: 'page-no', text: `Page ${p.number}` }),
        el('span', { className: 'page-badge', text: label }),
      ]),
      p.note && p.text ? el('p', { className: 'page-note', text: p.note }) : null,
      body,
    ]);
  }));
}

let docSearchTimer = null;
async function searchDoc() {
  const q = $('doc-q').value.trim();
  const box = $('doc-hits');
  if (!doc.job || doc.job.status !== 'done' || q.length < 2) {
    box.hidden = true;
    return;
  }
  const res = await api.api('GET', `/documents/${doc.job.id}/search?q=${encodeQuery(q.slice(0, 120))}`);
  if (!res.ok) return;
  const hits = res.body.hits;
  box.hidden = false;
  if (!hits.length) {
    box.replaceChildren(el('li', { className: 'hit-none', text: 'Not found in this document.' }));
    return;
  }
  box.replaceChildren(...hits.slice(0, 30).map((h) => {
    const btn = el('button', { className: 'hit', attrs: { type: 'button' } }, [
      el('span', { className: 'hit-page', text: `Page ${h.page}${h.source === 'ocr' ? ' · scan' : ''}` }),
      el('span', { className: 'hit-snippet', text: h.snippet }),
    ]);
    btn.addEventListener('click', () => {
      const target = document.getElementById(`page-${h.page}`);
      if (target) {
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        target.classList.add('page-flash');
        setTimeout(() => target.classList.remove('page-flash'), 1200);
      }
    });
    return el('li', {}, [btn]);
  }));
}

function updateAskButton() {
  const q = $('doc-question').value.trim();
  $('doc-ask').disabled = !(doc.job && doc.job.status === 'done') || q.length < 3 || state.backend.state !== 'ready';
}

async function askAboutDoc() {
  const q = $('doc-question').value.trim();
  if (!doc.job || q.length < 3) return;
  const note = $('doc-ask-note');
  if (!state.modelReady) {
    note.textContent = "Claw's brain isn't ready yet, so it can't answer questions. Searching and reading still work.";
    return;
  }
  note.textContent = '';
  await runTask(`About the document "${doc.job.path}" (I opened it in Claw): ${q}`);
}


// ---------- WhatsApp ----------
function renderWhatsApp(status) {
  const r = status && status.result;
  const when = status && status.last_check_at; // successful checks only
  $('wa-when').textContent = when ? `Last successful check ${timeAgo(new Date(when * 1000).toISOString())}` : 'No successful check yet.';
  const note = $('wa-result');
  if (!r) {
    note.textContent = '';
    $('wa-list').replaceChildren();
    return;
  }
  note.dataset.tone = r.state === 'ok' ? 'ok' : 'bad';
  note.textContent = r.message;
  $('wa-list').replaceChildren(...(r.unread || []).map((c) => el('li', { className: 'wa-chat' }, [
    el('span', { className: 'wa-name', text: c.name }),
    c.new_since_last_check ? el('span', { className: 'tag tag-live', text: 'New' }) : null,
    el('span', { className: 'wa-count', text: c.unread == null ? 'Marked unread' : `${c.unread} unread` }),
    c.preview ? el('span', { className: 'wa-preview', text: c.preview }) : null,
  ].filter(Boolean))));
}

async function loadWhatsApp() {
  const res = await api.api('GET', '/messages/whatsapp');
  if (res.ok) renderWhatsApp(res.body);
}

async function checkWhatsAppNow() {
  const btn = $('wa-check');
  btn.disabled = true;
  $('wa-result').dataset.tone = '';
  $('wa-result').textContent = 'Checking WhatsApp…';
  const res = await api.api('POST', '/messages/whatsapp/check');
  btn.disabled = false;
  if (!res.ok) {
    $('wa-result').dataset.tone = 'bad';
    $('wa-result').textContent = res.body?.error?.message || 'The check did not work.';
    return;
  }
  loadWhatsApp();
}

// ---------- Settings ----------
async function loadSettings() {
  const res = await api.api('GET', '/settings');
  if (!res.ok) {
    // Returning quietly here leaves the page showing whatever it showed before
    // - which looks exactly like a setting that reverted on its own.
    showError(res.body, 'Your settings could not be read, so this page may be out of date.');
    return;
  }
  state.settings = res.body.settings;
  const desk = res.body.settings.desktop || {};
  applyTheme(desk.theme || 'system');
  showTips(desk.show_tips !== false && state.view === 'home');
  const ed = await api.api('GET', '/edition');
  if (ed.ok) applyEdition(ed.body);
  $('data-dir').textContent = `Settings, history and logs are kept in ${res.body.data_dir}`;
  renderContext();
  if (res.body.error) {
    showError({ message: res.body.error.message, hint: 'Open Settings, correct them, and save.', details: res.body.error.details });
  }
}

const DEFAULT_URLS = { ollama: 'http://127.0.0.1:11434', openai_compatible: 'http://127.0.0.1:8080' };

const KEY_KEPT = '__keep__';  // the backend's placeholder: "leave the saved key alone"

// ---------- Settings: one section at a time ----------
// Seven sections in one scrolling form meant everything was findable only by
// scrolling past everything else. The sections themselves are unchanged; the
// panel decides which one is on screen.
function settingsTabs() {
  return Array.from(document.querySelectorAll('.set-tab'));
}

function showSettingsPanel(id) {
  for (const tab of settingsTabs()) {
    const on = tab.dataset.panel === id;
    tab.setAttribute('aria-selected', on ? 'true' : 'false');
    const panel = $(tab.dataset.panel);
    if (panel) {
      panel.hidden = !on;
      panel.setAttribute('role', 'tabpanel');
      panel.setAttribute('aria-label', tab.textContent.trim());
    }
  }
  const panels = $('set-panels');
  if (panels) panels.scrollTop = 0;
}

function moveSettingsTab(from, step) {
  const tabs = settingsTabs();
  const next = tabs[(tabs.indexOf(from) + step + tabs.length) % tabs.length];
  showSettingsPanel(next.dataset.panel);
  next.focus();
}

// Each search provider asks for a different thing: nothing, a host, or a whole address.
function applySearchEngine() {
  const engine = $('b-engine').value;
  $('b-custom-wrap').hidden = engine !== 'custom';
  $('b-searxng-wrap').hidden = engine !== 'searxng';
}

// One quiet flash when a task finishes. Added, then removed so it can happen again.
function flashMark() {
  const mark = document.querySelector('.brand-mark');
  if (!mark) return;
  mark.classList.remove('is-done');
  void mark.offsetWidth;          // restart the animation rather than ignore it
  mark.classList.add('is-done');
  setTimeout(() => mark.classList.remove('is-done'), 1000);
}

function applyThinkMode() {
  const mode = $('s-think').value;
  $('cloud-box').hidden = mode !== 'cloud';
  $('service-box').hidden = mode !== 'service';
  $('brain-box').hidden = mode !== 'builtin';
  describeEdition();
}

// What this edition is, and what the choice above it actually means. The two have
// to be read together: a Claw Local install set to a hosted model does not work
// offline, and saying "works offline" under that choice would be a lie.
function describeEdition() {
  const ed = state.edition;
  const note = $('s-edition-note');
  if (!ed) { note.textContent = ''; return; }
  const mode = $('s-think').value;
  if (ed.online) {
    note.textContent = mode === 'service'
      ? `${ed.name}: Claw thinks on the Claw service, so this computer needs the internet. No brain is installed here.`
      : `${ed.name}: no brain is installed on this computer, and you have chosen a model of your own instead of the Claw service. The internet is still needed.`;
    return;
  }
  note.textContent = mode === 'builtin'
    ? `${ed.name}: Claw thinks on this computer and keeps working with the network switched off.`
    : `${ed.name}: this copy can think on this computer, but you have chosen a model elsewhere, so tasks will need the internet until you switch back.`;
}

function applyEdition(ed) {
  state.edition = ed;
  if (!ed) return;
  const modes = ed.modes || {};
  for (const option of $('s-think').options) {
    const allowed = modes[option.value] ? modes[option.value].allowed : true;
    option.hidden = !allowed;
    option.disabled = !allowed;
  }
  describeEdition();
  $('s-service-where').textContent = ed.service_configured
    ? `This copy is set up to use ${ed.service_url}`
    : (modes.service && modes.service.why_not) || 'No Claw service was built into this copy.';
  $('s-service-test').disabled = !ed.service_configured;
}

async function testServiceConnection() {
  const note = $('s-service-result');
  note.dataset.tone = '';
  note.textContent = 'Asking the Claw service to reply…';
  $('s-service-test').disabled = true;
  const res = await api.api('POST', '/models/selftest', {});
  $('s-service-test').disabled = false;
  const r = res.body || {};
  note.dataset.tone = res.ok && r.ok ? 'ok' : 'bad';
  note.textContent = res.ok && r.ok
    ? `The Claw service replied in ${(r.ms / 1000).toFixed(1)}s: \u201C${r.reply}\u201D`
    : r.message || res.body?.error?.message || 'The Claw service did not reply.';
}

function fillSettingsForm(s) {
  $('s-custom').checked = s.model.mode === 'custom';
  $('s-think').value = ['cloud', 'service'].includes(s.model.mode) ? s.model.mode : 'builtin';
  applyThinkMode();
  // Cloud fields. The key is never sent to this page, so the box starts empty and
  // says whether one is stored; leaving it empty keeps whatever is saved.
  $('s-cloud-url').value = s.model.mode === 'cloud' ? s.model.base_url : '';
  $('s-cloud-model').value = s.model.mode === 'cloud' ? s.model.model : '';
  $('s-cloud-key').value = '';
  $('s-cloud-key').placeholder = s.model.api_key_set ? 'A key is saved' : 'paste your key';
  $('s-cloud-key-note').textContent = s.model.api_key_set
    ? 'A key is saved. Leave this blank to keep it, or type a new one to replace it.'
    : 'Stored on this computer only, and never shown again once saved.';
  $('s-cloud-result').textContent = '';
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
  $('b-searxng').value = b.searxng_url || '';
  applySearchEngine();
  $('b-history').value = b.history_access || 'ask';
  const a = s.agent || {};
  $('a-max-steps').value = a.max_steps ?? 20;
  $('a-step-timeout').value = a.step_timeout_s ?? 60;
  const m = s.messages || {};
  $('m-read').value = m.whatsapp_read || 'ask';
  $('m-every').value = String(m.check_every_minutes || 0);
  $('m-notify').checked = m.notify !== false;
  $('m-previews').checked = !!m.show_previews;
  loadWhatsApp();
  const d = s.desktop || {};
  $('d-quickbar').checked = d.show_quick_bar !== false;
  $('d-startup').checked = !!d.start_with_windows;
  $('d-awake').checked = d.keep_awake_while_running !== false;
  $('d-notify').checked = d.notifications !== false;
  $('d-tray').checked = d.close_to_tray !== false;
  $('d-brief').value = d.brief_at || '';
  applyTheme(d.theme || 'system');
  // Only on the home screen, and only while it has not been read.
  showTips(d.show_tips !== false && state.view === 'home');
  state.draftFolders = [...s.permissions.authorized_folders];
  renderFolders();
  $('s-test-result').textContent = '';
  $('settings-error').hidden = true;
}

function readCloudKey() {
  const typed = $('s-cloud-key').value;
  if (typed) return typed;                              // replacing it
  return state.settings?.model?.api_key_set ? KEY_KEPT : '';  // keeping it, or none
}

function readModelForm() {
  if ($('s-think').value === 'service') {
    // The address and the credential come from the build, so there is nothing here
    // for the user to fill in or get wrong.
    return { ...(state.settings?.model || {}), mode: 'service', api_key: KEY_KEPT };
  }
  if ($('s-think').value === 'cloud') {
    return {
      ...(state.settings?.model || {}),
      mode: 'cloud',
      provider: 'openai_compatible',
      base_url: $('s-cloud-url').value.trim(),
      model: $('s-cloud-model').value.trim(),
      api_key: readCloudKey(),
    };
  }
  const mode = $('s-custom').checked ? 'custom' : 'builtin';
  return {
    ...(state.settings?.model || {}),
    mode,
    api_key: readCloudKey(),
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
      searxng_url: $('b-searxng').value.trim(),
      history_access: $('b-history').value,
    },
    documents: { ...(prev.documents || {}) },
    messages: {
      whatsapp_read: $('m-read').value,
      check_every_minutes: Number($('m-every').value),
      notify: $('m-notify').checked,
      show_previews: $('m-previews').checked,
    },
    agent: { ...(prev.agent || {}), max_steps: Number($('a-max-steps').value), step_timeout_s: Number($('a-step-timeout').value) },
    desktop: {
      show_quick_bar: $('d-quickbar').checked,
      start_with_windows: $('d-startup').checked,
      keep_awake_while_running: $('d-awake').checked,
      notifications: $('d-notify').checked,
      close_to_tray: $('d-tray').checked,
      brief_at: $('d-brief').value || '',
      theme: $('d-theme').value || 'system',
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

// ---------- What Claw can do ----------
// Every line here describes something that exists. A tour that promises what the
// product cannot do is worse than no tour: the first thing the person tries is
// the thing that fails.
const TIPS = [
  { title: 'Ask for the result, not the steps',
    body: 'Describe what you want to end up with. Claw plans it, carries it out one step at a '
        + 'time, and checks each step actually worked instead of assuming it did.' },
  { title: 'It works the apps you already have',
    body: 'There is no WhatsApp or Telegram account to connect. Claw opens the app on your '
        + 'computer and uses it the way you would — and pressing Send always asks you first, '
        + 'naming the chat and quoting the message.' },
  { title: 'It reads your documents',
    body: 'Open a PDF, Word or Excel file and ask about it. Scanned pages are read on this '
        + 'computer with OCR, and Claw tells you which words came from a scan and how sure it is.' },
  { title: 'Calendar and reminders',
    body: 'Say "put the site visit on Tuesday at 3 and remind me an hour before". It is kept as '
        + 'an ordinary calendar file, so Outlook and Google can read it too.' },
  { title: 'It remembers what you tell it',
    body: 'Preferences, projects, the people you deal with. Never a password, a code or a card '
        + 'number — those are refused as you say them. Everything stored is listed in Settings, '
        + 'with a Remove on each line.' },
  { title: 'Jobs that run on a schedule',
    body: 'Check a site every hour, write a report each morning. They run while Claw is open — '
        + 'not when your computer is off, and the app will not pretend otherwise.' },
  { title: 'Talk instead of typing',
    body: 'Press the microphone in the task box, or Ctrl+Shift+V anywhere. The words appear for '
        + 'you to check; nothing runs until you press Start.' },
  { title: 'It is always one key away',
    body: 'Ctrl+Shift+Space anywhere in Windows opens the bar. Drag it wherever you like, or '
        + 'close it with the × and bring it back with the same keys.' },
];

const tips = { at: 0 };

function renderTip() {
  const tip = TIPS[tips.at];
  $('tips-title').textContent = tip.title;
  $('tips-body').textContent = tip.body;
  $('tips-next').textContent = tips.at === TIPS.length - 1 ? 'Got it' : 'Next';
  $('tips-dots').replaceChildren(...TIPS.map((_, i) => {
    const dot = el('button', { className: 'tips-dot', attrs: { type: 'button', role: 'tab' } });
    dot.setAttribute('aria-selected', i === tips.at ? 'true' : 'false');
    dot.setAttribute('aria-label', `Tip ${i + 1} of ${TIPS.length}`);
    dot.addEventListener('click', () => { tips.at = i; renderTip(); });
    return dot;
  }));
}

function showTips(show) {
  $('tips').hidden = !show;
  if (show) renderTip();
}

/** Close for now. It comes back next launch, which is what "not yet" means. */
function dismissTips() {
  showTips(false);
}

/** Never again — and that is remembered, because a tour you cannot stop is an advert. */
async function stopTips() {
  showTips(false);
  const res = await api.api('GET', '/settings');
  if (!res.ok) {
    showError(res.body, 'That could not be saved, so the tips will come back next launch.');
    return;
  }
  const settings = res.body.settings;
  settings.desktop = { ...settings.desktop, show_tips: false };
  await api.api('PUT', '/settings', settings);
}

function nextTip() {
  if (tips.at === TIPS.length - 1) stopTips();      // "Got it" means do not ask again
  else { tips.at += 1; renderTip(); }
}

// ---------- Appearance ----------
// Three states, not two: "follow Windows" has to stay available, because most
// people set that once and expect every app to respect it — including when it
// flips at sunset.
const THEMES = ['system', 'light', 'dark'];

function systemIsDark() {
  return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
}

/** Paint the window, and say what the toggle would do next. */
function applyTheme(theme) {
  const choice = THEMES.includes(theme) ? theme : 'system';
  state.theme = choice;
  const root = document.documentElement;
  if (choice === 'system') delete root.dataset.theme;
  else root.dataset.theme = choice;
  const dark = choice === 'dark' || (choice === 'system' && systemIsDark());
  const icon = $('theme-icon');
  if (icon) icon.setAttribute('href', dark ? '#i-sun' : '#i-moon');
  const label = $('theme-label');
  if (label) label.textContent = dark ? 'Light mode' : 'Dark mode';
  const btn = $('toggle-theme');
  if (btn) btn.setAttribute('aria-pressed', dark ? 'true' : 'false');
  const select = $('d-theme');
  if (select && select.value !== choice) select.value = choice;
}

async function saveTheme(theme) {
  applyTheme(theme);                 // repaint first; the save is not what the eye waits for
  const res = await api.api('GET', '/settings');
  if (!res.ok) {
    // The screen has already changed, so silence here is a lie that lasts until
    // the next launch puts the old theme back.
    showError(res.body, 'The theme was changed on screen but could not be saved.');
    return;
  }
  const settings = res.body.settings;
  settings.desktop = { ...settings.desktop, theme };
  await api.api('PUT', '/settings', settings);
}

/** The sidebar button flips between light and dark, whatever it is now. */
function flipTheme() {
  const dark = state.theme === 'dark' || (state.theme === 'system' && systemIsDark());
  saveTheme(dark ? 'light' : 'dark');
}

// ---------- Dictation ----------
// The button is always there. When voice is not set up it says so and opens the
// right page, because a control that disappears teaches people the feature does
// not exist — which is what happened before.
const dictation = { ready: false, recording: false, busy: false,
                    stream: null, ctx: null, node: null, chunks: [], rate: 16000 };

function micState(state, title) {
  const btn = $('dictate');
  btn.dataset.state = state;
  if (title) btn.title = title;
}

async function refreshDictation() {
  const res = await api.api('GET', '/speech');
  const s = res.ok ? res.body : null;
  dictation.ready = !!(s && s.ready);
  if (dictation.ready) micState('idle', 'Dictate (Ctrl+Shift+V)');
  else if (s && s.enabled) micState('off', s.reason || 'Voice is not ready yet');
  else micState('off', 'Dictation is off — click to set it up');
}

function releaseMic() {
  try { if (dictation.node) dictation.node.disconnect(); } catch { /* already gone */ }
  try { if (dictation.ctx) dictation.ctx.close(); } catch { /* already closed */ }
  if (dictation.stream) dictation.stream.getTracks().forEach((t) => t.stop());
  dictation.node = dictation.ctx = dictation.stream = null;
}

/** Raw mono samples to a 16-bit WAV, the shape the backend expects. */
function encodeWav(chunks, rate) {
  let total = 0;
  chunks.forEach((c) => { total += c.length; });
  const pcm = new Int16Array(total);
  let i = 0;
  chunks.forEach((c) => {
    for (let k = 0; k < c.length; k += 1, i += 1) {
      const v = Math.max(-1, Math.min(1, c[k]));
      pcm[i] = v < 0 ? v * 0x8000 : v * 0x7fff;
    }
  });
  const buf = new ArrayBuffer(44 + pcm.length * 2);
  const view = new DataView(buf);
  const ascii = (off, t) => { for (let k = 0; k < t.length; k += 1) view.setUint8(off + k, t.charCodeAt(k)); };
  ascii(0, 'RIFF'); view.setUint32(4, 36 + pcm.length * 2, true); ascii(8, 'WAVE');
  ascii(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, rate, true); view.setUint32(28, rate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  ascii(36, 'data'); view.setUint32(40, pcm.length * 2, true);
  new Int16Array(buf, 44).set(pcm);
  return new Uint8Array(buf);
}

async function startDictation() {
  if (dictation.recording || dictation.busy) return;
  try {
    dictation.stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    });
  } catch (err) {
    micState('off', err && err.name === 'NotAllowedError'
      ? 'Windows has not given Claw the microphone'
      : 'No microphone was found');
    return;
  }
  dictation.ctx = new AudioContext();
  dictation.rate = dictation.ctx.sampleRate;
  dictation.chunks = [];
  const src = dictation.ctx.createMediaStreamSource(dictation.stream);
  dictation.node = dictation.ctx.createScriptProcessor(4096, 1, 1);
  dictation.node.onaudioprocess = (e) => {
    if (!dictation.recording) return;
    dictation.chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
  };
  src.connect(dictation.node);
  dictation.node.connect(dictation.ctx.destination);
  dictation.recording = true;
  micState('on', 'Listening — click to stop');
}

async function stopDictation() {
  if (!dictation.recording) return;
  const { chunks, rate } = dictation;
  dictation.recording = false;
  dictation.chunks = [];
  releaseMic();                       // the microphone is freed before recognition runs
  if (!chunks.length) { micState('idle'); return; }
  dictation.busy = true;
  micState('off', 'Working out what you said…');
  try {
    const res = await api.transcribe(encodeWav(chunks, rate));
    if (res && res.ok && res.text) {
      // The words go into the box. Nothing runs until the person presses Start.
      const box = $('task-input');
      box.value = box.value ? `${box.value.trim()} ${res.text}` : res.text;
      box.focus();
      updateButtons();
      micState('idle', 'Check the words, then press Start task');
    } else {
      micState('idle', (res && res.message) || 'Claw could not make out any words');
    }
  } finally {
    dictation.busy = false;
  }
}

async function onMicClick() {
  if (!dictation.ready) {
    // Not set up: take them to the page that sets it up rather than doing nothing.
    openSettings();
    showSettingsPanel('set-brain');
    $('settings-error').replaceChildren(el('div', { className: 'banner-body' }, [
      el('strong', { text: 'Dictation needs a voice model' }),
      el('p', { text: 'Turn voice on and download one (the smallest is about 120 MB). '
                      + 'Then the microphone works here and with Ctrl+Shift+V.' }),
    ]));
    $('settings-error').hidden = false;
    return;
  }
  if (dictation.recording) await stopDictation();
  else await startDictation();
}

// ---------- Standing reply ----------
// Everything here is about what Claw has prepared. There is no send button,
// because there is nothing on the other side of it: the backend has no way to
// send a WhatsApp message, and this panel must not imply otherwise.
function draftRow(d) {
  const copy = el('button', { className: 'link', text: 'Copy' });
  copy.addEventListener('click', async () => {
    const res = await api.copyText(d.message);
    copy.textContent = res && res.ok ? 'Copied' : 'Could not copy';
    setTimeout(() => { copy.textContent = 'Copy'; }, 1800);
  });
  return el('li', { className: 'sr-draft' }, [
    el('span', { className: 'sr-chat', text: d.chat }),
    copy,
    el('span', { className: 'sr-why', text: d.because }),
    el('span', { className: 'sr-text', text: `“${d.message}”` }),
  ]);
}

function renderStanding(body) {
  const live = !!body.authorised;
  $('sr-live').hidden = !live;
  $('sr-new').hidden = live;
  if (live) {
    const mins = body.minutes_left || 0;
    const left = mins >= 60
      ? `${Math.floor(mins / 60)}h ${mins % 60}m left`
      : `${mins} minute${mins === 1 ? '' : 's'} left`;
    $('sr-state').textContent = `Replying for you — ${left}`;
    $('sr-account').textContent = body.account_hint
      ? `Watching: ${body.account_hint}. ${body.drafts_made || 0} prepared so far.`
      : `${body.drafts_made || 0} prepared so far. Claw will name the window once it has read it.`;
  }
  const drafts = body.drafts || [];
  $('sr-drafts').replaceChildren(...drafts.map(draftRow));
  $('sr-empty').hidden = drafts.length > 0 || !live;
}

async function loadStanding() {
  const res = await api.api('GET', '/standing-reply');
  if (res.ok) renderStanding(res.body);
}

async function startStanding() {
  const body = { message: $('sr-message').value.trim(), hours: Number($('sr-hours').value) };
  const res = await api.api('POST', '/standing-reply', body);
  if (!res.ok) {
    $('sr-error').textContent = (res.body && res.body.error && res.body.error.message)
      || 'That could not be started.';
    return;
  }
  $('sr-error').textContent = '';
  renderStanding(res.body);
}

async function stopStanding() {
  const res = await api.api('DELETE', '/standing-reply');
  if (res.ok) renderStanding(res.body);
}

// ---------- Automations ----------
// Each job shows its schedule, when it next runs, and what happened last time.
// "Ran" and "was skipped" are different words on purpose: a job skipped because
// you were using S-CLAW has not had its turn.
const JOB_OUTCOME = {
  completed: 'ran', failed: 'failed', stopped: 'stopped', skipped: 'was skipped',
  started: 'running now', incomplete: 'did not finish',
  interrupted: 'was cut short when S-CLAW stopped',
};

function jobWhen(job) {
  if (!job.enabled) return 'Paused';
  if (!job.next_run) return job.schedule;
  const when = new Date(job.next_run);
  const soon = when.toLocaleString(undefined, { weekday: 'short', hour: '2-digit', minute: '2-digit' });
  return `${job.schedule} · next ${soon}`;
}

function jobLast(job) {
  if (!job.last_status) return 'Never run yet.';
  const what = JOB_OUTCOME[job.last_status] || job.last_status;
  const detail = job.last_detail ? ` — ${job.last_detail}` : '';
  const when = job.last_run ? ` on ${new Date(job.last_run).toLocaleString()}` : '';
  return `Last: ${what}${when}${detail}`;
}

function jobRow(job) {
  const toggle = el('button', { className: 'link', text: job.enabled ? 'Pause' : 'Resume' });
  toggle.addEventListener('click', async () => {
    toggle.disabled = true;
    await api.api('POST', `/jobs/${encodeURIComponent(job.id)}/enabled`, { enabled: !job.enabled });
    loadJobs();
  });
  const runNow = el('button', { className: 'link', text: 'Run now' });
  runNow.addEventListener('click', async () => {
    runNow.disabled = true;
    const res = await api.api('POST', `/jobs/${encodeURIComponent(job.id)}/run`);
    if (res.ok) {
      closeSettings();
      startWatching(res.body.task_id, job.name);
    } else {
      runNow.disabled = false;
      $('job-error').textContent = (res.body && res.body.error && res.body.error.message) || '';
    }
  });
  const remove = el('button', { className: 'link', text: 'Remove' });
  remove.addEventListener('click', async () => {
    const sure = await api.confirm('Remove this job?',
      `"${job.name}" and its history will be removed. This cannot be undone.`, 'Remove');
    if (!sure) return;
    await api.api('DELETE', `/jobs/${encodeURIComponent(job.id)}`);
    loadJobs();
  });
  return el('li', { className: `job-row${job.enabled ? '' : ' job-off'}` }, [
    el('span', { className: 'job-name', text: job.name }),
    el('span', { className: 'job-acts' }, [runNow, toggle, remove]),
    el('span', { className: 'job-what', text: job.task_text }),
    el('span', { className: 'job-when', text: `${jobWhen(job)} · ${jobLast(job)}` }),
  ]);
}

async function loadJobs() {
  const res = await api.api('GET', '/jobs');
  const rows = (res.ok && res.body.jobs) || [];
  $('job-list').replaceChildren(...rows.map(jobRow));
  $('job-empty').hidden = rows.length > 0;
}

async function addJob() {
  const kind = $('job-kind').value;
  const body = {
    name: $('job-name').value.trim(),
    task: $('job-task').value.trim(),
    kind,
    minutes: kind === 'every' ? Number($('job-minutes').value) : undefined,
    at: kind === 'daily' ? $('job-at').value : undefined,
  };
  const res = await api.api('POST', '/jobs', body);
  if (!res.ok) {
    $('job-error').textContent = (res.body && res.body.error && res.body.error.message)
      || 'That job could not be added.';
    return;
  }
  $('job-error').textContent = '';
  $('job-name').value = '';
  $('job-task').value = '';
  loadJobs();
}

/** Wait for a pause in typing before asking the backend again. */
function debounce(fn, ms) {
  let t = null;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

// ---------- Memory ----------
// What is remembered is shown as it is stored, with where it came from and when.
// Removing one is immediate: there is no "are you sure" for a single memory,
// because the whole point is that it should be easy to correct.
function memoryRow(m) {
  const when = m.updated_at ? new Date(m.updated_at).toLocaleDateString() : '';
  const remove = el('button', { className: 'link', text: 'Remove' });
  remove.addEventListener('click', async () => {
    remove.disabled = true;
    const res = await api.api('DELETE', `/memory/${encodeURIComponent(m.id)}`);
    if (res.ok) loadMemories();
    else remove.disabled = false;
  });
  return el('li', { className: 'mem-row' }, [
    el('span', { className: 'mem-kind', text: m.kind }),
    el('span', { className: 'mem-fact' }, [
      el('strong', { text: `${m.subject}: ` }),
      document.createTextNode(m.fact),
    ]),
    el('span', { className: 'mem-when' }, [document.createTextNode(when), remove]),
  ]);
}

async function loadMemories() {
  const query = encodeURIComponent($('mem-search').value.trim());
  const res = await api.api('GET', `/memory${query ? `?query=${query}` : ''}`);
  const rows = (res.ok && res.body.memories) || [];
  $('mem-list').replaceChildren(...rows.map(memoryRow));
  $('mem-empty').hidden = rows.length > 0;
  $('mem-empty').textContent = $('mem-search').value.trim() && rows.length === 0
    ? 'Nothing remembered matches that.'
    : 'Nothing is remembered yet.';
}

async function exportMemories() {
  const res = await api.api('GET', '/memory/export');
  if (!res.ok) {
    showError(res.body, 'Your memories could not be exported.');
    return;
  }
  // Saved through the same path as every other file Claw writes.
  const name = `s-claw-memory-${new Date().toISOString().slice(0, 10)}.json`;
  await api.saveText(name, JSON.stringify(res.body, null, 2));
}

async function clearMemories() {
  const sure = await api.confirm('Forget everything?',
    'Everything Claw remembers about you, your projects and your contacts will be removed. '
    + 'This cannot be undone. Export first if you want to keep a copy.', 'Forget everything');
  if (!sure) return;
  const res = await api.api('POST', '/memory/forget-all', {});
  if (res.ok) loadMemories();
}

// ---------- About ----------
// The details come from the main process (src/creator.js), so the app, the
// installer and the packaged executable all carry the same name and link.
let creator = null;

async function fillAbout() {
  if (!api.creator) return;
  creator = creator || await api.creator();
  if (!creator) return;
  $('about-version').textContent = `S-CLAW ${creator.version}`;
  $('about-copyright').textContent = `${creator.copyright}. All rights reserved.`;
  $('about-whatsapp').textContent = creator.whatsapp;
  // The address itself is never shown. The badge is the link.
}

async function openCreatorSite() {
  if (!creator || !api.openLink) return;
  const res = await api.openLink(creator.site);
  if (res && res.ok === false) {
    const box = $('settings-error');
    box.replaceChildren(el('div', { className: 'banner-body' },
      [el('strong', { text: res.message || 'That link could not be opened.' })]));
    box.hidden = false;
  }
}

async function copyWhatsApp() {
  if (!creator || !api.copyText) return;
  const res = await api.copyText(creator.whatsapp);
  const btn = $('copy-whatsapp');
  // The clipboard gives no visible sign on its own, so the button says what happened.
  btn.textContent = res && res.ok ? 'Copied' : 'Could not copy';
  setTimeout(() => { btn.textContent = 'Copy'; }, 1800);
}

let lastFocus = null;
function openSettings() {
  lastFocus = document.activeElement;
  fillSettingsForm(state.settings || defaultSettings());
  applyEdition(state.edition);
  showSettingsPanel('set-brain');
  fillAbout();
  loadMemories();
  loadJobs();
  loadStanding();
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
    model: { mode: 'builtin', provider: 'openai_compatible', base_url: DEFAULT_URLS.openai_compatible, model: '', request_timeout_s: 120, temperature: 0.2, allow_remote_server: false },
    permissions: { modes: { read_only: 'allow', local_write: 'ask', external: 'ask', destructive: 'ask' }, authorized_folders: [] },
  };
}

async function testCloudConnection() {
  const note = $('s-cloud-result');
  note.dataset.tone = '';
  const url = $('s-cloud-url').value.trim();
  const model = $('s-cloud-model').value.trim();
  if (!url.startsWith('https://')) {
    note.dataset.tone = 'bad';
    note.textContent = 'The address must start with https:// so your key is not sent in the clear.';
    return;
  }
  if (!model) {
    note.dataset.tone = 'bad';
    note.textContent = 'Say which model to use.';
    return;
  }
  note.textContent = 'Checking…';
  $('s-cloud-test').disabled = true;
  const res = await api.api('POST', '/models/probe', { ...readModelForm(), mode: 'cloud' });
  $('s-cloud-test').disabled = false;
  if (!res.ok) {
    note.dataset.tone = 'bad';
    const e = res.body?.error || {};
    note.textContent = [e.message, ...(e.details || [])].filter(Boolean).join(' ');
    return;
  }
  const r = res.body;
  if (!r.model_available) {
    note.dataset.tone = 'bad';
    note.textContent = r.message || 'Connected, but that model was not available.';
    return;
  }
  // Listing the model is not the same as the model answering, and saying "answered"
  // after a check that generated nothing was a claim this app had not earned.
  note.textContent = `Connected. Asking ${model} to reply…`;
  $('s-cloud-test').disabled = true;
  const live = await api.api('POST', '/models/selftest', { ...readModelForm(), mode: 'cloud' });
  $('s-cloud-test').disabled = false;
  const t = live.body || {};
  note.dataset.tone = live.ok && t.ok ? 'ok' : 'bad';
  note.textContent = live.ok && t.ok
    ? `${model} replied in ${(t.ms / 1000).toFixed(1)}s: “${t.reply}”`
    : t.message || live.body?.error?.message || 'Connected, but the model did not reply.';
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
  $('run-again').addEventListener('click', async () => {
    if (!state.run || isRunning() || state.busy) return;
    // The title on screen is not always the task that was asked. A scheduled
    // job's run is labelled with the job's name, and a run picked up after a
    // restart falls back to "Running task", so re-running the label would run
    // something the person never typed. Ask the backend what was actually asked.
    const t = await api.api('GET', `/tasks/${state.run.id}`);
    const text = t.ok ? String(t.body.task_text || '').trim() : '';
    if (!text) {
      showError(t.body, 'That task could not be read again, so it was not re-run.');
      return;
    }
    runTask(text);
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
  $('wa-check').addEventListener('click', checkWhatsAppNow);
  $('open-docs').addEventListener('click', openDocsView);
  $('doc-open').addEventListener('click', openDocument);
  $('doc-cancel').addEventListener('click', () => doc.job && api.api('POST', `/documents/${doc.job.id}/cancel`));
  $('doc-show').addEventListener('click', () => doc.job && api.showDocument(doc.job.id));
  $('doc-save').addEventListener('click', async () => {
    if (!doc.job) return;
    $('doc-save').disabled = true;
    $('doc-ask-note').textContent = 'Making the searchable copy…';
    const r = await api.saveSearchable(doc.job.id, doc.job.name);
    $('doc-save').disabled = false;
    if (!r || r.cancelled) return void ($('doc-ask-note').textContent = '');
    $('doc-ask-note').textContent = r.ok ? `Saved: ${r.body.path}` : r.body?.error?.message || 'The copy could not be saved.';
  });
  $('doc-q').addEventListener('input', () => {
    clearTimeout(docSearchTimer);
    docSearchTimer = setTimeout(searchDoc, 200);
  });
  $('doc-question').addEventListener('input', updateAskButton);
  $('doc-question').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.isComposing) {
      e.preventDefault();
      askAboutDoc();
    }
  });
  $('doc-ask').addEventListener('click', askAboutDoc);
  $('s-think').addEventListener('change', applyThinkMode);
  $('s-cloud-test').addEventListener('click', testCloudConnection);
  $('s-service-test').addEventListener('click', testServiceConnection);
  for (const tab of settingsTabs()) {
    tab.addEventListener('click', () => showSettingsPanel(tab.dataset.panel));
    tab.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowDown' || e.key === 'ArrowRight') { e.preventDefault(); moveSettingsTab(tab, 1); }
      if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') { e.preventDefault(); moveSettingsTab(tab, -1); }
    });
  }
  $('brain-import').addEventListener('click', importBrain);
  $('brain-restart').addEventListener('click', async () => {
    $('brain-restart').disabled = true;
    $('brain-note').dataset.tone = '';
    $('brain-note').textContent = 'Restarting the brain…';
    await brainCall('/brain/restart', {}, 'The brain restarted and is ready.');
  });
  $('brain-dl-cancel').addEventListener('click', () => brainCall('/brain/download/cancel', {}, 'Download cancelled.'));
  $('open-settings').addEventListener('click', openSettings);
  $('close-settings').addEventListener('click', closeSettings);
  $('cancel-settings').addEventListener('click', closeSettings);
  $('settings-scrim').addEventListener('click', closeSettings);
  $('save-settings').addEventListener('click', saveSettings);
  $('s-test').addEventListener('click', testConnection);
  $('dictate').addEventListener('click', onMicClick);
  $('sr-start').addEventListener('click', startStanding);
  $('sr-stop').addEventListener('click', stopStanding);
  $('job-add').addEventListener('click', addJob);
  $('job-kind').addEventListener('change', () => {
    const every = $('job-kind').value === 'every';
    $('job-every-wrap').hidden = !every;
    $('job-at-wrap').hidden = every;
  });
  $('mem-search').addEventListener('input', debounce(loadMemories, 200));
  $('mem-export').addEventListener('click', exportMemories);
  $('mem-clear').addEventListener('click', clearMemories);
  $('credit-badge').addEventListener('click', openCreatorSite);
  $('copy-whatsapp').addEventListener('click', copyWhatsApp);
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
    applySearchEngine();
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
  refreshDictation();
  $('tips-close').addEventListener('click', dismissTips);
  $('tips-never').addEventListener('click', stopTips);
  $('tips-next').addEventListener('click', nextTip);
  $('toggle-theme').addEventListener('click', flipTheme);
  $('d-theme').addEventListener('change', () => saveTheme($('d-theme').value));
  // Following Windows means following it while the app is open, too.
  if (window.matchMedia) {
    window.matchMedia('(prefers-color-scheme: dark)')
      .addEventListener('change', () => { if (state.theme === 'system') applyTheme('system'); });
  }
  api.onSettingsChanged(() => refreshDictation());
  api.onTaskStarted(({ id }) => {
    loadHistory();
    if (state.view === 'home' || !isRunning()) openTask(id);
  });
  api.onNavigate((route) => {
    if (route && route.taskId) openTask(route.taskId);
  });
  api.onAgentStatus((s) => {
    // The mark in the title bar turns while Claw works and settles when it stops,
    // so the state of the app is readable without reading anything.
    const phase = (s && s.phase) || 'idle';
    if (document.body.dataset.phase === 'working' && phase !== 'working') flashMark();
    document.body.dataset.phase = phase;
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
