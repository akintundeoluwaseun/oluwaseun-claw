'use strict';

const {
  app, BrowserWindow, Menu, Notification, Tray, clipboard, dialog, globalShortcut, ipcMain,
  nativeImage, nativeTheme, powerSaveBlocker, screen, session, shell,
} = require('electron');
const path = require('node:path');
const { Backend } = require('./backend');
const { AgentWatcher } = require('./watcher');
const { ReminderWatcher, BriefWatcher } = require('./reminders');
const { clampBounds, defaultBounds } = require('./quickbar-position');
const { CREATOR, isAllowedLink } = require('./creator');

const BACKEND_DIR = process.env.CLAW_BACKEND_DIR || (app.isPackaged ? path.join(process.resourcesPath, 'backend') : path.resolve(__dirname, '..', '..', 'backend'));
const RESOURCES_DIR = process.env.CLAW_RESOURCES || (app.isPackaged ? process.resourcesPath : null);
const ASSETS = path.join(__dirname, 'assets');
const QUICK_SHORTCUT = 'CommandOrControl+Shift+Space';
const STOP_SHORTCUT = 'CommandOrControl+Alt+X'; // works even while Claw is using the mouse and keyboard
const START_HIDDEN = process.argv.includes('--background');
const IS_WIN = process.platform === 'win32';

let mainWindow = null;
let quickBar = null;
let tray = null;
let backend = null;
let watcher = null;
let reminders = null;
let briefing = null;
let lastBriefDay = null;
let quitting = false;
let awakeBlocker = null;
let trayHintShown = false;
let desktop = { start_with_windows: false, show_quick_bar: true, keep_awake_while_running: true, notifications: true, close_to_tray: true, brief_at: '' };

if (process.env.CLAW_E2E) app.setPath('userData', path.join(require('node:os').tmpdir(), `claw-e2e-${process.pid}`));
if (IS_WIN) app.setAppUserModelId('com.oluwaseun.sclaw'); // required for Windows notifications

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => showMain());
}

// ---------- Windows ----------
const THEME = {
  light: { overlay: '#ffffff', symbols: '#14212b' },
  dark: { overlay: '#161e24', symbols: '#e6ecef' },
};

function overlayColors() {
  return nativeTheme.shouldUseDarkColors ? THEME.dark : THEME.light;
}

/** Repaint the chrome of every window we own after a theme change. */
function paintWindows() {
  const c = overlayColors();
  for (const win of [mainWindow, quickBar]) {
    if (!win || win.isDestroyed()) continue;
    win.setBackgroundColor(c.overlay);
    if (typeof win.setTitleBarOverlay === 'function') {
      try {
        win.setTitleBarOverlay({ color: c.overlay, symbolColor: c.symbols, height: 44 });
      } catch {
        /* the quick bar is frameless and has no overlay to set */
      }
    }
  }
  // The bar is its own window with its own document.
  if (quickBar && !quickBar.isDestroyed()) {
    quickBar.webContents.send('claw:theme', desktop.theme || 'system');
  }
}

function createMainWindow() {
  const c = overlayColors();
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 840,
    minWidth: 960,
    minHeight: 620,
    title: 'S-CLAW',
    icon: path.join(ASSETS, IS_WIN ? 'icon.ico' : 'icon.png'),
    backgroundColor: c.overlay,
    show: false,
    titleBarStyle: 'hidden',
    titleBarOverlay: { color: c.overlay, symbolColor: c.symbols, height: 44 },
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      spellcheck: true,
    },
  });
  mainWindow.removeMenu();
  mainWindow.once('ready-to-show', () => {
    if (!START_HIDDEN) mainWindow.show();
  });
  mainWindow.webContents.on('will-navigate', (e) => e.preventDefault());
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https:\/\//.test(url)) shell.openExternal(url);
    return { action: 'deny' };
  });
  mainWindow.on('close', (e) => {
    if (quitting || !desktop.close_to_tray || !tray) return;
    e.preventDefault();
    mainWindow.hide();
    if (!trayHintShown) {
      trayHintShown = true;
      notify('Claw is still running', 'It keeps working in the background. Open it any time from the tray or the quick bar.');
    }
  });
  mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'));
}

function showMain(route) {
  if (!mainWindow) return;
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.show();
  mainWindow.focus();
  if (route) mainWindow.webContents.send('claw:navigate', route);
}

// Quick bar: a slim always-on-top pill at the top of the screen.
const QB = { collapsed: { w: 340, h: 52 }, expanded: { w: 680, h: 132 } };
let quickMode = 'collapsed';

// Where the person last put the bar. Null means the default: centred at the top.
let quickPos = null;
let quickDrag = null;

function quickPosFile() {
  return path.join(app.getPath('userData'), 'quickbar-position.json');
}

function loadQuickPos() {
  try {
    const saved = JSON.parse(fs.readFileSync(quickPosFile(), 'utf8'));
    if (Number.isFinite(saved.x) && Number.isFinite(saved.y)) quickPos = { x: saved.x, y: saved.y };
  } catch {
    quickPos = null;                       // never had one, or it was unreadable
  }
}

function saveQuickPos() {
  try {
    fs.writeFileSync(quickPosFile(), JSON.stringify(quickPos || {}), 'utf8');
  } catch (err) {
    console.warn('could not remember the quick bar position', err.message);
  }
}

function quickBounds(mode) {
  const size = QB[mode];
  // Clamp to the display the bar is actually on. A position saved on a second
  // monitor that is now unplugged would otherwise put the bar off screen, where
  // it cannot be grabbed to bring it back.
  const display = quickPos
    ? screen.getDisplayNearestPoint({ x: Math.round(quickPos.x), y: Math.round(quickPos.y) })
    : screen.getPrimaryDisplay();
  const { workArea } = display;
  return quickPos ? clampBounds(quickPos, size, workArea) : defaultBounds(size, workArea);
}

function createQuickBar() {
  loadQuickPos();
  quickBar = new BrowserWindow({
    ...quickBounds('collapsed'),
    frame: false,
    transparent: true,
    resizable: false,
    movable: false,
    minimizable: false,
    maximizable: false,
    fullscreenable: false,
    skipTaskbar: true,
    alwaysOnTop: true,
    show: false,
    hasShadow: false,
    backgroundColor: '#00000000',
    webPreferences: {
      preload: path.join(__dirname, 'preload-quickbar.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  quickBar.setAlwaysOnTop(true, 'floating');
  quickBar.setVisibleOnAllWorkspaces(true);
  quickBar.webContents.on('will-navigate', (e) => e.preventDefault());
  quickBar.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  quickBar.on('blur', () => setQuickMode('collapsed'));
  quickBar.loadFile(path.join(__dirname, 'renderer', 'quickbar.html'));
  quickBar.once('ready-to-show', () => {
    if (desktop.show_quick_bar) quickBar.showInactive();
  });
}

// Dragging the bar. The renderer owns the pointer (it knows whether this was a
// click or a drag); the main process owns the window. Deltas are sent rather than
// absolute positions so a slow frame cannot teleport the bar across the screen.
function beginQuickDrag() {
  if (!quickBar) return;
  const b = quickBar.getBounds();
  quickDrag = { x: b.x, y: b.y };
}

function moveQuickDrag(dx, dy) {
  if (!quickBar || !quickDrag) return;
  quickPos = { x: quickDrag.x + Math.round(dx), y: quickDrag.y + Math.round(dy) };
  quickBar.setBounds(quickBounds(quickMode));
}

function endQuickDrag() {
  if (!quickDrag) return;
  quickDrag = null;
  // Keep what the clamp decided, not what the pointer asked for, so a bar dragged
  // off the edge comes back to where it actually sits.
  if (quickBar) {
    const b = quickBar.getBounds();
    quickPos = { x: b.x, y: b.y };
  }
  saveQuickPos();
}

function resetQuickPosition() {
  quickPos = null;
  saveQuickPos();
  if (quickBar) quickBar.setBounds(quickBounds(quickMode));
}

function setQuickMode(mode) {
  if (!quickBar || quickMode === mode) return;
  quickMode = mode;
  quickBar.setBounds(quickBounds(mode));
  quickBar.webContents.send('quickbar:mode', mode);
  if (mode === 'expanded') {
    quickBar.show();
    quickBar.focus();
  }
}

function openQuickBar() {
  if (!quickBar) return;
  if (!quickBar.isVisible()) quickBar.showInactive();
  setQuickMode('expanded');
}

// ---------- Tray ----------
function trayImage(kind) {
  const img = nativeImage.createFromPath(path.join(ASSETS, `tray-${kind}.png`));
  return img;
}

function buildTrayMenu() {
  const s = watcher ? watcher.status : { phase: 'idle' };
  const busyLine =
    s.phase === 'working' ? `Working: ${s.activity || 'busy'}` : s.phase === 'attention' ? 'Waiting for your OK' : s.phase === 'offline' ? 'Agent not running' : 'Ready for a task';
  return Menu.buildFromTemplate([
    { label: busyLine, enabled: false },
    { type: 'separator' },
    { label: 'Open Claw', click: () => showMain() },
    { label: 'New task…', accelerator: QUICK_SHORTCUT, click: () => openQuickBar() },
    { label: 'Stop current task', accelerator: STOP_SHORTCUT, enabled: s.phase === 'working' || s.phase === 'attention', click: () => stopCurrent() },
    { type: 'separator' },
    { label: 'Show quick bar', type: 'checkbox', checked: desktop.show_quick_bar, click: (i) => updateDesktopSetting('show_quick_bar', i.checked) },
    { label: 'Start with Windows', type: 'checkbox', checked: desktop.start_with_windows, click: (i) => updateDesktopSetting('start_with_windows', i.checked) },
    { type: 'separator' },
    { label: 'Quit Claw', click: () => { quitting = true; app.quit(); } },
  ]);
}

function createTray() {
  try {
    tray = new Tray(trayImage('idle'));
  } catch {
    tray = null; // some Linux desktops have no tray; the app still works
    return;
  }
  tray.setToolTip('S-CLAW — ready');
  tray.setContextMenu(buildTrayMenu());
  tray.on('click', () => showMain());
}

function refreshTray(status) {
  if (!tray) return;
  const kind = status.phase === 'attention' ? 'attention' : status.phase === 'working' ? 'busy' : 'idle';
  tray.setImage(trayImage(kind));
  const tip = status.phase === 'working' ? `S-CLAW — ${status.activity}` : status.phase === 'attention' ? 'S-CLAW — needs your OK' : 'S-CLAW — ready';
  tray.setToolTip(tip);
  tray.setContextMenu(buildTrayMenu());
}

// ---------- Notifications ----------
function notify(title, body, onClick) {
  if (!desktop.notifications || !Notification.isSupported()) return;
  const n = new Notification({ title, body, icon: path.join(ASSETS, 'icon.png'), silent: false });
  if (onClick) n.on('click', onClick);
  n.show();
}

// ---------- Settings sync ----------
async function loadDesktopSettings() {
  const res = await backend.request('GET', '/settings');
  if (res.ok && res.body.settings && res.body.settings.desktop) applyDesktopSettings(res.body.settings.desktop);
}

function applyDesktopSettings(next) {
  desktop = { ...desktop, ...next };
  // Electron paints the title bar and the native dialogs, not the stylesheet,
  // so the choice has to reach it too — otherwise a light app keeps a dark
  // title bar and looks half-finished.
  const theme = ['system', 'light', 'dark'].includes(desktop.theme) ? desktop.theme : 'system';
  if (nativeTheme.themeSource !== theme) nativeTheme.themeSource = theme;
  paintWindows();
  if (quickBar) {
    if (desktop.show_quick_bar && !quickBar.isVisible()) quickBar.showInactive();
    if (!desktop.show_quick_bar && quickBar.isVisible()) quickBar.hide();
  }
  if (IS_WIN || process.platform === 'darwin') {
    const args = app.isPackaged ? ['--background'] : [path.resolve(__dirname, '..'), '--background'];
    app.setLoginItemSettings({ openAtLogin: !!desktop.start_with_windows, path: process.execPath, args });
  }
  updateAwake();
  if (tray) tray.setContextMenu(buildTrayMenu());
}

async function updateDesktopSetting(key, value) {
  const res = await backend.request('GET', '/settings');
  if (!res.ok) return;
  const settings = res.body.settings;
  settings.desktop = { ...settings.desktop, [key]: value };
  const saved = await backend.request('PUT', '/settings', settings);
  if (saved.ok) {
    applyDesktopSettings(saved.body.settings.desktop);
    broadcast('claw:settings-changed', saved.body.settings);
  }
}

function updateAwake() {
  const busy = watcher && (watcher.status.phase === 'working' || watcher.status.phase === 'attention');
  const want = busy && desktop.keep_awake_while_running;
  if (want && awakeBlocker === null) awakeBlocker = powerSaveBlocker.start('prevent-app-suspension');
  if (!want && awakeBlocker !== null) {
    powerSaveBlocker.stop(awakeBlocker);
    awakeBlocker = null;
  }
}

// ---------- Shared actions ----------
function broadcast(channel, payload) {
  for (const w of [mainWindow, quickBar]) {
    if (w && !w.isDestroyed()) w.webContents.send(channel, payload);
  }
}

async function stopCurrent() {
  const id = watcher && watcher.status.taskId;
  if (id) await backend.request('POST', `/tasks/${id}/cancel`);
}

function senderIs(event, win) {
  return win && !win.isDestroyed() && event.sender === win.webContents;
}

function fromOurWindows(event) {
  return senderIs(event, mainWindow) || senderIs(event, quickBar);
}

// ---------- IPC: main window ----------
ipcMain.handle('claw:api', async (event, method, route, body) => {
  if (!senderIs(event, mainWindow)) return { ok: false, status: 403, body: { error: { message: 'Not allowed.' } } };
  const res = await backend.request(method, route, body);
  if (res.ok && method === 'PUT' && route === '/settings') applyDesktopSettings(res.body.settings.desktop);
  if (res.ok && method === 'POST' && route === '/tasks/run') watcher.nudge();
  return res;
});
ipcMain.handle('claw:backend-status', (event) => (fromOurWindows(event) ? backend.status : null));
ipcMain.handle('claw:agent-status', (event) => (fromOurWindows(event) ? watcher.status : null));
ipcMain.handle('claw:pick-folder', async (event) => {
  if (!senderIs(event, mainWindow)) return null;
  const res = await dialog.showOpenDialog(mainWindow, { title: 'Choose a folder Claw may use', properties: ['openDirectory'] });
  return res.canceled || !res.filePaths.length ? null : res.filePaths[0];
});
ipcMain.handle('claw:restart-backend', async (event) => {
  if (!senderIs(event, mainWindow)) return null;
  await startBackend(true);
  return backend.status;
});
// Open a file Claw made, or show it in File Explorer. Only paths recorded as outputs of
// that task are accepted, so the page can't ask the main process to open arbitrary files.
ipcMain.handle('claw:open-output', async (event, taskId, filePath, how) => {
  if (!senderIs(event, mainWindow)) return { ok: false };
  if (typeof taskId !== 'string' || !/^[0-9a-f]{32}$/.test(taskId) || typeof filePath !== 'string') return { ok: false };
  const res = await backend.request('GET', `/tasks/${taskId}`);
  const files = (res.ok && res.body.result && res.body.result.files) || [];
  if (!files.some((f) => f.path === filePath)) return { ok: false, message: 'That file is not one Claw made in this task.' };
  if (!require('node:fs').existsSync(filePath)) return { ok: false, message: 'The file is no longer there.' };
  if (how === 'show') {
    shell.showItemInFolder(filePath);
    return { ok: true };
  }
  const err = await shell.openPath(filePath);
  return err ? { ok: false, message: err } : { ok: true };
});
// ---------- IPC: who made this ----------
// Hiding the bar from the bar itself. It stays hidden until the person brings
// it back with the shortcut or the tray, and the setting follows so it does not
// reappear at the next launch and feel broken.
ipcMain.on('quickbar:hide', (event) => {
  if (!senderIs(event, quickBar)) return;
  if (quickBar) quickBar.hide();
  // The same path the tray menu uses, so the setting, the tray tick and the
  // window all end up agreeing.
  updateDesktopSetting('show_quick_bar', false).catch(() => {});
  notify('The bar is hidden', `Press ${QUICK_SHORTCUT.replace('CommandOrControl', 'Ctrl')} to bring it back, or turn it on again in Settings.`);
});

ipcMain.handle('claw:creator', (event) => (fromOurWindows(event)
  ? { ...CREATOR, version: app.getVersion() }
  : null));

// Opening a link hands a URL to the user's own browser, so the URL is not taken
// on trust: only the creator's own site passes, and only over https.
ipcMain.handle('claw:open-link', async (event, url) => {
  if (!senderIs(event, mainWindow)) return { ok: false, message: 'Not allowed.' };
  if (!isAllowedLink(url)) return { ok: false, message: 'That link is not one S-CLAW opens.' };
  await shell.openExternal(url);
  return { ok: true };
});

ipcMain.handle('claw:copy-text', (event, text) => {
  if (!senderIs(event, mainWindow) || typeof text !== 'string') return { ok: false };
  // Short, and only ever something already on screen - never a path or a token.
  clipboard.writeText(text.slice(0, 200));
  return { ok: true };
});

ipcMain.handle('claw:shortcut', (event) => (fromOurWindows(event) ? QUICK_SHORTCUT.replace('CommandOrControl', 'Ctrl') : ''));
ipcMain.handle('claw:stop-shortcut', (event) => (fromOurWindows(event) ? STOP_SHORTCUT.replace('CommandOrControl', 'Ctrl') : ''));

// ---------- IPC: documents and brain files (paths only ever come from Windows dialogs) ----------
const DOC_FILTERS = [
  { name: 'Documents', extensions: ['pdf', 'docx', 'xlsx', 'xlsm', 'txt', 'md', 'csv'] },
  { name: 'PDF', extensions: ['pdf'] },
];
// E2E tests can't click a native dialog, so they may pre-answer it (only when CLAW_E2E is set).
function e2eDialogAnswer(kind) {
  if (!process.env.CLAW_E2E) return undefined;
  const v = process.env[`CLAW_E2E_${kind}`];
  return v === undefined ? undefined : v ? v.split('|') : [];
}

async function pickFiles(kind, options) {
  const canned = e2eDialogAnswer(kind);
  if (canned !== undefined) return canned;
  const res = await dialog.showOpenDialog(mainWindow, options);
  return res.canceled ? [] : res.filePaths;
}

ipcMain.handle('claw:open-document', async (event) => {
  if (!senderIs(event, mainWindow)) return { ok: false };
  const [file] = await pickFiles('OPEN_DOC', { title: 'Open a document for Claw to read', properties: ['openFile'], filters: DOC_FILTERS });
  if (!file) return { ok: false, cancelled: true };
  return backend.request('POST', '/documents/open', { path: file }, { internal: true });
});

// Exporting what Claw remembers. The renderer hands over text it already has;
// the file name is sanitised here and the person chooses where it goes.
ipcMain.handle('claw:save-text', async (event, suggestedName, text) => {
  if (!senderIs(event, mainWindow) || typeof text !== 'string') return { ok: false };
  if (text.length > 5_000_000) return { ok: false, message: 'That is too large to save this way.' };
  const base = String(suggestedName || 'export.json').replace(/[\\/:*?"<>|]/g, '_').slice(0, 120);
  const res = await dialog.showSaveDialog(mainWindow, {
    title: 'Save a copy',
    defaultPath: base,
    filters: [{ name: 'JSON', extensions: ['json'] }],
    properties: ['showOverwriteConfirmation'],
  });
  if (res.canceled || !res.filePath) return { ok: false, cancelled: true };
  try {
    fs.writeFileSync(res.filePath, text, 'utf8');
    return { ok: true, path: res.filePath };
  } catch (err) {
    return { ok: false, message: err.message };
  }
});

ipcMain.handle('claw:save-searchable', async (event, docId, suggestedName) => {
  if (!senderIs(event, mainWindow) || typeof docId !== 'string' || !/^[0-9a-f]{32}$/.test(docId)) return { ok: false };
  const base = String(suggestedName || 'document').replace(/\.pdf$/i, '').replace(/[\\/:*?"<>|]/g, '_').slice(0, 120);
  let out = (e2eDialogAnswer('SAVE_PDF') || [])[0];
  if (!out) {
    const res = await dialog.showSaveDialog(mainWindow, {
      title: 'Save a searchable copy',
      defaultPath: `${base} (searchable).pdf`,
      filters: [{ name: 'PDF', extensions: ['pdf'] }],
      properties: ['showOverwriteConfirmation'],
    });
    if (res.canceled || !res.filePath) return { ok: false, cancelled: true };
    out = res.filePath;
  }
  return backend.request('POST', `/documents/${docId}/searchable`, { out }, { internal: true });
});

ipcMain.handle('claw:show-file', async (event, docId) => {
  // Show a document the user opened in Claw (only paths of open documents are accepted).
  if (!senderIs(event, mainWindow) || typeof docId !== 'string' || !/^[0-9a-f]{32}$/.test(docId)) return { ok: false };
  const res = await backend.request('GET', `/documents/${docId}`);
  if (!res.ok) return { ok: false };
  shell.showItemInFolder(res.body.path);
  return { ok: true };
});

ipcMain.handle('claw:import-brain', async (event) => {
  if (!senderIs(event, mainWindow)) return { ok: false };
  const files = await pickFiles('IMPORT_BRAIN', {
    title: 'Choose a GGUF brain file (and its mmproj vision file, if it has one)',
    properties: ['openFile', 'multiSelections'],
    filters: [{ name: 'GGUF model', extensions: ['gguf'] }],
  });
  if (!files.length) return { ok: false, cancelled: true };
  const mmproj = files.find((f) => /mmproj/i.test(path.basename(f)));
  const model = files.find((f) => f !== mmproj);
  if (!model) return { ok: false, status: 422, body: { error: { message: 'Choose the brain file itself, not only its vision file.' } } };
  return backend.request('POST', '/brain/import', { path: model, mmproj: mmproj || null }, { internal: true });
});

ipcMain.handle('claw:confirm', async (event, title, detail, okLabel) => {
  if (!senderIs(event, mainWindow)) return false;
  if (process.env.CLAW_E2E) return process.env.CLAW_E2E_CONFIRM !== 'no';
  const res = await dialog.showMessageBox(mainWindow, {
    type: 'warning',
    title: 'S-CLAW',
    message: String(title).slice(0, 200),
    detail: String(detail || '').slice(0, 600),
    buttons: [String(okLabel || 'OK').slice(0, 40), 'Cancel'],
    defaultId: 1,
    cancelId: 1,
    noLink: true,
  });
  return res.response === 0;
});

// ---------- IPC: quick bar (narrower) ----------
let voiceEnabled = false;

// Electron allows permission requests by default. Claw refuses everything except
// the microphone, only for its own two windows, and only while voice input is on.
// Nothing here grants camera, location, screen capture or notifications-by-request.
function lockDownPermissions() {
  const ours = (contents) =>
    (quickBar && !quickBar.isDestroyed() && contents === quickBar.webContents) ||
    (mainWindow && !mainWindow.isDestroyed() && contents === mainWindow.webContents);
  const allow = (contents, permission) => ours(contents) && permission === 'media' && voiceEnabled;
  session.defaultSession.setPermissionRequestHandler((contents, permission, callback) => {
    callback(allow(contents, permission));
  });
  session.defaultSession.setPermissionCheckHandler((contents, permission) => allow(contents, permission));
}

// ---------- IPC: voice ----------
// The bar may ask whether voice is ready, and hand over one finished recording.
// It cannot start a download, change settings, or reach the network.
ipcMain.handle('voice:status', async (event) => {
  if (!fromOurWindows(event)) return null;
  const res = await backend.request('GET', '/speech');
  return res.ok ? res.body : { enabled: false, ready: false, reason: 'Claw is still starting.' };
});

ipcMain.handle('voice:stream-start', async (event, sampleRate) => {
  if (!fromOurWindows(event)) return { ok: false, message: 'Not allowed.' };
  const res = await backend.request('POST', '/speech/stream/start', { sample_rate: Number(sampleRate) || 16000 });
  if (!res.ok) {
    const err = (res.body && res.body.error) || {};
    return { ok: false, message: [err.message, err.hint].filter(Boolean).join(' ') || 'Could not start listening.' };
  }
  return { ok: true, streamId: String(res.body.stream_id || '') };
});

ipcMain.handle('voice:stream-chunk', async (event, streamId, pcm) => {
  if (!fromOurWindows(event)) return { ok: false, message: 'Not allowed.' };
  const res = await backend.sendAudioChunk(streamId, pcm instanceof Uint8Array ? pcm : new Uint8Array(pcm || []));
  if (!res.ok) {
    const err = (res.body && res.body.error) || {};
    return { ok: false, message: err.message || 'Lost the recording.' };
  }
  return { ok: true, text: String((res.body && res.body.text) || '') };
});

ipcMain.handle('voice:stream-finish', async (event, streamId) => {
  if (!fromOurWindows(event)) return { ok: false, message: 'Not allowed.' };
  const res = await backend.finishStream(streamId);
  if (!res.ok) {
    const err = (res.body && res.body.error) || {};
    return { ok: false, message: err.message || 'Recognition failed.' };
  }
  return { ok: true, text: String((res.body && res.body.text) || '') };
});

ipcMain.handle('voice:stream-cancel', async (event) => {
  if (!fromOurWindows(event)) return { ok: false };
  await backend.request('POST', '/speech/stream/cancel', {});
  return { ok: true };
});

ipcMain.handle('voice:transcribe', async (event, wav) => {
  if (!fromOurWindows(event)) return { ok: false, message: 'Not allowed.' };
  const bytes = wav instanceof Uint8Array ? wav : new Uint8Array(wav || []);
  const res = await backend.sendAudio(bytes);
  if (!res.ok) {
    const err = (res.body && res.body.error) || {};
    return { ok: false, message: [err.message, err.hint].filter(Boolean).join(' ') || 'Recognition failed.' };
  }
  return { ok: true, text: String((res.body && res.body.text) || '') };
});

ipcMain.handle('quickbar:run', async (event, task) => {
  if (!senderIs(event, quickBar)) return { ok: false };
  if (typeof task !== 'string' || task.trim().length < 3 || task.length > 4000) {
    return { ok: false, message: 'Describe the task in a few more words.' };
  }
  const res = await backend.request('POST', '/tasks/run', { task: task.trim() });
  if (!res.ok) return { ok: false, message: (res.body && res.body.error && res.body.error.message) || 'Could not start the task.' };
  watcher.nudge();
  broadcast('claw:task-started', { id: res.body.id });
  setTimeout(() => setQuickMode('collapsed'), 900);
  return { ok: true, id: res.body.id };
});
ipcMain.on('quickbar:mode', (event, mode) => {
  if (senderIs(event, quickBar) && (mode === 'expanded' || mode === 'collapsed')) setQuickMode(mode);
});
ipcMain.on('quickbar:open-app', (event) => {
  if (!senderIs(event, quickBar)) return;
  setQuickMode('collapsed');
  const s = watcher.status;
  showMain(s.taskId ? { taskId: s.taskId } : null);
});
ipcMain.on('quickbar:stop', (event) => {
  if (senderIs(event, quickBar)) stopCurrent();
});
// Only the quick bar may move the quick bar.
ipcMain.on('quickbar:drag-begin', (event) => {
  if (senderIs(event, quickBar)) beginQuickDrag();
});
ipcMain.on('quickbar:drag-to', (event, dx, dy) => {
  if (senderIs(event, quickBar) && Number.isFinite(dx) && Number.isFinite(dy)) moveQuickDrag(dx, dy);
});
ipcMain.on('quickbar:drag-end', (event) => {
  if (senderIs(event, quickBar)) endQuickDrag();
});
ipcMain.on('quickbar:reset-position', (event) => {
  if (senderIs(event, quickBar)) resetQuickPosition();
});

// ---------- Startup ----------
// Automatic recovery: if the agent process dies unexpectedly, restart it (at most 3 times in 5 minutes).
const crashTimes = [];
let restartTimer = null;

function onBackendStatus(s, instance) {
  broadcast('claw:backend-status', s);
  if (instance !== backend || s.state !== 'failed' || !/stopped unexpectedly/.test(s.message) || quitting) return;
  const now = Date.now();
  while (crashTimes.length && now - crashTimes[0] > 5 * 60 * 1000) crashTimes.shift();
  crashTimes.push(now);
  if (crashTimes.length > 3) {
    notify('Claw stopped working', 'It crashed several times. Open Claw to see what happened.', () => showMain());
    return;
  }
  const delay = 1000 * 2 ** (crashTimes.length - 1);
  broadcast('claw:backend-status', { state: 'starting', message: 'Restarting after a problem', detail: s.detail });
  clearTimeout(restartTimer);
  restartTimer = setTimeout(() => startBackend(true), delay);
}

async function startBackend(restart = false) {
  if (restart && backend) backend.stop();
  const instance = new Backend({ backendDir: BACKEND_DIR, resourcesDir: RESOURCES_DIR, onStatus: (s) => onBackendStatus(s, instance) });
  backend = instance;
  await instance.start();
  if (instance.status.state === 'ready') await loadDesktopSettings();
}

app.whenReady().then(async () => {
  createMainWindow();
  createQuickBar();
  createTray();
  // Calendar reminders. Clicking one opens S-CLAW on the task view, where the
  // calendar lives; the notification itself is the whole point of the feature.
  reminders = new ReminderWatcher(() => backend, {
    show: (item, text) => notify(text.title, text.body, () => showMain({})),
  });
  // The morning briefing. Only while the app runs: there is no service behind it.
  briefing = new BriefWatcher(() => backend, {
    at: () => desktop.brief_at,
    lastDay: () => lastBriefDay,
    remember: (day) => { lastBriefDay = day; },
    show: (body) => notify(`Today — ${body.headline}`,
      (body.agenda || []).slice(0, 3).map((i) => `${i.at}  ${i.summary}`).join('\n')
        || 'Nothing in your calendar today.',
      () => showMain({})),
  });
  watcher = new AgentWatcher(() => backend, {
    onChange: (status) => {
      broadcast('claw:agent-status', status);
      refreshTray(status);
      updateAwake();
    },
    onApprovalNeeded: (a) => {
      // A request for a password or a code is not an approval, and a notification
      // that says "allow or deny" is the wrong thing to read on a phone screen
      // when what is actually wanted is for you to go and sign in.
      if (a.kind === 'needs_you') {
        notify('S-CLAW needs you', `${a.description || 'Something needs you'} — open S-CLAW to carry on.`,
          () => showMain({ taskId: a.task_id }));
        return;
      }
      notify('S-CLAW needs your OK', `${a.description || a.tool} — open S-CLAW to allow or deny.`, () => showMain({ taskId: a.task_id }));
    },
    onTaskEnded: (t) => {
      const parts = [];
      if (t.counts.verified) parts.push(`${t.counts.verified} done`);
      if (t.counts.failed) parts.push(`${t.counts.failed} failed`);
      let body = t.status === 'completed' ? (t.answer || parts.join(', ') || 'Done.') : t.error || parts.join(', ');
      if (t.files && t.files.length) body = `${t.files.length} file(s) ready. ${body}`;
      notify(`${t.label}: ${t.title.slice(0, 60)}`, String(body).slice(0, 200), () => showMain({ taskId: t.id }));
    },
  });
  if (!globalShortcut.register(QUICK_SHORTCUT, () => openQuickBar())) {
    console.warn('Could not register', QUICK_SHORTCUT);
  }
  globalShortcut.register(STOP_SHORTCUT, async () => {
    const s = watcher && watcher.status;
    if (!s || !s.taskId) return;
    await stopCurrent();
    notify('Claw stopped', 'You pressed the stop shortcut. The task was stopped.');
  });
  nativeTheme.on('updated', () => {
    const c = overlayColors();
    if (mainWindow && IS_WIN) mainWindow.setTitleBarOverlay({ color: c.overlay, symbolColor: c.symbols });
  });
  nativeTheme.on('updated', () => { if ((desktop.theme || 'system') === 'system') paintWindows(); });
  lockDownPermissions();
  await startBackend();
  watcher.start();
  reminders.start();
  briefing.start();
  // Push-to-talk only exists when the user has turned voice on and picked that mode.
  try {
    const v = await backend.request('GET', '/speech');
    voiceEnabled = !!(v.ok && v.body && v.body.enabled);
    if (v.ok && v.body && v.body.enabled && v.body.push_to_talk) {
      registerPushToTalk(String(v.body.push_to_talk).replace('Ctrl', 'CommandOrControl'));
    }
  } catch {
    /* voice is optional: the bar still types */
  }
  // WhatsApp: a Windows notification when a check (manual or background) finds chats with new messages.
  let waSeq = null;
  setInterval(async () => {
    if (!backend || backend.status.state !== 'ready') return;
    const res = await backend.request('GET', '/messages/whatsapp');
    if (!res.ok) return;
    const { seq, result } = res.body;
    if (waSeq === null) waSeq = seq;
    if (seq === waSeq) return;
    waSeq = seq;
    if (!result || result.state !== 'ok' || !result.new_count) return;
    const settings = await backend.request('GET', '/settings');
    if (settings.ok && settings.body.settings.messages && settings.body.settings.messages.notify === false) return;
    const names = result.unread.filter((c) => c.new_since_last_check).map((c) => c.name);
    notify('New WhatsApp messages', `${names.slice(0, 4).join(', ')}${names.length > 4 ? ` and ${names.length - 4} more` : ''}`, () => showMain());
  }, 20000);
});

app.on('window-all-closed', () => {
  if (!tray) app.quit();
});
app.on('before-quit', () => {
  quitting = true;
  if (watcher) watcher.stop();
  if (awakeBlocker !== null) powerSaveBlocker.stop(awakeBlocker);
  if (backend) backend.stop();
});
let pttHeld = false;
let pttTimer = null;

function registerPushToTalk(accelerator) {
  if (!accelerator) return;
  const ok = globalShortcut.register(accelerator, () => {
    if (!quickBar || quickBar.isDestroyed()) return;
    if (!pttHeld) {
      pttHeld = true;
      openQuickBar();
      quickBar.webContents.send('voice:push-to-talk', true);
    }
    clearTimeout(pttTimer);
    // No key-up event exists for a global shortcut: the gap between auto-repeats
    // ending is what tells us the key was let go.
    pttTimer = setTimeout(() => {
      pttHeld = false;
      if (quickBar && !quickBar.isDestroyed()) quickBar.webContents.send('voice:push-to-talk', false);
    }, 400);
  });
  if (!ok) console.warn(`Could not register the push-to-talk shortcut ${accelerator}.`);
}

app.on('will-quit', () => globalShortcut.unregisterAll());
