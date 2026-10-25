'use strict';
// Narrow bridge between the UI and the main process. The UI never sees the
// session token and cannot open arbitrary connections.

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('claw', {
  api: (method, route, body) => ipcRenderer.invoke('claw:api', method, route, body),
  backendStatus: () => ipcRenderer.invoke('claw:backend-status'),
  restartBackend: () => ipcRenderer.invoke('claw:restart-backend'),
  pickFolder: () => ipcRenderer.invoke('claw:pick-folder'),
  onBackendStatus: (callback) => {
    const listener = (_event, status) => callback(status);
    ipcRenderer.on('claw:backend-status', listener);
    return () => ipcRenderer.removeListener('claw:backend-status', listener);
  },
});
