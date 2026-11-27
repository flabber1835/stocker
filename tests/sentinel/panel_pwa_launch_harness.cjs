// Execute the shipped worker and launch controller with no operational credentials.
const vm = require('node:vm');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));

async function worker() {
  const handlers = {};
  let pending, reads = 0;
  vm.runInNewContext(input.source, {
    URL, Response, Promise,
    self: {location:{origin:'https://fixture.invalid'}, addEventListener:(name,fn)=>handlers[name]=fn},
    fetch:async()=>{reads++;return new Response('network-only-fixture');}
  });
  handlers.fetch({request:{mode:input.kind==='json'?'cors':'navigate',method:'GET',
    url:'https://fixture.invalid'+(input.kind==='root'?'/?launch=1':input.kind==='document'?'/?document=1':'/panel.json')},
    respondWith:value=>{pending=value;}});
  if (input.kind==='json') { assert.equal(pending,undefined); assert.equal(reads,0); }
  else {
    const response=await pending;
    if (input.kind==='root') {
      assert.equal(reads,0,'first document must not wait for the network');
      assert.equal(response.headers.get('X-Sentinel-Panel-Status'),'CONNECTING');
      assert.equal(response.headers.get('Cache-Control'),'no-store');
      assert((await response.text()).includes('data-panel-launch="true"'));
    } else { assert.equal(reads,1); assert.equal(await response.text(),'network-only-fixture'); }
  }
}

async function launch() {
  const reads=[],writes=[],listeners={},frames=[],timers=new Map();let serial=0;
  const stamp=Date.parse('2031-04-21T22:00:00Z');
  const status={textContent:'connecting'},detail={textContent:''};
  const retry={disabled:false,addEventListener:(_name,fn)=>{listeners.retry=fn;}};
  const document={body:{dataset:{panelLaunch:'true'}},visibilityState:'visible',
    getElementById:id=>({'launch-status':status,'launch-detail':detail,'launch-retry':retry})[id],
    addEventListener:(name,fn)=>{listeners[name]=fn;},
    open:()=>writes.push('open'),write:html=>{writes.push(html);document.body.dataset.panelLaunch='false';},close:()=>writes.push('close')};
  let elapsed=0;
  class Clock extends Date {static now(){return stamp+elapsed+(input.kind==='device-skew'?-600000:0);}}
  const responseHeaders = (status='CURRENT') => ({get:name =>
    name==='X-Sentinel-Server-Time' ? String(stamp+elapsed) : name==='X-Sentinel-Panel-Status' ? status : null});
  class Parser {parseFromString(){return {
    getElementById:()=>input.kind==='incomplete'?null:{},body:{dataset:{
      generatedAt:input.kind==='invalid-date'?'invalid':new Date(stamp+(input.kind==='future'?10000:
        input.kind==='stale'?-120000:input.kind==='exact-expiry'?-45000:0)).toISOString(),
      maxAgeSeconds:input.kind==='budget'?'99999':'45',refreshPending:input.kind==='pending'?'true':'false',
      observationCurrent:['partial','wrong-current-marker'].includes(input.kind)?'false':input.kind==='missing-marker'?undefined:'true'}}};}}
  const context={document,Date:Clock,DOMParser:Parser,AbortController,URL,
    performance:{now:()=>elapsed},navigator:{onLine:input.kind!=='offline'},
    location:{href:'https://fixture.invalid/',origin:'https://fixture.invalid'},
    window:{addEventListener:(name,fn)=>{listeners[name]=fn;}},
    requestAnimationFrame:fn=>frames.push(fn),
    setTimeout:(fn,delay)=>{timers.set(++serial,{fn,delay});return serial;},clearTimeout:id=>timers.delete(id),
    fetch:(_url,options)=>new Promise((resolve,reject)=>{
      const read={resolve,reject,options,aborted:false};
      options.signal.addEventListener('abort',()=>{read.aborted=true;});
      reads.push(read);
    })};
  vm.runInNewContext(input.source,context);
  assert.equal(reads.length,0,'first paint must precede the status fetch');
  frames.shift()();assert.equal(reads.length,0);frames.shift()();
  if(input.kind==='offline') {assert.equal(reads.length,0);assert.match(status.textContent,/STATUS NOT CURRENT — OFFLINE/);assert.equal(document.body.dataset.link,'offline');return;}
  assert.equal(reads.length,1);
  assert.equal(reads[0].options.cache,'no-store');
  const settle = () => new Promise(resolve => setImmediate(resolve));
  const takeTimer = delay => {
    const matches = [...timers].filter(([,timer]) => timer.delay === delay);
    assert.equal(matches.length,1,'expected one timer for '+delay);
    const [id,timer]=matches[0];
    timers.delete(id);
    return timer.fn;
  };
  if (input.kind.startsWith('suspend-') || input.kind==='retry-online') {
    const pendingRetry=input.kind.startsWith('suspend-retry-') || input.kind==='retry-online';
    const pagehide=input.kind.endsWith('-pagehide');
    const offline=input.kind.endsWith('-offline');
    const body=input.kind==='suspend-body-visibility';
    let completeBody;
    if (body) {
      reads[0].resolve({ok:true,status:200,url:context.location.href,
        headers:responseHeaders(),text:()=>new Promise(resolve=>{completeBody=resolve;})});
      await settle();
      assert.equal(typeof completeBody,'function','body transport must be pending before suspension');
    }
    let retiredRetry;
    if (pendingRetry) {
      reads[0].reject(new Error('connection reset'));
      await settle();
      const pending=[...timers].filter(([,timer])=>timer.delay===5000);
      assert.equal(pending.length,1,'failed launch owns one retry before suspension');
      retiredRetry=pending[0];
    }
    if (input.kind!=='retry-online') {
      if (offline) {
        context.navigator.onLine=false;listeners.offline();
        assert.match(status.textContent,/OFFLINE/);
      } else if (pagehide) {
        listeners.pagehide();
      } else {
        document.visibilityState='hidden';listeners.visibilitychange();
      }
      if (pendingRetry) {
        assert(!timers.has(retiredRetry[0]),'suspension must synchronously cancel the old retry');
      } else {
        assert(reads[0].aborted,'suspension must synchronously abort the old request');
      }
      if (offline) {
        context.navigator.onLine=true;listeners.online();
      } else if (pagehide) {
        listeners.pageshow({persisted:true});
      } else {
        document.visibilityState='visible';listeners.visibilitychange();
      }
    } else {
      listeners.online();
      assert(!timers.has(retiredRetry[0]),'an online wake must retire the old retry');
    }
    assert.equal(reads.length,2,'foreground return must immediately own one fresh request');
    listeners.online();listeners.pageshow({persisted:true});
    assert.equal(reads.length,2,'duplicate lifecycle events must share the fresh request');
    if (retiredRetry) { retiredRetry[1].fn(); }
    if (completeBody) { completeBody('late'); }
    else if (!pendingRetry) {
      if (offline) { reads[0].reject(new Error('late offline failure')); }
      else { reads[0].resolve({ok:true,status:200,url:context.location.href,
        headers:responseHeaders(),text:async()=> 'late'}); }
    }
    await settle();
    assert.deepEqual(writes,[],'retired completion cannot replace the current launcher');
    assert.equal(retry.disabled,true,'retired finally cannot release the new request control');
    assert.equal(reads.length,2,'retired callback cannot start another request');
    assert(![...timers.values()].some(timer=>timer.delay===5000),
      'retired completion cannot schedule a retry');
    reads[1].resolve({ok:true,status:200,url:context.location.href,
      headers:responseHeaders(),text:async()=> 'fresh'});
    await settle();
    assert.deepEqual(writes,['open','fresh','close'],'only the current request may install');
    assert.equal(timers.size,0);
    return;
  }
  if (['reset-recovery','timeout-recovery','unsettled-fetch','unsettled-body','backoff','pause-offline','pause-hidden',
       'foreign-progress','malformed-progress'].includes(input.kind)) {
    let completeBody;
    if (['timeout-recovery','unsettled-fetch','unsettled-body'].includes(input.kind)) {
      if (input.kind==='timeout-recovery') {
        reads[0].options.signal.addEventListener('abort',()=>reads[0].reject(new Error('aborted')));
      } else if (input.kind==='unsettled-body') {
        reads[0].resolve({ok:true,status:200,url:context.location.href,headers:responseHeaders(),
          text:()=>new Promise(resolve=>{completeBody=resolve;})});
        await settle();
      }
      elapsed=15000;
      takeTimer(15000)();
    } else if (input.kind.endsWith('-progress')) {
      reads[0].resolve({ok:false,status:503,
        url:input.kind==='foreign-progress'?'https://foreign.invalid/':context.location.href,
        headers:{get:()=>input.kind==='foreign-progress'?'Foreign phase':'%wrong'}});
    } else {
      reads[0].reject(new Error('connection reset'));
    }
    await settle();
    assert.equal(writes.length,0);
    assert.equal(retry.disabled,false,'a timed-out request must release the launch retry control');
    if(input.kind==='malformed-progress') {
      assert.equal(document.body.dataset.link,'connected');assert.match(status.textContent,/waiting for current status/);
    } else if(input.kind==='foreign-progress') {
      assert.equal(document.body.dataset.link,'unverified');assert.match(status.textContent,/response unverified/);
    } else {
      assert.equal(document.body.dataset.link,'connection');assert.match(status.textContent,/CONNECTION DELAYED/);
    }
    if (input.kind==='pause-offline' || input.kind==='pause-hidden') {
      if (input.kind==='pause-offline') {
        context.navigator.onLine=false;listeners.offline();
        assert.match(status.textContent,/OFFLINE/);
        assert.equal(timers.size,0);
        context.navigator.onLine=true;listeners.online();
      } else {
        document.visibilityState='hidden';listeners.visibilitychange();
        assert.equal(timers.size,0);
        document.visibilityState='visible';listeners.visibilitychange();
      }
    } else {
      takeTimer(5000)();
    }
    assert.equal(reads.length,2,'launch must recover without a click');
    if(input.kind==='backoff') {
      for (const delay of [10000,20000,30000,30000]) {
        reads.at(-1).reject(new Error('reset'));
        await settle();
        takeTimer(delay)();
      }
    }
    reads.at(-1).resolve({ok:true,status:200,url:context.location.href,
      headers:responseHeaders(),text:async()=> 'fresh'});
    await settle();
    assert.deepEqual(writes,['open','fresh','close']);
    if (completeBody) completeBody('late');
    if (input.kind==='unsettled-fetch') {
      reads[0].resolve({ok:true,status:200,url:context.location.href,headers:responseHeaders(),text:async()=> 'late'});
    }
    await settle();
    assert.deepEqual(writes,['open','fresh','close'],'a late read must not replace a working document');
    assert.equal(timers.size,0);
    return;
  }
  if(input.kind==='busy-progress') {
    assert.equal(reads[0].options.headers['X-Sentinel-Refresh'],'1');
    const phase='Software installation · verifying completion';
    reads[0].resolve({ok:false,status:503,url:context.location.href,
      headers:{get:key=>key==='X-Sentinel-Deployment-Progress'?encodeURIComponent(phase):null},
      text:()=>{throw new Error('retry downloaded a retained document');}});
    for(let i=0;i<12;i++)await Promise.resolve();
    assert.equal(status.textContent,phase);
    assert.equal(document.body.dataset.link,'connected');
    assert.equal(writes.length,0);
    const pending=[...timers.values()].filter(t=>t.delay===5000);
    assert.equal(pending.length,1);
    pending[0].fn();
    assert.equal(reads.length,2,'an unsigned launch refreshes automatically');
    return;
  }
  listeners.retry();listeners.retry();assert.equal(reads.length,1,'only one read in flight');
  if(input.kind==='hidden') {document.visibilityState='hidden';listeners.visibilitychange();}
  if(input.kind==='deadline') {const timer=[...timers.values()].find(t=>t.delay===15000);assert(timer);timer.fn();}
  reads[0].resolve({ok:input.kind!=='busy',status:input.kind==='busy'?503:200,
    url:input.kind==='foreign'?'https://foreign.invalid/':'https://fixture.invalid/',
    headers:responseHeaders(input.kind==='cached'?'LAST_KNOWN':['partial','wrong-partial-marker'].includes(input.kind)?'PARTIAL':'CURRENT'),text:async()=> 'fresh'});
  for(let i=0;i<12;i++)await Promise.resolve();
  if(['fresh','partial','device-skew'].includes(input.kind)) {assert.deepEqual(writes,['open','fresh','close']);assert.equal(reads.length,1);}
  else {assert.equal(writes.length,0,'invalid, late or hidden response installed authority');}
  if (['busy','incomplete','cached','stale'].includes(input.kind)) {
    assert.equal(document.body.dataset.link,'connected');
    assert.match(status.textContent,/waiting for current status/);
  }
}
(async()=>{if(input.target==='worker')await worker();else await launch();process.stdout.write('PASS\n');})()
  .catch(error=>{process.stderr.write(error.stack+'\n');process.exitCode=1;});
