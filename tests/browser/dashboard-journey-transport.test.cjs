'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const http=require('node:http');
const crypto=require('node:crypto');
const {performance}=require('node:perf_hooks');
const {setTimeout:delay}=require('node:timers/promises');
const {startJourneyTransport,bindTransport,holdUntil}=require('./support/dashboard-journey-transport.cjs');

test('a refresh rechecks its monotonic deadline after an early timer wake',async()=>{
  const controller=new AbortController();
  let now=10.25;
  const waits=[];
  async function earlyTimer(ms,_,{signal}) {
    assert.equal(signal,controller.signal);
    waits.push(ms);
    now=waits.length===1 ? 19.75 : 20;
  }
  await holdUntil(20,controller.signal,()=>now,earlyTimer);
  assert.deepEqual(waits,[10,1]);
  await holdUntil(19,controller.signal,()=>now,()=>assert.fail('a late upstream response needs no delay'));
});

test('aborting a held refresh leaves a concurrent refresh on its own deadline',async()=>{
  const server=http.createServer((_,response)=>response.end('healthy'));
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const proxy=await startJourneyTransport({upstreamUrl:`http://127.0.0.1:${server.address().port}/`,refreshFloorMs:1500});
  const controller=new AbortController();
  const records=proxy.profile.upstream_requests;
  async function awaitUpstream(index) {
    const deadline=performance.now()+5000;
    while (records[index]?.upstream_ms==null && performance.now()<deadline) await delay(1);
    assert.ok(Number.isFinite(records[index]?.upstream_ms),`missing upstream response ${index}`);
  }
  try {
    await (await fetch(proxy.url)).text();
    const canceled=assert.rejects(fetch(proxy.url,{signal:controller.signal}),{name:'AbortError'});
    await awaitUpstream(1);
    const surviving=fetch(proxy.url);
    await awaitUpstream(2);
    assert.equal(records[1].served,false);
    controller.abort();
    await canceled;
    assert.equal(await (await surviving).text(),'healthy');
    assert.equal(records[1].served,false);
    assert.equal(records[2].served,true);
    assert.ok(records[2].total_ms>=proxy.profile.refresh_floor_ms);
  } finally {
    controller.abort();
    await proxy.close();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));
  }
});

test('loopback proxy preserves entity/header verdict and floors refresh only',async()=>{
  const entity=Buffer.from('<html>Original entity \u00a3; this is transport verification only.</html>');
  let requests=0;
  const server=http.createServer((request,response)=>{
    requests+=1;
    assert.equal(request.headers.cookie,undefined);assert.equal(request.headers.authorization,undefined);
    response.writeHead(200,{'Content-Type':'text/html','Cache-Control':'no-store',
      'X-Sentinel-Panel-Status':'CURRENT','Content-Length':entity.length});response.end(entity);
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const proxy=await startJourneyTransport({upstreamUrl:`http://127.0.0.1:${server.address().port}/`,refreshFloorMs:20});
  const observed=[];
  try {
    for (let index=0;index<3;index++) {
      const response=await fetch(proxy.url,{headers:{'sec-fetch-mode':index ? 'cors' : 'navigate',
        cookie:'MUST_NOT_FORWARD',authorization:'MUST_NOT_FORWARD'}});
      const body=Buffer.from(await response.arrayBuffer());assert.deepEqual(body,entity);
      assert.equal(response.headers.get('cache-control'),'no-store');
      assert.equal(response.headers.get('x-sentinel-panel-status'),'CURRENT');
      observed.push({request_id:index+1,kind:index ? 'refresh' : 'navigation',http_status:200,
        panel_status:'CURRENT',cache_control:'no-store',document:{sha256:crypto.createHash('sha256').update(body).digest('hex')}});
    }
    const records=proxy.profile.upstream_requests;
    assert.equal(records[0].kind,'navigation');assert.equal(records[0].hold_ms,0);
    for (const record of records.slice(1)) {
      assert.equal(record.kind,'refresh');
      assert.ok(record.total_ms>=proxy.profile.refresh_floor_ms,`early refresh at ${record.total_ms} ms`);
    }
    assert.equal(bindTransport({responses:observed},proxy.profile).matched,true);
    for (const invalid of [19.99,null,NaN]) {
      const profile={...proxy.profile,upstream_requests:[records[0],{...records[1],total_ms:invalid},records[2]]};
      assert.deepEqual(bindTransport({responses:observed},profile).errors,['REFRESH_FLOOR_MISSED_2']);
    }
    observed[1].document.sha256='changed';assert.equal(bindTransport({responses:observed},proxy.profile).matched,false);
    const rejected=await fetch(proxy.url,{method:'POST',body:'not forwarded'});assert.equal(rejected.status,405);
    assert.equal(requests,3);
  } finally {
    await proxy.close();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));
  }
});
