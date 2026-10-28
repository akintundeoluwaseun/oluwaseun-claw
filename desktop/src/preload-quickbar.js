'use strict';
// The quick bar can only start a task, stop it, change its own size, move itself,
// open the main window, read the agent's status, and hand over one finished
// recording for recognition. Nothing else. It cannot reach the network itself.

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('quick', {
  run: (task) => ipcRenderer.invoke('quickbar:run', task),
  setMode: (mode) => ipcRenderer.send('quickbar:mode', mode),
  openApp: () => ipcRenderer.send('quickbar:open-app'),
  hideBar: () => ipcRenderer.send('quickbar:hide'),
  stop: () => ipcRenderer.send('quickbar:stop'),
  // Moving the bar: the renderer decides what is a drag, the main process moves the window.
  dragBegin: () => ipcRenderer.send('quickbar:drag-begin'),
  dragTo: (dx, dy) => ipcRenderer.send('quickbar:drag-to', dx, dy),
  dragEnd: () => ipcRenderer.send('quickbar:drag-end'),
  resetPosition: () => ipcRenderer.send('quickbar:reset-position'),
  status: () => ipcRenderer.invoke('claw:agent-status'),
  shortcut: () => ipcRenderer.invoke('claw:shortcut'),
  stopShortcut: () => ipcRenderer.invoke('claw:stop-shortcut'),
  voiceStatus: () => ipcRenderer.invoke('voice:status'),
  // wav is a Uint8Array of one finished recording; the reply is the recognised text.
  transcribe: (wav) => ipcRenderer.invoke('voice:transcribe', wav),
  // Live: open a recording, push raw PCM as it arrives, close it.
  streamStart: (rate) => ipcRenderer.invoke('voice:stream-start', rate),
  streamChunk: (id, pcm) => ipcRenderer.invoke('voice:stream-chunk', id, pcm),
  streamFinish: (id) => ipcRenderer.invoke('voice:stream-finish', id),
  streamCancel: () => ipcRenderer.invoke('voice:stream-cancel'),
  onPushToTalk: (cb) => {
    const l = (_e, down) => cb(down);
    ipcRenderer.on('voice:push-to-talk', l);
    return () => ipcRenderer.removeListener('voice:push-to-talk', l);
  },
  onTheme: (cb) => {
    const listener = (_e, theme) => cb(theme);
    ipcRenderer.on('claw:theme', listener);
    return () => ipcRenderer.removeListener('claw:theme', listener);
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
