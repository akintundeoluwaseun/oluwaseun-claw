'use strict';

const {
  app, BrowserWindow, Menu, Notification, Tray, dialog, globalShortcut, ipcMain,
  nativeImage, nativeTheme, powerSaveBlocker, screen, shell,
} = require('electron');
const path = require('node:path');
const { Backend } = require('./backend');
const { AgentWatcher } = require('./watcher');

const BACKEND_DIR = process.env.CLAW_BACKEND_DIR || path.resolve(__dirname, '..', '..', 'backend');
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
let quitting = false;
let awakeBlocker = null;
let trayHintShown = false;
let desktop = { start_with_windows: false, show_quick_bar: true, keep_awake_while_running: true, notifications: true, close_to_tray: true };

if (process.env.CLAW_E2E) app.setPath('userData', path.join(require('node:os').tmpdir(), `claw-e2e-${process.pid}`));
if (IS_WIN) app.setAppUserModelId('com.oluwaseun.claw'); // required for Windows notifications

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

function createMainWindow() {
  const c = overlayColors();
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 840,
    minWidth: 960,
    minHeight: 620,
    title: 'Oluwaseun Claw',
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

function quickBounds(mode) {
  const { workArea } = screen.getPrimaryDisplay();
  const size = QB[mode];
  return { x: Math.round(workArea.x + (workArea.width - size.w) / 2), y: workArea.y + 10, width: size.w, height: size.h };
}

function createQuickBar() {
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
  tray.setToolTip('Oluwaseun Claw — ready');
  tray.setContextMenu(buildTrayMenu());
  tray.on('click', () => showMain());
}

function refreshTray(status) {
  if (!tray) return;
  const kind = status.phase === 'attention' ? 'attention' : status.phase === 'working' ? 'busy' : 'idle';
  tray.setImage(trayImage(kind));
  const tip = status.phase === 'working' ? `Claw — ${status.activity}` : status.phase === 'attention' ? 'Claw — needs your OK' : 'Oluwaseun Claw — ready';
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
ipcMain.handle('claw:shortcut', (event) => (fromOurWindows(event) ? QUICK_SHORTCUT.replace('CommandOrControl', 'Ctrl') : ''));
ipcMain.handle('claw:stop-shortcut', (event) => (fromOurWindows(event) ? STOP_SHORTCUT.replace('CommandOrControl', 'Ctrl') : ''));

// ---------- IPC: quick bar (narrower) ----------
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

// ---------- Startup ----------
async function startBackend(restart = false) {
  if (restart && backend) backend.stop();
  backend = new Backend({ backendDir: BACKEND_DIR, onStatus: (s) => broadcast('claw:backend-status', s) });
  await backend.start();
  if (backend.status.state === 'ready') await loadDesktopSettings();
}

app.whenReady().then(async () => {
  createMainWindow();
  createQuickBar();
  createTray();
  watcher = new AgentWatcher(() => backend, {
    onChange: (status) => {
      broadcast('claw:agent-status', status);
      refreshTray(status);
      updateAwake();
    },
    onApprovalNeeded: (a) => {
      notify('Claw needs your OK', `${a.description || a.tool} — open Claw to allow or deny.`, () => showMain({ taskId: a.task_id }));
    },
    onTaskEnded: (t) => {
      const parts = [];
      if (t.counts.verified) parts.push(`${t.counts.verified} done`);
      if (t.counts.failed) parts.push(`${t.counts.failed} failed`);
      const body = t.status === 'completed' ? (t.answer || parts.join(', ') || 'Done.') : t.error || parts.join(', ');
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
  await startBackend();
  watcher.start();
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
app.on('will-quit', () => globalShortcut.unregisterAll());
