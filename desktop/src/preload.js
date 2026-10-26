'use strict';
// Narrow bridge between the main window UI and the main process. The UI never
// sees the session token and cannot open arbitrary connections.

const { contextBridge, ipcRenderer } = require('electron');

function subscribe(channel, callback) {
  const listener = (_event, payload) => callback(payload);
  ipcRenderer.on(channel, listener);
  return () => ipcRenderer.removeListener(channel, listener);
}

contextBridge.exposeInMainWorld('claw', {
  api: (method, route, body) => ipcRenderer.invoke('claw:api', method, route, body),
  backendStatus: () => ipcRenderer.invoke('claw:backend-status'),
  agentStatus: () => ipcRenderer.invoke('claw:agent-status'),
  restartBackend: () => ipcRenderer.invoke('claw:restart-backend'),
  pickFolder: () => ipcRenderer.invoke('claw:pick-folder'),
  openOutput: (taskId, path, how) => ipcRenderer.invoke('claw:open-output', taskId, path, how),
  shortcut: () => ipcRenderer.invoke('claw:shortcut'),
  stopShortcut: () => ipcRenderer.invoke('claw:stop-shortcut'),
  platform: process.platform,
  onBackendStatus: (cb) => subscribe('claw:backend-status', cb),
  onAgentStatus: (cb) => subscribe('claw:agent-status', cb),
  onTaskStarted: (cb) => subscribe('claw:task-started', cb),
  onNavigate: (cb) => subscribe('claw:navigate', cb),
  onSettingsChanged: (cb) => subscribe('claw:settings-changed', cb),
});
