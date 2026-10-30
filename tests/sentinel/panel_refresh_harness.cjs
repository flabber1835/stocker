// Execute the actual rendered refresh controller against failed/overlapping reads.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const stamp = Date.parse(input.generated);
let now = input.wake === 'resume-initial-pending' ? stamp + 120000 : stamp;
let sequence = 0;
const timers = new Map();
const listeners = {};
const reads = [];
const writes = [];
const badge = { className: ['known-failure','resume-known-failure'].includes(input.wake) ? 'state fail' : 'state ok', textContent: 'current' };
const heartbeat = { textContent: 'current' };
const preparation = { textContent: 'Downloading closing data' };
const planReadiness = { textContent: 'Next trading plan: not ready yet.' };
const classes = new Set();
let focusRestored = false;
const expandedDetail = {dataset: {detailKey: 'shadow-holdings'}, open: true,
  querySelector: () => ({focus: options => { assert.equal(options.preventScroll, true); focusRestored = true; }})};
const document = {
  activeElement: {closest: () => expandedDetail},
  body: { dataset: { generatedAt: input.wake === 'invalid-date' ? 'invalid' :
      input.wake === 'future-date' ? new Date(stamp + 10000).toISOString() : input.generated,
      maxAgeSeconds: input.budget,
      refreshPending: ['initial-pending','resume-initial-pending'].includes(input.wake) ? 'true' : 'false' } },
  documentElement: { classList: { add: value => classes.add(value), remove: value => classes.delete(value) } },
  visibilityState: input.wake === 'initial-hidden' ? 'hidden' : 'visible',
  getElementById: id => ({'operational-state': badge, 'preparation-stage': preparation,
    'plan-readiness': planReadiness})[id] ?? heartbeat,
  addEventListener: (name, fn) => { listeners[name] = fn; },
  querySelectorAll: selector => selector.includes('[open]') ?
    [expandedDetail].filter(item => item.open) : [expandedDetail],
  open() { writes.push('open'); },
  write(html) { writes.push(html); },
  close() { writes.push('close'); expandedDetail.open = false; },
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
function schedule(fn, delay) { const id = ++sequence; timers.set(id, {fn, delay, due: now + delay}); return id; }
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
function failRead(read) {
  if (input.failure === 'timeout') { fireDelay(15000); return; }
  read.resolve({ok: input.failure !== 'busy', status: input.failure === 'busy' ? 503 : 200,
    headers: {get: () => input.failure === 'cached' ? 'LAST_KNOWN' : 'CURRENT'},
    text: async () => input.failure});
}
(async () => {
  const sourceHash = crypto.createHash('sha256').update(input.script).digest('hex');
  vm.runInNewContext(input.script, context, {
    filename: 'sentinel-panel-refresh://' + sourceHash
  });
  if (input.wake.startsWith('resume-')) {
    async function advance(ms) {
      now += ms;
      for (let guard = 0; guard < 50; guard++) {
        const entry = [...timers.entries()].filter(([, t]) => t.due <= now)
          .sort((a, b) => a[1].due - b[1].due)[0];
        if (!entry) return;
        if (entry[1].interval) entry[1].due = now + entry[1].delay;
        else timers.delete(entry[0]);
        entry[1].fn(); await settled();
      }
      throw new Error('timer loop is unbounded');
    }
    const original = document.body.dataset.generatedAt;
    if (input.wake !== 'resume-initial-pending') {
      document.visibilityState = 'hidden'; listeners.visibilitychange();
      now = stamp + 120000;
      // iOS can deliver an overdue age timer before the visible/pageshow event.
      fireDelay(1000);
      assert.equal(reads.length, 0, 'hidden age checks must not create refresh traffic');
      document.visibilityState = 'visible'; listeners.visibilitychange();
      listeners.pageshow({persisted: true});
    }
    assert.equal(reads.length, 1, 'one network read on app return');
    if (input.wake === 'resume-known-failure') {
      assert.equal(badge.className, 'state fail', 'known failure stays red during resume');
      process.stdout.write('PASS\n'); return;
    }
    assert.equal(badge.className, 'state warn', 'resume withdraws green without inventing red');
    assert.equal(preparation.textContent, 'Last known preparation stage · refresh required',
      'background return must withdraw live preparation copy');
    assert.equal(planReadiness.textContent, 'Plan readiness not current · refreshing status');
    assert(classes.has('refreshing-status'), 'saved financial values need last-known styling');
    assert.equal(document.body.dataset.generatedAt, original, 'resume cannot renew evidence clocks');
    if (input.wake === 'resume-offline') {
      context.navigator.onLine = false; listeners.offline();
      assert.equal(badge.className, 'state fail', 'offline immediately fails');
      process.stdout.write('PASS\n'); return;
    }
    if (input.wake === 'resume-clock') {
      now -= 10000; fireDelay(1000);
      assert.equal(badge.className, 'state fail', 'clock rollback cannot extend resume');
      process.stdout.write('PASS\n'); return;
    }
    if (input.wake === 'resume-malformed') {
      reads[0].resolve({ok:true,status:200,headers:{get:()=> 'CURRENT'},text:async()=> 'incomplete'});
      await settled();
      assert.equal(badge.className, 'state fail', 'invalid server evidence fails immediately');
      process.stdout.write('PASS\n'); return;
    }
    if (input.wake === 'resume-expiry') {
      // Busy at 10 seconds. Repeated lifecycle events may not buy another budget.
      await advance(10000);
      reads[0].resolve({ok:false,status:503,headers:{get:()=> 'LAST_KNOWN'}});
      await settled();
      document.visibilityState='hidden'; listeners.visibilitychange();
      document.visibilityState='visible'; listeners.visibilitychange();
      listeners.pageshow({persisted:true});
      assert.equal(badge.className,'state warn');
      await advance(4999);
      assert.equal(badge.className,'state warn');
      await advance(2);
      assert.equal(badge.className,'state fail','the original 15-second foreground deadline must fail red');
      assert(classes.has('not-current') && !classes.has('refreshing-status'));
      assert.equal(document.body.dataset.generatedAt,original);
      now -= 1000; fireDelay(1000);
      assert.equal(badge.className,'state fail','expired resume remains red until a server answer');
    }
    const pending=reads.at(-1);
    pending.resolve({ok:true,status:200,headers:{get:()=> 'CURRENT'},text:async()=> 'fresh'});
    await settled();
    assert.deepEqual(writes,['open','fresh','close'],'fresh server document replaces last-known view');
    assert.equal(expandedDetail.open,true);
    assert.equal(focusRestored,true);
    assert.equal(timers.size,0,'successful replacement cancels the foreground deadline');
    process.stdout.write('PASS\n'); return;
  }
  if (input.wake === 'known-failure') {
    now += 30000; fireDelay(30000); await settled();
    failRead(reads[0]); await settled();
    assert.equal(badge.className,'state fail','transport delay must not hide a known negative verdict');
    process.stdout.write('PASS\n'); return;
  }
  if (input.wake.startsWith('ordinary-')) {
    const cycles = input.wake === 'ordinary-healthy' ? 3 : 1;
    for (let cycle = 0; cycle < cycles; cycle++) {
      const original = Date.parse(document.body.dataset.generatedAt);
      const first = reads.length;
      now = original + 30000;
      fireDelay(30000);
      await settled();
      assert.equal(reads.length, first + 1, 'ordinary refresh starts one read');
      assert.equal(badge.className, 'state ok', 'unexpired document stays current');
      assert.equal(Date.parse(document.body.dataset.generatedAt), original,
        'a request must not renew the original document timestamp');
      assert.equal(writes.length, 0);
      if (input.wake === 'ordinary-failure') {
        failRead(reads[first]);
        await settled();
        const expected = ['busy','cached','timeout'].includes(input.failure) ? 'state warn' : 'state fail';
        assert.equal(badge.className, expected, 'refresh preserves only bounded transport delays');
        assert(heartbeat.textContent.includes('last known'));
        assert.equal(writes.length, 0);
        now = original + 31000; fireDelay(1000);
        assert.equal(badge.className, expected, 'unexpired age cannot clear a known failure or delay');
        listeners.pageshow({persisted: true});
        assert.equal(reads.length, first + 1, 'retry backoff prevents overlapping reads');
        fireDelay(5000);
        assert.equal(reads.length, first + 2);
      } else if (input.wake === 'ordinary-slow') {
        now = original + 44000; fireDelay(1000);
        assert.equal(badge.className, 'state ok', 'slow read retains only unexpired proof');
        assert(heartbeat.textContent.includes('UPDATED 44s'));
        assert.equal(reads.length, first + 1);
      } else if (input.wake === 'ordinary-expiry') {
        now = original + Number(input.budget) * 1000 + 1; fireDelay(1000);
        assert.equal(badge.className, 'state fail', 'original expiry withdraws current');
        assert.equal(preparation.textContent, 'Last known preparation stage · refresh required',
          'original expiry must withdraw live preparation copy');
        assert.equal(planReadiness.textContent, 'Plan readiness not current · refreshing status');
        assert.equal(reads.length, first + 1, 'expiry cannot overlap the pending read');
        now = original + 32000; fireDelay(1000);
        assert.equal(badge.className, 'state fail', 'clock rollback cannot restore green');
      }
      const pending = reads.at(-1);
      pending.resolve({ok: true, headers: {get: () => 'CURRENT'}, text: async () => 'fresh'});
      await settled();
      assert.deepEqual(writes, ['open', 'fresh', 'close']);
      assert.equal(timers.size, 0, 'replacement removes every old document timer');
      if (cycle + 1 < cycles) {
        // Install the next server document and execute its actual controller.
        document.body.dataset.generatedAt = new Date(now).toISOString();
        badge.className = 'state ok'; badge.textContent = 'current';
        writes.length = 0;
        vm.runInNewContext(input.script, context);
      }
    }
    process.stdout.write('PASS\n');
    return;
  }
  if (input.wake === 'fresh-age') {
    listeners.pageshow({persisted: false});
    assert.equal(reads.length, 0);
    assert.equal(badge.className, 'state ok');
    now += 1000; fireDelay(1000);
    assert(heartbeat.textContent.includes('UPDATED 1s'));
    now += Number(input.budget) * 1000; fireDelay(1000);
    assert.equal(badge.className, 'state fail');
    assert.equal(preparation.textContent, 'Last known preparation stage · refresh required',
      'original evidence must withdraw live preparation copy');
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
    assert.equal(badge.className, 'state warn');
  } else if (['offline', 'initial-offline'].includes(input.wake)) {
    if (input.wake === 'offline') {
      context.navigator.onLine = false; listeners.offline();
    }
    assert.equal(reads.length, 0, 'offline cannot start a network read');
    assert.equal(badge.className, 'state fail');
    assert.equal(preparation.textContent, 'Last known preparation stage · refresh required',
      'offline must withdraw live preparation copy');
    listeners.pageshow({persisted: true});
    assert.equal(reads.length, 0);
    context.navigator.onLine = true; listeners.online();
    assert.equal(reads.length, 1);
  } else if (input.wake === 'online') {
    listeners.online(); assert.equal(reads.length, 0, 'no outage, no recovery read');
  } else if (input.wake === 'initial-pending') {
    assert.equal(reads.length, 1);
    assert.equal(badge.className, 'state warn');
  }
  fireDelay(30000);
  now += 1000;
  listeners.pageshow({persisted: true});
  listeners.pageshow({persisted: true});
  assert.equal(reads.length, 1, 'overlapping wakeups must not start another refresh');
  assert.equal(writes.length, 0);
  const alreadyFailed=['fresh-age','invalid-date','future-date','offline','initial-offline'].includes(input.wake);
  assert.equal(badge.className, alreadyFailed ? 'state fail' : 'state warn');
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
  assert.equal(expandedDetail.open, true, 'expanded holdings survive page replacement');
  assert.equal(focusRestored, true, 'keyboard focus survives page replacement');
  assert.equal(timers.size, 0, 'old document timers must not survive replacement');
  process.stdout.write('PASS\n');
})().catch(error => { console.error(error.message); process.exitCode = 1; });
