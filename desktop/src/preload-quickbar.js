'use strict';
// The quick bar can only start a task, stop it, change its own size, open the
// main window, read the agent's status, and hand over one finished recording
// for recognition. Nothing else. It cannot reach the network itself.

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('quick', {
  run: (task) => ipcRenderer.invoke('quickbar:run', task),
  setMode: (mode) => ipcRenderer.send('quickbar:mode', mode),
  openApp: () => ipcRenderer.send('quickbar:open-app'),
  stop: () => ipcRenderer.send('quickbar:stop'),
  status: () => ipcRenderer.invoke('claw:agent-status'),
  shortcut: () => ipcRenderer.invoke('claw:shortcut'),
  stopShortcut: () => ipcRenderer.invoke('claw:stop-shortcut'),
  voiceStatus: () => ipcRenderer.invoke('voice:status'),
  // wav is a Uint8Array of one finished recording; the reply is the recognised text.
  transcribe: (wav) => ipcRenderer.invoke('voice:transcribe', wav),
  onPushToTalk: (cb) => {
    const l = (_e, down) => cb(down);
    ipcRenderer.on('voice:push-to-talk', l);
    return () => ipcRenderer.removeListener('voice:push-to-talk', l);
  },
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
