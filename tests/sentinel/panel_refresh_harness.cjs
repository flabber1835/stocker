// Execute the actual rendered refresh controller against failed/overlapping reads.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
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
  body: { dataset: { generatedAt: input.generated, maxAgeSeconds: '60', refreshPending: 'false' } },
  documentElement: { classList: { add() {} } },
  visibilityState: 'visible',
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
      body: { dataset: { generatedAt: new Date(html === 'stale' ? now - 120000 : now).toISOString(),
                        maxAgeSeconds: '60', refreshPending: 'false' } } };
  }
}
function schedule(fn, delay) { const id = ++sequence; timers.set(id, {fn, delay}); return id; }
const context = {
  document, Date: Clock, DOMParser: Parser, AbortController,
  navigator: { onLine: true }, location: { href: 'http://fixture.invalid/' },
  window: { scrollY: 42, scrollTo() {}, addEventListener: (name, fn) => {listeners[name] = fn;} },
  setInterval: schedule, setTimeout: schedule,
  clearInterval: id => timers.delete(id), clearTimeout: id => timers.delete(id),
  fetch: (_url, options) => new Promise((resolve, reject) => {
    reads.push({ resolve, reject });
    options.signal.addEventListener('abort', () => reject(new Error('timeout')));
  }),
};
function fireDelay(delay) {
  const entry = [...timers.entries()].find(([, timer]) => timer.delay === delay);
  assert(entry, 'expected bounded timer');
  timers.delete(entry[0]); entry[1].fn();
}
async function settled() { for (let i = 0; i < 8; i++) await Promise.resolve(); }
(async () => {
  vm.runInNewContext(input.script, context);
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
      text: async () => ['stale','incomplete'].includes(input.failure) ? input.failure : 'ignored'});
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
