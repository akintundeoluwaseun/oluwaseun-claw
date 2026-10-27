'use strict';
// Telling the person about an event before it happens.
//
// The backend decides what is due (claw/calendar/reminders.py); this polls for
// it, shows a Windows notification, and tells the backend what it showed so the
// same reminder is never shown twice. Split out of main.js so the loop can be
// tested without an Electron window - the failure that matters here is a
// reminder that arrives twice, or not at all, and neither needs a screen.

const MINUTE = 60 * 1000;
//: Often enough that "in 10 minutes" is not stale, rare enough to cost nothing.
const EVERY = MINUTE;
//: Nobody reads six notifications. The rest wait for the next poll.
const AT_ONCE = 3;

/** What one reminder says, as a title and a line underneath. */
function describe(item) {
  const when = item.when || 'soon';
  const where = item.location ? ` · ${item.location}` : '';
  return {
    title: item.minutes_until <= 0 ? item.summary : `${item.summary} — ${when}`,
    body: item.all_day ? `Today${where}` : `Starts ${when}${where}`,
  };
}

class ReminderWatcher {
  /**
   * @param backendRef () => Backend, because the backend is replaced on restart
   * @param show (item, text) => void, what actually puts it on screen
   */
  constructor(backendRef, { show, every = EVERY } = {}) {
    this.backendRef = backendRef;
    this.show = show;
    this.every = every;
    this.timer = null;
  }

  start() {
    if (this.timer) return;
    const loop = async () => {
      try {
        await this.tick();
      } catch {
        /* the backend is restarting; the reminder is still due next time */
      }
      this.timer = setTimeout(loop, this.every);
    };
    loop();
  }

  stop() {
    clearTimeout(this.timer);
    this.timer = null;
  }

  async tick() {
    const backend = this.backendRef();
    if (!backend || backend.status.state !== 'ready') return;
    const res = await backend.request('GET', '/calendar/due');
    if (!res.ok || !res.body || !Array.isArray(res.body.due) || res.body.due.length === 0) return;

    const batch = res.body.due.slice(0, AT_ONCE);
    for (const item of batch) this.show(item, describe(item));
    // Only what was actually shown is marked. A reminder left out of this batch
    // must still be waiting at the next poll, not silently used up.
    await backend.request('POST', '/calendar/due/seen', { uids: batch.map((i) => i.uid) });
  }
}

//: How long after the chosen time a briefing is still worth showing. Open the
//: laptop at 09:30 and you still want the 08:00 briefing; open it at 22:00 and
//: you do not.
const BRIEF_WINDOW_HOURS = 6;

/** "08:00" as minutes past local midnight, or null if it is not a time. */
function parseTimeOfDay(text) {
  const m = /^([01]?\d|2[0-3]):([0-5]\d)$/.exec(String(text || '').trim());
  return m ? Number(m[1]) * 60 + Number(m[2]) : null;
}

/** The local day, as YYYY-MM-DD, which is what "once a day" is counted in. */
function localDay(now) {
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
}

/**
 * Should the briefing be shown right now?
 *
 * Pure, because the awkward cases are all about time: the app was closed all
 * morning, the app has been open since yesterday, the chosen time has not come
 * yet. None of them need a window to test.
 */
function briefingIsDue(now, atText, lastDay) {
  const at = parseTimeOfDay(atText);
  if (at === null) return false;                       // off, or not a time
  const minutes = now.getHours() * 60 + now.getMinutes();
  if (minutes < at) return false;                      // not yet today
  if (minutes > at + BRIEF_WINDOW_HOURS * 60) return false;  // too late to be a morning briefing
  return lastDay !== localDay(now);                    // once a day
}

/**
 * The morning briefing.
 *
 * It only ever fires while S-CLAW is running. There is no service behind it, so
 * a laptop that stayed shut gets no briefing - and the app never says otherwise.
 */
class BriefWatcher {
  constructor(backendRef, { show, at, lastDay, remember, every = EVERY }) {
    this.backendRef = backendRef;
    this.show = show;
    this.at = at;                 // () => "08:00" | "" , read from settings each tick
    this.lastDay = lastDay;       // () => "YYYY-MM-DD" | null
    this.remember = remember;     // (day) => void
    this.every = every;
    this.timer = null;
  }

  start() {
    if (this.timer) return;
    const loop = async () => {
      try {
        await this.tick();
      } catch {
        /* the backend is restarting; tomorrow's briefing is not affected */
      }
      this.timer = setTimeout(loop, this.every);
    };
    loop();
  }

  stop() {
    clearTimeout(this.timer);
    this.timer = null;
  }

  async tick(now = new Date()) {
    if (!briefingIsDue(now, this.at(), this.lastDay())) return;
    const backend = this.backendRef();
    if (!backend || backend.status.state !== 'ready') return;
    const res = await backend.request('GET', '/brief');
    if (!res.ok || !res.body) return;
    // Marked first: a briefing that fails to display is not worth repeating
    // every minute for the next six hours.
    this.remember(localDay(now));
    this.show(res.body);
  }
}

module.exports = {
  ReminderWatcher, BriefWatcher, describe, briefingIsDue, parseTimeOfDay, localDay,
  EVERY, AT_ONCE, BRIEF_WINDOW_HOURS,
};
