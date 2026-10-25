'use strict';

const { app, BrowserWindow, dialog, ipcMain, shell } = require('electron');
const path = require('node:path');
const { Backend } = require('./backend');

const BACKEND_DIR = process.env.CLAW_BACKEND_DIR || path.resolve(__dirname, '..', '..', 'backend');

let mainWindow = null;
let backend = null;

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });
}

function sendStatus(status) {
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send('claw:backend-status', status);
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1240,
    height: 820,
    minWidth: 900,
    minHeight: 600,
    title: 'Oluwaseun Claw',
    backgroundColor: '#0e1116',
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
      spellcheck: true,
    },
  });
  mainWindow.removeMenu();
  mainWindow.once('ready-to-show', () => mainWindow.show());

  // The UI is a local page only: no navigation, no new windows.
  mainWindow.webContents.on('will-navigate', (e) => e.preventDefault());
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https:\/\//.test(url)) shell.openExternal(url);
    return { action: 'deny' };
  });

  mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'));
}

function fromOurWindow(event) {
  return mainWindow && event.sender === mainWindow.webContents;
}

ipcMain.handle('claw:api', async (event, method, route, body) => {
  if (!fromOurWindow(event)) return { ok: false, status: 403, body: { error: { message: 'Not allowed.' } } };
  return backend.request(method, route, body);
});

ipcMain.handle('claw:backend-status', (event) => (fromOurWindow(event) ? backend.status : null));

ipcMain.handle('claw:pick-folder', async (event) => {
  if (!fromOurWindow(event)) return null;
  const res = await dialog.showOpenDialog(mainWindow, {
    title: 'Choose a folder the agent may use',
    properties: ['openDirectory'],
  });
  return res.canceled || !res.filePaths.length ? null : res.filePaths[0];
});

ipcMain.handle('claw:restart-backend', async (event) => {
  if (!fromOurWindow(event)) return null;
  backend.stop();
  backend = new Backend({ backendDir: BACKEND_DIR, onStatus: sendStatus });
  await backend.start();
  return backend.status;
});

app.whenReady().then(async () => {
  backend = new Backend({ backendDir: BACKEND_DIR, onStatus: sendStatus });
  createWindow();
  await backend.start();
});

app.on('window-all-closed', () => app.quit());
app.on('before-quit', () => backend && backend.stop());
