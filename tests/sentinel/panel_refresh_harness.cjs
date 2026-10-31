// Execute the actual rendered refresh controller against failed/overlapping reads.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const stamp = Date.parse(input.generated);
let now = ['resume-initial-pending','transport-expired-initial'].includes(input.wake) ? stamp + 120000 : stamp;
let sequence = 0;
const timers = new Map();
const listeners = {};
const reads = [];
const writes = [];
const installed = [];
const badge = { className: ['known-failure','resume-known-failure','hidden-initial-known-failure'].includes(input.wake) || input.case?.knownNegative ? 'state fail' : 'state ok', textContent: 'current' };
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
  visibilityState: input.wake === 'initial-hidden' || input.wake.startsWith('hidden-initial-') ? 'hidden' : 'visible',
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
    const read = {resolve, reject, started: now, aborted: false};
    reads.push(read);
    options.signal.addEventListener('abort', () => {
      read.aborted = true;
      if (!(input.case && input.case.ignoreAbort)) reject(new Error('timeout'));
    });
  }),
};
function fireDelay(delay) {
  const entries = [...timers.entries()];
  const entry = (delay === 15000 ? entries.reverse() : entries)
    .find(([, timer]) => timer.delay === delay);
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
  if (input.wake.startsWith('transport-')) {
    const config = input.case || {};
    const budget = Number(input.budget) * 1000;
    const poll = Number(input.script.match(/refreshTimer = setTimeout[^\n]+, (\d+)\);/)[1]);
    const original = document.body.dataset.generatedAt;
    const observations = [];
    let planned = 0;
    let finished = false;
    function fresh(read) {
      read.resolve({ok:true,status:200,headers:{get:()=> 'CURRENT'},text:async()=> 'fresh'});
    }
    function remember() {
      observations.push({at:now,state:badge.className,generated:Date.parse(document.body.dataset.generatedAt)});
      if (!writes.length || config.latencyMs === undefined) return;
      assert.deepEqual(writes,['open','fresh','close']);
      assert.equal(timers.size,0,'fresh replacement cancels the old proof and transport timers');
      installed.push(now);
      if (installed.length >= (config.cycles || 1)) { finished=true; return; }
      document.body.dataset.generatedAt = new Date(now).toISOString();
      badge.className='state ok';badge.textContent='current';
      classes.clear();writes.length=0;
      vm.runInNewContext(input.script,context);
    }
    function planReplies() {
      if (config.latencyMs === undefined) return;
      while (planned < reads.length) {
        const read=reads[planned++];
        schedule(()=>{if (!read.aborted || config.ignoreAbort) fresh(read);},config.latencyMs);
      }
    }
    async function advanceTo(target) {
      assert(target >= now);
      for (let guard=0;guard<5000;guard++) {
        if (finished) return;
        planReplies();
        const entry=[...timers.entries()].filter(([,t])=>t.due<=target)
          .sort((a,b)=>a[1].due-b[1].due || a[0]-b[0])[0];
        if (!entry) {now=target;await settled();remember();return;}
        now=entry[1].due;
        if (entry[1].interval) entry[1].due += entry[1].delay;
        else timers.delete(entry[0]);
        entry[1].fn();await settled();remember();
      }
      throw new Error('actual due-time scheduler is unbounded');
    }
    function lastKnown() {
      assert.equal(badge.className,'state warn','owned refresh keeps expired proof explicitly last known');
      assert(classes.has('refreshing-status'),'expired proof values require last-known styling');
      assert(!classes.has('not-current'),'bounded refresh is not an operational failure');
      assert.equal(preparation.textContent,'Last known preparation stage · refresh required');
      assert.equal(planReadiness.textContent,'Plan readiness not current · refreshing status');
      assert.equal(document.body.dataset.generatedAt,original,'transport cannot renew proof clocks');
    }
    function hide(visibility=true) {
      listeners.pagehide();
      if (visibility) {document.visibilityState='hidden';listeners.visibilitychange();}
    }
    function show(visibility=true) {
      if (visibility) {document.visibilityState='visible';listeners.visibilitychange();}
      if (config.event!=='pageshow' && listeners.focus) listeners.focus();
      if (config.event!=='focus') listeners.pageshow({persisted:false});
    }
    if (input.wake === 'transport-matrix') {
      const cycles=config.cycles || 1;
      if (config.latencyMs < 15000) {
        await advanceTo(stamp+cycles*(poll+config.latencyMs+2000));
        assert.equal(installed.length,cycles,'bounded healthy responses replace the document');
        assert.equal(reads.length,cycles);
        assert(reads[0].started>=stamp+poll,'proof expiry cannot advance the first ordinary read');
        assert(reads.every((r,i)=>!i || r.started-reads[i-1].started>=5000),'ordinary polling keeps its five-second floor');
        if (budget>=poll) assert(observations.every(o=>o.state!=='state fail'),'healthy in-flight refresh cannot flash red');
        if (config.requireAmber) assert(observations.some(o=>o.state==='state warn'),'expired healthy transport must withdraw green');
        for (const view of observations) {
          const firstExpiredTick=view.generated+(Math.floor(budget/1000)+1)*1000;
          if (view.at>=firstExpiredTick && !installed.includes(view.at)) {
            assert.notEqual(view.state,'state ok','the original proof boundary cannot retain green');
          }
        }
      } else {
        await advanceTo(stamp+poll+16001);
        assert.equal(installed.length,0,'a response after the transport timeout is not installed');
        assert.equal(badge.className,'state fail','exhausted transport must withdraw last-known amber');
      }
    } else if (input.wake === 'transport-unowned-focus') {
      await advanceTo(stamp+2000);
      assert.equal(badge.className,'state fail','unowned expired proof withdraws at its age tick');
      assert.equal(reads.length,0);
      listeners.focus();listeners.focus();
      assert.equal(reads.length,0,'unowned focus cannot buy a resume or bring the ordinary read forward');
      assert.equal(badge.className,'state fail');
      assert.equal(document.body.dataset.generatedAt,original);
      await advanceTo(stamp+poll);
      assert.equal(reads.length,1,'ordinary read keeps its original due time');
    } else if (input.wake === 'transport-expired-initial') {
      assert.equal(reads.length,0,'an expired initial proof waits for ordinary polling');
      listeners.pageshow({persisted:false});
      assert.equal(reads.length,1,'expired initial pageshow starts one bounded recovery');
      lastKnown();
      listeners.focus();listeners.pageshow({persisted:false});
      assert.equal(reads.length,1);
      await advanceTo(now+15001);
      assert.equal(badge.className,'state fail');
    } else {
      await advanceTo(stamp+poll);
      assert.equal(reads.length,1);
      const start=reads[0].started;
      if (input.wake === 'transport-deadline' || input.wake === 'transport-focus') {
        await advanceTo(stamp+10000);lastKnown();
        if (input.wake === 'transport-focus') {
          listeners.focus();listeners.pageshow({persisted:false});
          lastKnown();
        } else {
          for (const [id,timer] of timers) if (timer.interval) timers.delete(id);
        }
        await advanceTo(start+14999);lastKnown();
        await advanceTo(start+15001);
        assert.equal(badge.className,'state fail','the original ordinary transport deadline is absolute');
      } else if (input.wake === 'transport-retry' || input.wake === 'transport-body') {
        await advanceTo(start+(input.wake==='transport-body'?6000:2000));
        if (input.wake==='transport-body') {
          reads[0].resolve({ok:true,status:200,headers:{get:()=> 'CURRENT'},text:async()=>{throw new Error('body interrupted');}});
        } else reads[0].resolve({ok:false,status:503,headers:{get:()=> 'LAST_KNOWN'}});
        await settled();
        await advanceTo(start+14999);lastKnown();
        assert.equal(reads.length,2,'one backoff read remains inside the original episode');
        await advanceTo(start+15001);
        assert.equal(badge.className,'state fail','transport retries cannot renew their first deadline');
      } else if (input.wake === 'transport-hidden') {
        await advanceTo(start+1000);hide(config.visibility!==false);
        if (config.kind==='busy') {
          await advanceTo(start+6000);
          reads[0].resolve({ok:false,status:503,headers:{get:()=> 'LAST_KNOWN'}});
          await settled();
        }
        const returned=start+(config.order==='before-timeout'?14000:20000);
        await advanceTo(returned);
        show(config.visibility!==false);lastKnown();
        const resumeViews=observations.length;
        const resumeEnd=returned+15000;
        await advanceTo(resumeEnd-1);lastKnown();
        assert(observations.slice(resumeViews).every(view=>view.state!=='state fail'),
          'owned refresh keeps expired proof last known throughout its first resume');
        show(config.visibility!==false);
        await advanceTo(resumeEnd+1);
        assert.equal(badge.className,'state fail','foreground events cannot renew the first resume deadline');
        show(config.visibility!==false);
        assert.equal(badge.className,'state fail','exhausted resume cannot revive last-known amber');
        if (reads.at(-1).aborted && !config.ignoreAbort) await advanceTo(now+5000);
        fresh(reads.at(-1));await settled();
        assert.deepEqual(writes,['open','fresh','close'],'a later genuinely fresh server answer can restore the view');
      } else if (input.wake === 'transport-negative') {
        await advanceTo(start+1000);
        if (config.kind==='offline') {context.navigator.onLine=false;listeners.offline();}
        else if (config.kind==='clock') {now=stamp-6000;fireDelay(1000);}
        else {
          const value=config.kind==='future'?'future':'incomplete';
          reads[0].resolve({ok:true,status:200,headers:{get:()=> 'CURRENT'},text:async()=>value});
          await settled();
        }
        assert.equal(badge.className,'state fail');
        assert(classes.has('not-current'));
        hide();document.visibilityState='visible';show();
        assert.equal(badge.className,'state fail','foreground resume cannot soften a hard negative');
        assert(classes.has('not-current'),'hard-negative last-known styling cannot be cleared by resume');
      } else throw new Error('unrecognized transport case');
    }
    process.stdout.write('PASS\n');return;
  }
  if (input.wake.startsWith('hidden-')) {
    const original = document.body.dataset.generatedAt;
    if (input.wake === 'hidden-timer') {
      document.visibilityState = 'hidden'; listeners.visibilitychange();
      now = stamp + 30000; fireDelay(30000); await settled();
      assert.equal(reads.length, 0, 'hidden timer cannot start a refresh');
    } else if (input.wake === 'hidden-response') {
      now = stamp + 30000; fireDelay(30000); await settled();
      assert.equal(reads.length, 1);
      document.visibilityState = 'hidden'; listeners.visibilitychange();
      now = stamp + 120000;
      reads[0].resolve({ok:true,status:200,headers:{get:()=> 'CURRENT'},text:async()=> 'fresh'});
      await settled();
      assert.equal(writes.length, 0, 'response completed while hidden cannot replace the lifecycle');
      assert.equal(reads.length, 1);
    } else if (input.wake === 'hidden-initial-due') {
      now = stamp + 30000; fireDelay(30000); fireDelay(1000); await settled();
      assert.equal(reads.length, 0, 'initially hidden ordinary read is deferred');
      assert.equal(badge.className, 'state ok');
    } else {
      now = stamp + (input.wake === 'hidden-initial-fresh' ? 1000 : 120000);
      fireDelay(1000); await settled();
      assert.equal(reads.length, 0, 'hidden age checks cannot start traffic');
      if (input.wake !== 'hidden-initial-known-failure') {
        assert.notEqual(badge.className, 'state fail', 'hidden expiry waits for bounded foreground resume');
      }
    }
    const previousReads = reads.length;
    document.visibilityState = 'visible'; listeners.visibilitychange();
    if (input.wake === 'hidden-initial-fresh') {
      assert.equal(reads.length, 0, 'fresh first-visible document needs no extra read');
      assert.equal(badge.className, 'state ok');
      process.stdout.write('PASS\n'); return;
    }
    assert.equal(reads.length, previousReads + 1, 'foreground starts exactly one current read');
    assert.equal(badge.className, input.wake === 'hidden-initial-known-failure' ? 'state fail' :
      input.wake === 'hidden-initial-due' ? 'state ok' : 'state warn',
      'foreground resume cannot invent red or hide a known negative');
    assert.equal(document.body.dataset.generatedAt, original, 'foreground resume cannot renew original clocks');
    listeners.pageshow({persisted:true});
    assert.equal(reads.length, previousReads + 1, 'foreground wakeups cannot overlap the pending read');
    if (input.wake === 'hidden-initial-expired') {
      now += 14999;
      document.visibilityState = 'hidden'; listeners.visibilitychange();
      document.visibilityState = 'visible'; listeners.visibilitychange();
      listeners.pageshow({persisted:true}); fireDelay(1000);
      assert.equal(badge.className, 'state warn');
      now += 2; fireDelay(1000);
      assert.equal(badge.className, 'state fail', 'first-visible resume keeps its original 15-second deadline');
      assert.equal(reads.length, previousReads + 1);
    }
    reads.at(-1).resolve({ok:true,status:200,headers:{get:()=> 'CURRENT'},text:async()=> 'fresh'});
    await settled();
    assert.deepEqual(writes, ['open','fresh','close']);
    assert.equal(timers.size, 0, 'successful foreground replacement cancels original timers');
    process.stdout.write('PASS\n'); return;
  }
  if (input.wake === 'proof-expiry') {
    assert.equal(badge.className,'state ok');
    const original=document.body.dataset.generatedAt;
    const poll=Number(input.script.match(/refreshTimer = setTimeout[^\n]+, (\d+)\);/)[1]);
    now=stamp+(Math.floor(Number(input.budget))+1)*1000;
    fireDelay(1000);
    assert.equal(badge.className,'state fail','original proof expiry withdraws green');
    assert.equal(planReadiness.textContent,'Plan readiness not current · refreshing status');
    assert.equal(document.body.dataset.generatedAt,original,'proof expiry cannot renew the observation');
    if (now<stamp+poll) {
      assert.equal(reads.length,0,'short-proof expiry cannot cause a one-second poll');
      now=stamp+poll;fireDelay(poll);await settled();
    }
    assert.equal(reads.length,1);
    listeners.pageshow({persisted:true});
    assert.equal(reads.length,1,'expired proof cannot start competing reads');
    now=stamp+1000;fireDelay(1000);
    assert.equal(badge.className,'state fail','clock rollback cannot restore the historical exception');
    process.stdout.write('PASS\n');return;
  }
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
