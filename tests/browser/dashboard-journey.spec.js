'use strict';
const {test,expect}=require('@playwright/test');
const fs=require('node:fs/promises');
const http=require('node:http');
const {startCapture,finishCapture,assessCapture}=require('./support/dashboard-journey-capture.cjs');
const {startJourneyTransport,bindTransport}=require('./support/dashboard-journey-transport.cjs');

test.describe('Unmodified dashboard journey', () => {
  test('records cold navigation and two actual HTML refreshes',async ({page},testInfo) => {
    await fs.mkdir(testInfo.outputDir,{recursive:true});
    const upstreamUrl=process.env.SENTINEL_JOURNEY_BASE_URL;
    const floor=process.env.SENTINEL_JOURNEY_REFRESH_FLOOR_MS;
    if (floor!==undefined && !/^\d+$/.test(floor)) throw new Error('Invalid refresh-floor profile');
    const transport=floor===undefined ? null : await startJourneyTransport({upstreamUrl,refreshFloorMs:Number(floor)});
    let capture,report;
    try {
      const url=transport ? transport.url : upstreamUrl;
      capture=await startCapture(page,{url,outputDir:testInfo.outputDir,project:testInfo.project.name,maxDurationMs:110000,maxEvents:300});
      try {
        await page.goto(url,{waitUntil:'domcontentloaded',timeout:105000});
        await capture.waitForCompletion();
      } catch (_) { capture.recordFailure('NAVIGATION_OR_RECORDER_ERROR'); }
      finally {report=await finishCapture(capture);}
    } finally {if (transport) await transport.close();}
    report.upstream_origin=new URL(upstreamUrl).origin;
    report.browser={engine:testInfo.project.use.browserName,version:page.context().browser().version(),
      service_workers:'allow',viewport:testInfo.project.use.viewport || {width:393,height:852}};
    report.transport_profile=transport ? {...transport.profile,binding:bindTransport(report,transport.profile)} : {name:'direct',refresh_floor_ms:0};
    if (transport && !report.transport_profile.binding.matched) {
      report.capture.complete=false;report.capture.status='INCOMPLETE';report.capture.reasons.push('TRANSPORT_ENTITY_MISMATCH');
      report.acceptance=assessCapture(report);
    }
    const filename=testInfo.outputPath('journey.json');
    await fs.writeFile(filename,JSON.stringify(report,null,2)+'\n');
    await testInfo.attach('dashboard-journey',{path:filename,contentType:'application/json'});
    expect(report.capture.status,JSON.stringify(report.capture)).toBe('COMPLETE');
    expect(report.acceptance.status,JSON.stringify(report.acceptance)).toBe('PASS');
  });
});

test.describe('Recorder integrity', () => {
  for (const interrupted of [false,true]) {
    test(`records actual banner decoding and ${interrupted ? 'refuses an interrupted' : 'accepts a valid'} PNG`,async ({page},testInfo)=>{
      // This is recorder integrity, not financial acceptance: all document
      // labels explicitly identify the small synthetic recorder-only fixture.
      const assetPath='/static/caesars-palace-512.png';
      const upstream=await page.request.get(assetPath);
      expect(upstream.status()).toBe(200);
      const png=await upstream.body();
      const timers=new Set(),sockets=new Set();
      let generation=0;
      const server=http.createServer((request,response)=>{
        const url=new URL(request.url,'http://127.0.0.1');
        if (url.pathname===assetPath) {
          response.writeHead(200,{'Content-Type':'image/png','Cache-Control':'no-store','Content-Length':png.length});
          if (!interrupted) {response.end(png);return;}
          response.write(png.subarray(0,1024));
          const timer=setTimeout(()=>{timers.delete(timer);response.destroy();},50);
          timers.add(timer);response.once('close',()=>{clearTimeout(timer);timers.delete(timer);});
          return;
        }
        const index=generation++,stamp=new Date(Date.now()+index).toISOString();
        const next=index<2 ? `<script>setTimeout(async()=>{const response=await fetch(location.href,{cache:'no-store'});const body=await response.text();document.open();document.write(body);document.close();},250);</script>` : '';
        const html=`<html><head><style>.brand img{width:128px;height:128px}</style></head><body data-generated-at="${stamp}" data-max-age-seconds="45" data-refresh-pending="false"><div class="brand"><img src="${assetPath}?recorder=unrecorded-query-token" alt="Recorder image"></div><span id="operational-state" class="state ok">RECORDER FIXTURE ONLY</span><section class="next-plan">Recorder fixture only</section>${next}</body></html>`;
        response.writeHead(200,{'Content-Type':'text/html','Cache-Control':'no-store','X-Sentinel-Panel-Status':'CURRENT'});
        response.end(html);
      });
      server.on('connection',socket=>{sockets.add(socket);socket.once('close',()=>sockets.delete(socket));});
      await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
      const url=`http://127.0.0.1:${server.address().port}/`;
      const capture=await startCapture(page,{url,project:testInfo.project.name,maxDurationMs:5000});
      let report;
      try {
        await page.goto(url,{waitUntil:'domcontentloaded'});
        await capture.waitForCompletion();
      } finally {
        report=await finishCapture(capture);
        await page.goto('about:blank',{waitUntil:'commit',timeout:5000}).catch(()=>undefined);
        for (const timer of timers) clearTimeout(timer);
        const stopped=new Promise(resolve=>server.close(resolve));
        for (const socket of sockets) socket.destroy();
        await stopped;
      }
      const states=report.events.filter(item=>item.type==='visible-state' && item.banner_present);
      expect(states.length).toBeGreaterThan(0);
      expect(report.events.some(item=>item.type==='banner-response' && item.http_status===200)).toBe(true);
      expect(JSON.stringify(report)).not.toContain('unrecorded-query-token');
      const codes=report.acceptance.findings.map(item=>item.code);
      if (interrupted) {
        expect(states.some(item=>item.banner_complete && item.banner_width===0 && !item.banner_displayed)).toBe(true);
        expect(report.events.some(item=>item.type==='banner-request-failed')).toBe(true);
        expect(codes).toContain('BANNER_UNAVAILABLE');
        expect(report.acceptance.status).toBe('FAIL');
      } else {
        expect(states.some(item=>item.banner_displayed && item.banner_width===512 && item.banner_height===512)).toBe(true);
        expect(codes).not.toContain('BANNER_UNAVAILABLE');
        expect(codes).not.toContain('MISSING_BANNER_EVIDENCE');
      }
      await testInfo.attach('banner-recorder-integrity',{body:Buffer.from(JSON.stringify({
        purpose:'RECORDER_INTEGRITY_ONLY',interrupted,events:report.events,findings:report.acceptance.findings
      })),contentType:'application/json'});
    });
  }

  test('retains a short amber transition and document.open replacement',async ({page},testInfo) => {
    const first='2026-10-31T00:00:00.000Z',second='2026-10-31T00:00:01.000Z';
    const body=(generation,label)=>`<html><body data-generated-at="${generation}" data-max-age-seconds="45"><span id="operational-state" class="state ok">${label}</span><section class="next-plan">Recorder fixture only</section></body></html>`;
    const replacement=body(second,'SECOND DOCUMENT');
    const fixture=body(first,'FIRST DOCUMENT').replace('</body>',`<script>
      setTimeout(()=>{document.getElementById('operational-state').className='state warn'},100);
      setTimeout(()=>{document.getElementById('operational-state').className='state ok'},200);
      setTimeout(()=>{document.open();document.write(${JSON.stringify(replacement)});document.close();
        setTimeout(()=>{document.getElementById('operational-state').className='state fail'},100)},300);
      </script></body>`);
    const server=http.createServer((request,response)=>{response.writeHead(200,{'Content-Type':'text/html','Cache-Control':'no-store'});response.end(fixture);});
    await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
    const capture=await startCapture(page,{url:`http://127.0.0.1:${server.address().port}/`,project:testInfo.project.name,maxDurationMs:5000});
    try {
      await page.goto(`http://127.0.0.1:${server.address().port}/`,{waitUntil:'domcontentloaded'});
      await expect.poll(()=>capture.report.events.some(event=>event.type==='badge-transition' && event.generated_at===second && event.headline_class==='state fail')).toBe(true);
      const events=capture.report.events;
      expect(events.some(event=>event.type==='meaningful-content' && event.generated_at===first)).toBe(true);
      expect(events.some(event=>event.type==='meaningful-content' && event.generated_at===second)).toBe(true);
      expect(events.some(event=>event.type==='badge-transition' && event.generated_at===first && event.headline_class==='state warn')).toBe(true);
      expect(events.filter(event=>event.type==='document-root')).toHaveLength(2);
    } finally {
      const report=await finishCapture(capture);
      await testInfo.attach('recorder-integrity',{body:Buffer.from(JSON.stringify({purpose:'RECORDER_INTEGRITY_ONLY',events:report.events})),contentType:'application/json'});
      await new Promise(resolve=>server.close(resolve));
    }
  });
});
