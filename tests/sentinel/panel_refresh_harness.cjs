// Execute the actual rendered refresh controller against failed/overlapping reads.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const stamp = Date.parse(input.generated);
let now = stamp;
let sequence = 0;
const timers = new Map();
const listeners = {};
const reads = [];
const writes = [];
const badge = { className: 'state ok', textContent: 'current' };
const heartbeat = { textContent: 'current' };
const document = {
  body: { dataset: { generatedAt: input.wake === 'invalid-date' ? 'invalid' :
      input.wake === 'future-date' ? new Date(stamp + 10000).toISOString() : input.generated,
      maxAgeSeconds: input.budget,
      refreshPending: input.wake === 'initial-pending' ? 'true' : 'false' } },
  documentElement: { classList: { add() {} } },
  visibilityState: input.wake === 'initial-hidden' ? 'hidden' : 'visible',
  getElementById: id => id === 'operational-state' ? badge : heartbeat,
  addEventListener: (name, fn) => { listeners[name] = fn; },
  open() { writes.push('open'); },
  write(html) { writes.push(html); },
  close() { writes.push('close'); },
};
class Clock extends Date { static now() { return now; } }
class Parser {
  parseFromString(html) {
    return { getElementById: () => html === 'incomplete' ? null : {},
      body: { dataset: { generatedAt: html === 'invalid-date' ? 'invalid' :
        new Date(html === 'stale' ? now - 120000 : html === 'future' ? now + 10000 : now).toISOString(),
        maxAgeSeconds: ({'invalid-budget': 'invalid', 'zero-budget': '0',
          'infinite-budget': 'Infinity', 'oversized-budget': '99999'})[html] ?? input.budget,
        refreshPending: html === 'pending' ? 'true' : 'false' } } };
  }
}
function schedule(fn, delay) { const id = ++sequence; timers.set(id, {fn, delay}); return id; }
function interval(fn, delay) { const id = schedule(fn, delay); timers.get(id).interval = true; return id; }
const context = {
  document, Date: Clock, DOMParser: Parser, AbortController,
  navigator: { onLine: input.wake !== 'initial-offline' }, location: { href: 'http://fixture.invalid/' },
  window: { scrollY: 42, scrollTo() {}, addEventListener: (name, fn) => {listeners[name] = fn;} },
  setInterval: interval, setTimeout: schedule,
  clearInterval: id => timers.delete(id), clearTimeout: id => timers.delete(id),
  fetch: (_url, options) => new Promise((resolve, reject) => {
    reads.push({ resolve, reject });
    options.signal.addEventListener('abort', () => reject(new Error('timeout')));
  }),
};
function fireDelay(delay) {
  const entry = [...timers.entries()].find(([, timer]) => timer.delay === delay);
  assert(entry, 'expected bounded timer');
  if (!entry[1].interval) { timers.delete(entry[0]); }
  entry[1].fn();
}
async function settled() { for (let i = 0; i < 8; i++) await Promise.resolve(); }
(async () => {
  const sourceHash = crypto.createHash('sha256').update(input.script).digest('hex');
  vm.runInNewContext(input.script, context, {
    filename: 'sentinel-panel-refresh://' + sourceHash
  });
  if (input.wake === 'fresh-age') {
    listeners.pageshow({persisted: false});
    assert.equal(reads.length, 0);
    assert.equal(badge.className, 'state ok');
    now += 1000; fireDelay(1000);
    assert(heartbeat.textContent.includes('UPDATED 1s'));
    now += Number(input.budget) * 1000; fireDelay(1000);
    assert.equal(badge.className, 'state fail');
    now = stamp + 1000; fireDelay(1000);
    assert.equal(badge.className, 'state fail', 'a local clock cannot restore green');
  } else if (['invalid-date', 'future-date'].includes(input.wake)) {
    listeners.pageshow({persisted: false});
    assert.equal(badge.className, 'state fail');
    assert.equal(reads.length, 1);
  } else if (['visibility', 'initial-hidden'].includes(input.wake)) {
    if (input.wake === 'initial-hidden') {
      listeners.visibilitychange();
      document.visibilityState = 'visible'; listeners.visibilitychange();
      assert.equal(reads.length, 0, 'first visible state must not invent an absence');
      document.visibilityState = 'prerender'; listeners.visibilitychange();
    }
    document.visibilityState = 'hidden'; listeners.visibilitychange();
    document.visibilityState = 'hidden'; listeners.visibilitychange();
    document.visibilityState = 'visible'; listeners.visibilitychange();
    assert.equal(reads.length, 1);
    assert.equal(badge.className, 'state fail');
  } else if (['offline', 'initial-offline'].includes(input.wake)) {
    if (input.wake === 'offline') {
      context.navigator.onLine = false; listeners.offline();
    }
    assert.equal(reads.length, 0, 'offline cannot start a network read');
    assert.equal(badge.className, 'state fail');
    listeners.pageshow({persisted: true});
    assert.equal(reads.length, 0);
    context.navigator.onLine = true; listeners.online();
    assert.equal(reads.length, 1);
  } else if (input.wake === 'online') {
    listeners.online(); assert.equal(reads.length, 0, 'no outage, no recovery read');
  } else if (input.wake === 'initial-pending') {
    assert.equal(reads.length, 1);
    assert.equal(badge.className, 'state fail');
  }
  fireDelay(30000);
  now += 1000;
  listeners.pageshow({persisted: true});
  listeners.pageshow({persisted: true});
  assert.equal(reads.length, 1, 'overlapping wakeups must not start another refresh');
  assert.equal(writes.length, 0);
  assert.equal(badge.className, 'state fail');
  if (input.failure === 'timeout') {
    fireDelay(15000);
  } else {
    const ok = input.failure !== 'busy';
    const header = input.failure === 'cached' ? 'LAST_KNOWN' : 'CURRENT';
    reads[0].resolve({ok, headers: {get: () => header},
      text: async () => ['stale', 'incomplete', 'pending', 'future', 'invalid-date',
        'invalid-budget', 'zero-budget', 'infinite-budget', 'oversized-budget'].includes(input.failure)
        ? input.failure : 'ignored'});
  }
  await settled();
  assert.equal(writes.length, 0, 'a failed or non-current read must keep the visible dashboard');
  assert(heartbeat.textContent.includes('last known'));
  listeners.pageshow({persisted: true});
  assert.equal(reads.length, 1, 'retry backoff must survive overlapping wakeups');
  fireDelay(5000);
  assert.equal(reads.length, 2);
  reads[1].resolve({ok: true, headers: {get: () => 'CURRENT'}, text: async () => 'fresh'});
  await settled();
  assert.deepEqual(writes, ['open', 'fresh', 'close']);
  assert.equal(timers.size, 0, 'old document timers must not survive replacement');
  process.stdout.write('PASS\n');
})().catch(error => { console.error(error.message); process.exitCode = 1; });
