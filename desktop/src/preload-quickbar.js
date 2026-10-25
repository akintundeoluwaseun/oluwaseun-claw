'use strict';
// The quick bar can only start a task, stop it, change its own size, open the
// main window, and read the agent's status. Nothing else.

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('quick', {
  run: (task) => ipcRenderer.invoke('quickbar:run', task),
  setMode: (mode) => ipcRenderer.send('quickbar:mode', mode),
  openApp: () => ipcRenderer.send('quickbar:open-app'),
  stop: () => ipcRenderer.send('quickbar:stop'),
  status: () => ipcRenderer.invoke('claw:agent-status'),
  shortcut: () => ipcRenderer.invoke('claw:shortcut'),
  onStatus: (cb) => {
    const l = (_e, s) => cb(s);
    ipcRenderer.on('claw:agent-status', l);
    return () => ipcRenderer.removeListener('claw:agent-status', l);
  },
  onMode: (cb) => {
    const l = (_e, m) => cb(m);
    ipcRenderer.on('quickbar:mode', l);
    return () => ipcRenderer.removeListener('quickbar:mode', l);
  },
});
