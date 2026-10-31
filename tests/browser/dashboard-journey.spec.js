'use strict';
const {test,expect}=require('@playwright/test');
const fs=require('node:fs/promises');
const http=require('node:http');
const {startCapture,finishCapture}=require('./support/dashboard-journey-capture.cjs');

test.describe('Unmodified dashboard journey', () => {
  test('records cold navigation and two actual HTML refreshes',async ({page},testInfo) => {
    await fs.mkdir(testInfo.outputDir,{recursive:true});
    const capture=await startCapture(page,{url:process.env.SENTINEL_JOURNEY_BASE_URL,
      outputDir:testInfo.outputDir,project:testInfo.project.name,maxDurationMs:110000,maxEvents:300});
    let report;
    try {
      await page.goto(process.env.SENTINEL_JOURNEY_BASE_URL,{waitUntil:'domcontentloaded',timeout:105000});
      await capture.waitForCompletion();
    } catch (_) { capture.recordFailure('NAVIGATION_OR_RECORDER_ERROR'); }
    finally {
      report=await finishCapture(capture);
      const filename=testInfo.outputPath('journey.json');
      await fs.writeFile(filename,JSON.stringify(report,null,2)+'\n');
      await testInfo.attach('dashboard-journey',{path:filename,contentType:'application/json'});
    }
    expect(report.capture.status,JSON.stringify(report.capture)).toBe('COMPLETE');
    expect(report.acceptance.status,JSON.stringify(report.acceptance)).toBe('PASS');
  });
});

test.describe('Recorder integrity', () => {
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
