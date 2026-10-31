'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const http=require('node:http');
const crypto=require('node:crypto');
const {startJourneyTransport,bindTransport}=require('./support/dashboard-journey-transport.cjs');

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
    assert.ok(records.slice(1).every(item=>item.kind==='refresh' && item.total_ms>=19));
    assert.equal(bindTransport({responses:observed},proxy.profile).matched,true);
    observed[1].document.sha256='changed';assert.equal(bindTransport({responses:observed},proxy.profile).matched,false);
    const rejected=await fetch(proxy.url,{method:'POST',body:'not forwarded'});assert.equal(rejected.status,405);
    assert.equal(requests,3);
  } finally {
    await proxy.close();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));
  }
});
