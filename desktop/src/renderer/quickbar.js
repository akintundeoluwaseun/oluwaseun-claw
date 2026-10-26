'use strict';

const q = window.quick;
const $ = (id) => document.getElementById(id);
let phase = 'idle';
let shortcut = 'Ctrl+Shift+Space';
let stopKeys = 'Ctrl+Alt+X';

function setMode(mode) {
  document.body.dataset.mode = mode;
  if (mode === 'expanded') {
    $('task').focus();
    $('task').select();
  }
}

function renderStatus(s) {
  phase = s && s.phase ? s.phase : 'idle';
  document.body.dataset.phase = phase;
  const pill = $('pill');
  if (phase === 'working') {
    $('pill-text').textContent = s.activity || 'Working';
    $('pill-meta').textContent = s.usingInput ? `${stopKeys} stops` : s.step ? `step ${s.step}` : '';
    pill.setAttribute('aria-label', `Claw is working: ${s.activity}. Open Claw`);
  } else if (phase === 'attention') {
    $('pill-text').textContent = 'Needs your OK';
    $('pill-meta').textContent = 'Review';
    pill.setAttribute('aria-label', 'Claw is waiting for your approval. Open Claw');
  } else if (phase === 'offline') {
    $('pill-text').textContent = 'Claw is starting';
    $('pill-meta').textContent = '';
  } else {
    $('pill-text').textContent = 'Ask Claw';
    $('pill-meta').textContent = shortcut;
    pill.setAttribute('aria-label', 'Give Claw a task');
  }
}

function foot(text, tone) {
  $('foot-text').textContent = text;
  if (tone) $('panel-foot').dataset.tone = tone;
  else delete $('panel-foot').dataset.tone;
}

$('pill').addEventListener('click', () => {
  if (phase === 'working' || phase === 'attention') q.openApp();
  else q.setMode('expanded');
});
$('pill-stop').addEventListener('click', () => q.stop());
$('open-app').addEventListener('click', () => q.openApp());
$('task').addEventListener('input', () => {
  $('run').disabled = $('task').value.trim().length < 3;
  foot('Claw asks before it saves files or changes anything online.');
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') q.setMode('collapsed');
});
$('panel').addEventListener('submit', async (e) => {
  e.preventDefault();
  const task = $('task').value.trim();
  if (task.length < 3) return;
  $('run').disabled = true;
  foot('Starting…');
  const res = await q.run(task);
  if (res && res.ok) {
    $('task').value = '';
    foot('On it. You will get a notification when it is done.', 'ok');
  } else {
    $('run').disabled = false;
    foot((res && res.message) || 'Could not start the task.', 'bad');
  }
});

q.onMode((mode) => {
  setMode(mode);
  if (mode === 'collapsed') foot('Claw asks before it saves files or changes anything online.');
});
q.onStatus(renderStatus);
q.stopShortcut().then((k) => {
  stopKeys = k || stopKeys;
});
q.shortcut().then((s) => {
  shortcut = s || shortcut;
  q.status().then(renderStatus);
});

// ---------- voice ----------
// Records only while the user holds or clicks the microphone, encodes one WAV and
// hands it to the main process. The renderer has connect-src 'none': it cannot send
// audio anywhere itself. The microphone track is stopped the moment recording ends,
// so Windows stops showing the in-use indicator.
const voice = {
  stream: null,
  ctx: null,
  node: null,
  chunks: [],
  rate: 16000,
  recording: false,
  busy: false,
  enabled: false,
};

function setListening(on, text) {
  voice.recording = on;
  document.body.dataset.listening = on ? 'yes' : 'no';
  $('listening').hidden = !on && !text;
  $('listening-text').textContent = text || 'Listening…';
  $('mic').setAttribute('aria-pressed', on ? 'true' : 'false');
}

async function startRecording() {
  if (voice.recording || voice.busy || !voice.enabled) return;
  try {
    voice.stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    });
  } catch (err) {
    foot(err && err.name === 'NotAllowedError'
      ? 'Claw needs permission to use the microphone. Allow it in Windows privacy settings.'
      : 'No microphone was found.', 'bad');
    return;
  }
  voice.ctx = new AudioContext();
  voice.rate = voice.ctx.sampleRate;
  voice.chunks = [];
  const src = voice.ctx.createMediaStreamSource(voice.stream);
  // ScriptProcessor is deprecated but needs no extra file in the packaged app;
  // one mono buffer of raw samples is all we collect.
  voice.node = voice.ctx.createScriptProcessor(4096, 1, 1);
  voice.node.onaudioprocess = (e) => {
    if (voice.recording) voice.chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
  };
  src.connect(voice.node);
  voice.node.connect(voice.ctx.destination);
  setListening(true);
}

function releaseMic() {
  if (voice.node) { voice.node.disconnect(); voice.node.onaudioprocess = null; voice.node = null; }
  if (voice.ctx) { voice.ctx.close().catch(() => {}); voice.ctx = null; }
  if (voice.stream) { voice.stream.getTracks().forEach((t) => t.stop()); voice.stream = null; }
}

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
  const ascii = (off, s) => { for (let k = 0; k < s.length; k += 1) view.setUint8(off + k, s.charCodeAt(k)); };
  ascii(0, 'RIFF'); view.setUint32(4, 36 + pcm.length * 2, true); ascii(8, 'WAVE');
  ascii(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, rate, true); view.setUint32(28, rate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  ascii(36, 'data'); view.setUint32(40, pcm.length * 2, true);
  new Int16Array(buf, 44).set(pcm);
  return new Uint8Array(buf);
}

async function stopRecording(cancelled) {
  if (!voice.recording) return;
  const chunks = voice.chunks;
  const rate = voice.rate;
  voice.chunks = [];
  setListening(false);
  releaseMic();                       // the microphone is freed before recognition runs
  if (cancelled || !chunks.length) { $('listening').hidden = true; return; }

  voice.busy = true;
  $('listening').hidden = false;
  $('listening-text').textContent = 'Working out what you said…';
  try {
    const res = await q.transcribe(encodeWav(chunks, rate));
    if (res && res.ok && res.text) {
      // The words go in the field. Nothing runs until the user presses Start.
      $('task').value = res.text;
      $('task').focus();
      $('run').disabled = $('task').value.trim().length < 3;
      foot('Check the words, then press Start.');
    } else {
      foot((res && res.message) || 'Claw could not make out any words.', 'bad');
    }
  } finally {
    voice.busy = false;
    $('listening').hidden = true;
  }
}

$('mic').addEventListener('click', () => (voice.recording ? stopRecording(false) : startRecording()));
$('mic-cancel').addEventListener('click', () => stopRecording(true));
q.onPushToTalk((down) => {
  if (down) startRecording();
  else stopRecording(false);
});

q.voiceStatus().then((s) => {
  voice.enabled = !!(s && s.ready);
  $('mic').hidden = !(s && s.enabled);
  if (s && s.enabled && !s.ready) {
    $('mic').disabled = true;
    $('mic').title = s.reason || 'Voice input is not ready';
  }
});

window.addEventListener('beforeunload', releaseMic);
