'use strict';
// The reminder loop, without an Electron window.
//
// What can go wrong here is narrow and awful: a reminder shown twice, or one
// marked as shown that nobody ever saw. Both are tested against a fake backend
// that records exactly what was asked of it.

const test = require('node:test');
const assert = require('node:assert');
const { ReminderWatcher, describe: say, AT_ONCE } = require('../src/reminders');

function fakeBackend(due, state = 'ready') {
  const calls = [];
  return {
    calls,
    status: { state },
    async request(method, route, body) {
      calls.push({ method, route, body });
      if (route === '/calendar/due') return { ok: true, body: { due } };
      return { ok: true, body: {} };
    },
  };
}

const item = (uid, extra = {}) => ({
  uid, summary: 'Site visit', location: '', all_day: false,
  minutes_until: 10, when: 'in 10 minutes', ...extra,
});

test('a due reminder is shown and then marked as shown', async () => {
  const backend = fakeBackend([item('a@x')]);
  const shown = [];
  await new ReminderWatcher(() => backend, { show: (i) => shown.push(i.uid) }).tick();
  assert.deepStrictEqual(shown, ['a@x']);
  const seen = backend.calls.find((c) => c.route === '/calendar/due/seen');
  assert.deepStrictEqual(seen.body, { uids: ['a@x'] });
});

test('nothing due means nothing is said and nothing is marked', async () => {
  const backend = fakeBackend([]);
  let shown = 0;
  await new ReminderWatcher(() => backend, { show: () => { shown += 1; } }).tick();
  assert.strictEqual(shown, 0);
  assert.ok(!backend.calls.some((c) => c.route === '/calendar/due/seen'),
    'an empty poll must not mark anything as shown');
});

test('only what was shown is marked, so the rest still arrive next time', async () => {
  const many = ['a', 'b', 'c', 'd', 'e'].map((u) => item(`${u}@x`));
  const backend = fakeBackend(many);
  const shown = [];
  await new ReminderWatcher(() => backend, { show: (i) => shown.push(i.uid) }).tick();
  assert.strictEqual(shown.length, AT_ONCE, 'a pile of notifications at once is noise');
  const seen = backend.calls.find((c) => c.route === '/calendar/due/seen');
  assert.deepStrictEqual(seen.body.uids, shown, 'a reminder was used up without being seen');
});

test('a backend that is not ready is left alone', async () => {
  const backend = fakeBackend([item('a@x')], 'starting');
  let shown = 0;
  await new ReminderWatcher(() => backend, { show: () => { shown += 1; } }).tick();
  assert.strictEqual(shown, 0);
  assert.strictEqual(backend.calls.length, 0);
});

test('how a reminder reads on screen', () => {
  assert.deepStrictEqual(say(item('a@x')), {
    title: 'Site visit — in 10 minutes', body: 'Starts in 10 minutes',
  });
  // Once it has started, the countdown is noise: the title is just the thing.
  assert.strictEqual(say(item('a@x', { minutes_until: 0, when: 'now' })).title, 'Site visit');
  assert.strictEqual(
    say(item('a@x', { all_day: true, location: 'Site office', when: 'today' })).body,
    'Today · Site office');
});

// ---------- the morning briefing ----------
const { BriefWatcher, briefingIsDue, parseTimeOfDay, localDay, BRIEF_WINDOW_HOURS } = require('../src/reminders');

const on = (h, m = 0) => new Date(2026, 10, 3, h, m);   // 3 Nov 2026, local

test('a time of day is read, or refused', () => {
  assert.strictEqual(parseTimeOfDay('08:00'), 480);
  assert.strictEqual(parseTimeOfDay('23:59'), 1439);
  assert.strictEqual(parseTimeOfDay('7:30'), 450);
  for (const bad of ['', '8am', '24:00', '08:60', 'morning', null, undefined]) {
    assert.strictEqual(parseTimeOfDay(bad), null, `${bad} is not a time`);
  }
});

test('the briefing waits for its time, and gives up when the morning is gone', () => {
  assert.ok(!briefingIsDue(on(7, 59), '08:00', null), 'not yet');
  assert.ok(briefingIsDue(on(8, 0), '08:00', null), 'on time');
  assert.ok(briefingIsDue(on(9, 30), '08:00', null), 'a laptop opened late still gets it');
  assert.ok(!briefingIsDue(on(8 + BRIEF_WINDOW_HOURS, 1), '08:00', null),
    'at 14:01 a morning briefing is not a briefing');
});

test('the briefing is shown once a day, and an empty time turns it off', () => {
  assert.ok(!briefingIsDue(on(9), '08:00', localDay(on(9))), 'already had one today');
  assert.ok(briefingIsDue(on(9), '08:00', '2026-11-02'), 'yesterday does not count');
  assert.ok(!briefingIsDue(on(9), '', null), 'empty means off');
  assert.ok(!briefingIsDue(on(9), 'morning', null), 'and so does nonsense');
});

test('the briefing is fetched, remembered, and then shown', async () => {
  const backend = {
    status: { state: 'ready' },
    calls: [],
    async request(method, route) {
      this.calls.push(route);
      return { ok: true, body: { headline: 'One thing today: Site visit at 15:00.', agenda: [] } };
    },
  };
  let day = null;
  const shown = [];
  const w = new BriefWatcher(() => backend, {
    at: () => '08:00', lastDay: () => day, remember: (d) => { day = d; },
    show: (b) => shown.push(b.headline),
  });
  await w.tick(on(8, 5));
  assert.deepStrictEqual(backend.calls, ['/brief']);
  assert.strictEqual(shown.length, 1);
  assert.strictEqual(day, '2026-11-03');

  // Same day again: nothing is fetched at all.
  await w.tick(on(9, 5));
  assert.deepStrictEqual(backend.calls, ['/brief'], 'the briefing was fetched twice in one day');
  assert.strictEqual(shown.length, 1);
});

test('no briefing is invented while the backend is down', async () => {
  const backend = { status: { state: 'starting' }, async request() { throw new Error('nope'); } };
  let day = null;
  const w = new BriefWatcher(() => backend, {
    at: () => '08:00', lastDay: () => day, remember: (d) => { day = d; }, show: () => {
      throw new Error('a briefing was shown without being fetched');
    },
  });
  await w.tick(on(8, 5));
  assert.strictEqual(day, null, 'a day must not be marked as briefed when nothing was fetched');
});
