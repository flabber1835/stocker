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
  class Clock extends Date {static now(){return stamp;}}
  class Parser {parseFromString(){return {
    getElementById:()=>input.kind==='incomplete'?null:{},body:{dataset:{
      generatedAt:input.kind==='invalid-date'?'invalid':new Date(stamp+(input.kind==='future'?10000:input.kind==='stale'?-120000:0)).toISOString(),
      maxAgeSeconds:input.kind==='budget'?'99999':'45',refreshPending:input.kind==='pending'?'true':'false'}}};}}
  const context={document,Date:Clock,DOMParser:Parser,AbortController,URL,
    navigator:{onLine:input.kind!=='offline'},
    location:{href:'https://fixture.invalid/',origin:'https://fixture.invalid'},
    window:{addEventListener:(name,fn)=>{listeners[name]=fn;}},
    requestAnimationFrame:fn=>frames.push(fn),
    setTimeout:(fn,delay)=>{timers.set(++serial,{fn,delay});return serial;},clearTimeout:id=>timers.delete(id),
    fetch:(_url,options)=>new Promise((resolve,reject)=>{reads.push({resolve,reject,options});})};
  vm.runInNewContext(input.source,context);
  assert.equal(reads.length,0,'first paint must precede the status fetch');
  frames.shift()();assert.equal(reads.length,0);frames.shift()();
  if(input.kind==='offline') {assert.equal(reads.length,0);assert.match(status.textContent,/OFFLINE/);return;}
  assert.equal(reads.length,1);
  assert.equal(reads[0].options.cache,'no-store');
  listeners.retry();listeners.retry();assert.equal(reads.length,1,'only one read in flight');
  if(input.kind==='hidden') {document.visibilityState='hidden';listeners.visibilitychange();}
  if(input.kind==='deadline') {const timer=[...timers.values()].find(t=>t.delay===15000);assert(timer);timer.fn();}
  reads[0].resolve({ok:input.kind!=='busy',status:input.kind==='busy'?503:200,
    url:input.kind==='foreign'?'https://foreign.invalid/':'https://fixture.invalid/',
    headers:{get:()=>input.kind==='cached'?'LAST_KNOWN':'CURRENT'},text:async()=> 'fresh'});
  for(let i=0;i<12;i++)await Promise.resolve();
  if(input.kind==='fresh') {assert.deepEqual(writes,['open','fresh','close']);assert.equal(reads.length,1);}
  else {assert.equal(writes.length,0,'invalid, late or hidden response installed authority');}
}
(async()=>{if(input.target==='worker')await worker();else await launch();process.stdout.write('PASS\n');})()
  .catch(error=>{process.stderr.write(error.stack+'\n');process.exitCode=1;});
