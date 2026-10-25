'use strict';
// Starts, watches, and talks to the Python backend. Runs only in the Electron main process.

const { spawn } = require('node:child_process');
const crypto = require('node:crypto');
const fs = require('node:fs');
const net = require('node:net');
const path = require('node:path');

const IS_WIN = process.platform === 'win32';

// Only these routes may be called from the UI. Anything else is refused here,
// before it ever reaches the backend.
const ALLOWED_ROUTES = [
  ['GET', /^\/health$/],
  ['GET', /^\/settings$/],
  ['PUT', /^\/settings$/],
  ['GET', /^\/models\/status$/],
  ['POST', /^\/models\/probe$/],
  ['POST', /^\/tasks\/plan$/],
  ['GET', /^\/tasks(\?[\w=&%.+-]*)?$/],
  ['GET', /^\/tasks\/[0-9a-f]{32}$/],
  ['POST', /^\/tasks\/run$/],
  ['POST', /^\/tasks\/[0-9a-f]{32}\/cancel$/],
  ['GET', /^\/tasks\/[0-9a-f]{32}\/events(\?after=\d{1,9})?$/],
  ['GET', /^\/approvals$/],
  ['POST', /^\/approvals\/[0-9a-f]{32}$/],
  ['GET', /^\/runner$/],
];

function isAllowedRoute(method, route) {
  if (typeof method !== 'string' || typeof route !== 'string' || route.length > 300) return false;
  return ALLOWED_ROUTES.some(([m, re]) => m === method && re.test(route));
}

function findFreePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.unref();
    srv.on('error', reject);
    srv.listen(0, '127.0.0.1', () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
  });
}

function resolvePython(backendDir) {
  if (process.env.CLAW_PYTHON) return { cmd: process.env.CLAW_PYTHON, args: [] };
  const venv = IS_WIN
    ? path.join(backendDir, '.venv', 'Scripts', 'python.exe')
    : path.join(backendDir, '.venv', 'bin', 'python');
  if (fs.existsSync(venv)) return { cmd: venv, args: [] };
  return IS_WIN ? { cmd: 'py', args: ['-3'] } : { cmd: 'python3', args: [] };
}

class Backend {
  constructor({ backendDir, onStatus }) {
    this.backendDir = backendDir;
    this.onStatus = onStatus || (() => {});
    this.token = crypto.randomBytes(32).toString('base64url');
    this.child = null;
    this.port = null;
    this.stderrTail = [];
    this.status = { state: 'starting', message: 'Starting the agent…' };
    this.stopping = false;
  }

  setStatus(state, message, detail) {
    this.status = { state, message, detail: detail || '' };
    this.onStatus(this.status);
  }

  async start() {
    if (!fs.existsSync(path.join(this.backendDir, 'claw', 'main.py'))) {
      this.setStatus('failed', 'The agent files are missing.', `Expected them in ${this.backendDir}`);
      return;
    }
    this.port = await findFreePort();
    const py = resolvePython(this.backendDir);
    this.setStatus('starting', 'Starting the agent…');
    try {
      this.child = spawn(py.cmd, [...py.args, '-m', 'claw.main', '--port', String(this.port)], {
        cwd: this.backendDir,
        env: { ...process.env, CLAW_SESSION_TOKEN: this.token, PYTHONUNBUFFERED: '1', PYTHONIOENCODING: 'utf-8' },
        stdio: ['ignore', 'pipe', 'pipe'],
        windowsHide: true,
      });
    } catch (err) {
      this.setStatus('failed', 'Could not start Python.', String(err.message || err));
      return;
    }
    this.child.on('error', (err) => {
      const hint = err.code === 'ENOENT'
        ? `Python was not found (${py.cmd}). Install Python 3.12 and run scripts\\setup.ps1, or set CLAW_PYTHON.`
        : String(err.message || err);
      this.setStatus('failed', 'Could not start the agent.', hint);
    });
    const keepTail = (chunk) => {
      for (const line of chunk.toString('utf8').split(/\r?\n/)) {
        if (!line.trim()) continue;
        this.stderrTail.push(line.includes(this.token) ? '[line hidden: contained session token]' : line);
        if (this.stderrTail.length > 40) this.stderrTail.shift();
      }
    };
    this.child.stdout.on('data', keepTail);
    this.child.stderr.on('data', keepTail);
    this.child.on('exit', (code, signal) => {
      this.child = null;
      if (this.stopping) return;
      this.setStatus('failed', 'The agent stopped unexpectedly.', `exit code ${code ?? signal}\n${this.lastErrors()}`);
    });
    await this.waitUntilHealthy(30000);
  }

  lastErrors() {
    return this.stderrTail.slice(-8).join('\n');
  }

  async waitUntilHealthy(timeoutMs) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      if (!this.child) return; // exit handler already reported the failure
      try {
        const res = await fetch(`http://127.0.0.1:${this.port}/health`, { signal: AbortSignal.timeout(2000) });
        if (res.ok) {
          const body = await res.json();
          this.setStatus('ready', 'Agent running', `v${body.version} · Python ${body.python}`);
          return;
        }
      } catch {
        /* not up yet */
      }
      await new Promise((r) => setTimeout(r, 300));
    }
    this.setStatus('failed', 'The agent did not start in time.', this.lastErrors());
  }

  async request(method, route, body) {
    if (!isAllowedRoute(method, route)) {
      return { ok: false, status: 400, body: { error: { code: 'blocked_route', message: 'That request is not allowed.' } } };
    }
    if (this.status.state !== 'ready') {
      return { ok: false, status: 503, body: { error: { code: 'backend_unavailable', message: this.status.message, hint: this.status.detail } } };
    }
    const timeoutMs = route.startsWith('/tasks/plan') ? 15 * 60 * 1000 : 30000;
    try {
      const res = await fetch(`http://127.0.0.1:${this.port}${route}`, {
        method,
        headers: { 'X-Claw-Token': this.token, 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: AbortSignal.timeout(timeoutMs),
      });
      let data = null;
      try {
        data = await res.json();
      } catch {
        data = { error: { code: 'bad_reply', message: 'The agent sent a reply that could not be read.' } };
      }
      return { ok: res.ok, status: res.status, body: data };
    } catch (err) {
      const timedOut = err && err.name === 'TimeoutError';
      return {
        ok: false,
        status: 0,
        body: { error: { code: timedOut ? 'timeout' : 'network', message: timedOut ? 'The agent took too long to answer.' : 'Could not reach the agent.' } },
      };
    }
  }

  stop() {
    this.stopping = true;
    if (this.child) {
      this.child.kill();
      this.child = null;
    }
  }
}

module.exports = { Backend, isAllowedRoute, resolvePython };
