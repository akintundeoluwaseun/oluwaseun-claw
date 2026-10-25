'use strict';
// Follows the agent from the main process, so notifications, the tray icon and
// the quick bar stay correct even when every window is hidden.

const TOOL_ACTIVITY = {
  web_search: 'Searching the web',
  open_url: 'Opening a page',
  open_search_result: 'Opening a result',
  read_page: 'Reading the page',
  extract_links: 'Collecting links',
  click_link: 'Following a link',
  click_button: 'Clicking a button',
  list_tabs: 'Checking tabs',
  new_tab: 'Opening a tab',
  switch_tab: 'Switching tabs',
  close_tab: 'Closing a tab',
  search_browser_history: 'Searching your history',
  save_links: 'Saving links',
  list_folder: 'Looking in a folder',
  read_text_file: 'Reading a file',
  find_files: 'Finding files',
  list_windows: 'Checking open windows',
  focus_window: 'Switching windows',
  launch_app: 'Opening an app',
  look_at_window: 'Looking at a window',
  click_control: 'Clicking in an app',
  type_into: 'Typing in an app',
  type_text: 'Typing in an app',
  press_keys: 'Pressing keys',
  read_control: 'Reading an app',
  take_screenshot: 'Taking a screenshot',
  describe_screen: 'Looking at the screen',
  click_at: 'Clicking on screen',
};
const USES_INPUT = new Set(['focus_window', 'launch_app', 'click_control', 'type_into', 'type_text', 'press_keys', 'click_at']);

const OUTCOME_TEXT = {
  completed: 'Finished',
  failed: 'Could not finish',
  stopped: 'Stopped',
  cancelled: 'Stopped by you',
  incomplete: 'Ran out of steps',
  interrupted: 'Interrupted',
};

class AgentWatcher {
  constructor(backendRef, { onChange, onApprovalNeeded, onTaskEnded }) {
    this.backendRef = backendRef; // () => Backend
    this.onChange = onChange;
    this.onApprovalNeeded = onApprovalNeeded;
    this.onTaskEnded = onTaskEnded;
    this.timer = null;
    this.status = { phase: 'idle', taskId: null, title: '', activity: '', step: 0, approval: null };
    this.after = 0;
    this.seenApprovals = new Set();
  }

  start() {
    if (this.timer) return;
    const loop = async () => {
      try {
        await this.tick();
      } catch {
        /* backend restarting; try again next tick */
      }
      this.timer = setTimeout(loop, this.status.phase === 'idle' ? 1500 : 700);
    };
    loop();
  }

  stop() {
    clearTimeout(this.timer);
    this.timer = null;
  }

  nudge() {
    // Called right after the user starts a task, so the UI reacts at once.
    this.stop();
    this.start();
  }

  set(next) {
    const before = JSON.stringify(this.status);
    this.status = { ...this.status, ...next };
    if (JSON.stringify(this.status) !== before) this.onChange(this.status);
  }

  async tick() {
    const backend = this.backendRef();
    if (!backend || backend.status.state !== 'ready') {
      this.set({ phase: 'offline' });
      return;
    }
    const runner = await backend.request('GET', '/runner');
    if (!runner.ok) return;
    const { busy, current_id: currentId } = runner.body;

    if (!busy) {
      if (this.status.taskId && this.status.phase !== 'idle') {
        const ended = this.status.taskId;
        const res = await backend.request('GET', `/tasks/${ended}`);
        if (res.ok) {
          const t = res.body;
          this.onTaskEnded({
            id: ended,
            title: t.task_text,
            status: t.status,
            label: OUTCOME_TEXT[t.status] || t.status,
            error: t.error,
            answer: t.result && t.result.final_answer,
            counts: (t.result && t.result.counts) || {},
          });
        }
      }
      this.after = 0;
      this.set({ phase: 'idle', taskId: null, title: '', activity: '', step: 0, approval: null });
      return;
    }

    if (currentId !== this.status.taskId) {
      this.after = 0;
      const t = await backend.request('GET', `/tasks/${currentId}`);
      this.set({ taskId: currentId, title: t.ok ? t.body.task_text : 'Task', activity: 'Planning', step: 0 });
    }
    const ev = await backend.request('GET', `/tasks/${currentId}/events?after=${this.after}`);
    if (!ev.ok) return;
    let { activity, step } = this.status;
    for (const e of ev.body.events) {
      this.after = Math.max(this.after, e.id);
      const d = e.data || {};
      if (e.kind === 'model_call') activity = 'Planning';
      if (e.kind === 'planned') activity = 'Thinking';
      if (e.kind === 'requested' || e.kind === 'attempted') {
        activity = TOOL_ACTIVITY[d.tool] || 'Working';
        step = d.step || step;
        this.usingInput = USES_INPUT.has(d.tool);
      }
    }
    const approval = (ev.body.approvals || [])[0] || null;
    if (approval && !this.seenApprovals.has(approval.id)) {
      this.seenApprovals.add(approval.id);
      this.onApprovalNeeded({ ...approval, title: this.status.title });
    }
    this.set({
      phase: approval ? 'attention' : 'working', activity, step, usingInput: !!this.usingInput && !approval,
      approval: approval ? { id: approval.id, tool: approval.tool } : null,
    });
  }
}

module.exports = { AgentWatcher, TOOL_ACTIVITY, USES_INPUT };
