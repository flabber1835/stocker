const {test,expect}=require('@playwright/test');
const fs=require('node:fs');
const http=require('node:http');
const {panelAssets,servePanelAsset}=require('./panel-assets.cjs');
const {startCapture,finishCapture}=require('./support/dashboard-journey-capture.cjs');

test.use({serviceWorkers:'block'});
test('opening recorder follows the rendered page through both renewals and detects a late grey border',async({page,request})=>{
  test.setTimeout(55000);
  const fixture=JSON.parse(fs.readFileSync(process.env.SENTINEL_DOM_FIXTURE,'utf8'));
  const assets=await panelAssets(request,fixture.green);
  const epoch=Date.now();
  const fixtureAt=Date.parse(fixture.now);
  const stamp=ms=>new Date(epoch+ms).toISOString();
  const start=Date.now();
  let polls=0;
  let bell,execute,completed,shadow;
  const server=http.createServer((req,res)=>{
    const path=new URL(req.url,'http://127.0.0.1').pathname;
    if (assets.has(path)) return servePanelAsset(res,assets.get(path));
    const now=stamp(Date.now()-start);
    if (path==='/panel.json') {
      polls++;
      if (polls===1) { bell=stamp(Date.now()-start+1); execute=stamp(Date.now()-start+2); }
      if (polls===3) completed=now;
      if (polls===4) shadow=now;
      const state=polls===1 ? 'WAITING_OPEN' : polls===2 ? 'EXECUTING' : 'SUCCEEDED';
      const verified=at=>({latest:{outcome:'VERIFIED',completed_at:at}});
      res.setHeader('content-type','application/json');
      return res.end(JSON.stringify({as_of:now,observation:{strict_current:true},
        rows:[{key:'trading_run',current:true,trading_run:{state,completed_at:completed,
          intent:{cycle_id:'recorder-cycle',plan_id:'recorder-plan',execution_open_at:bell,execute_at:execute}}}],
        verification_attempts:{PAPER:verified(polls>=3 ? completed : stamp(-1000)),
          SHADOW:verified(shadow || stamp(-1000))}}));
    }
    if (path!=='/') { res.writeHead(404);return res.end(); }
    res.writeHead(200,{'content-type':'text/html','cache-control':'no-store','x-sentinel-panel-status':'CURRENT'});
    const received=Date.parse(now);
    res.end(fixture.green.replace(/\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:\+00:00|Z)/g,
      original=>new Date(received+Date.parse(original)-fixtureAt).toISOString()));
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  let capture;
  try {
    const url='http://127.0.0.1:'+server.address().port+'/';
    capture=await startCapture(page,{url,opening:true,project:'recorder-replay'});
    await page.goto(url);
    await expect.poll(()=>capture.report.responses.filter(item=>item.document).length,{timeout:20000}).toBeGreaterThanOrEqual(3);
    await page.locator('body').evaluate(body=>{body.dataset.health='neutral';});
    await expect.poll(()=>capture.report.events.some(e=>e.meaningful_visible && e.healthy_border===false)).toBe(true);
    await page.locator('body').evaluate(body=>{body.dataset.health='green';});
    await capture.waitForCompletion();
    const report=await finishCapture(capture);
    expect(report.opening.displayed_at).toBeTruthy();
    expect(report.capture.reasons).toEqual([]);
    expect(report.acceptance.findings.map(f=>f.code)).toContain('HEALTHY_REFRESH_FLICKER');
  } finally {
    if (capture) await finishCapture(capture);
    server.closeAllConnections();
    await new Promise(resolve=>server.close(resolve));
  }
});
for (const residualMs of [3360,1550,670]) {
  test(`mobile receipt with ${residualMs}ms remaining requests evidence before expiry`,async({page,request})=>{
    const fixture=JSON.parse(fs.readFileSync(process.env.SENTINEL_DOM_FIXTURE,'utf8'));
    const documents=fixture.short_receipts[residualMs];
    const assets=await panelAssets(request,documents.initial,documents.next);
    const arrival=Date.parse(documents.arrival);
    const pending=[];
    await page.clock.install({time:new Date(arrival-60000)});
    await page.clock.pauseAt(new Date(arrival));
    await page.route('**/*', async route=>{
      const path=new URL(route.request().url()).pathname;
      if (assets.has(path)) return route.fulfill({status:200,...assets.get(path)});
      if (path!=='/') return route.fulfill({status:404,body:''});
      const body=route.request().isNavigationRequest() ? documents.initial :
        await new Promise(resolve=>pending.push(resolve));
      await route.fulfill({status:200,contentType:'text/html',
        headers:{'X-Sentinel-Panel-Status':'CURRENT'},body});
    });
    await page.goto('http://127.0.0.1:18947/');
    const headline=page.locator('#operational-state');
    const details=page.locator('#system-details');
    await details.evaluate(el=>{el.open=true;});
    await expect(headline).toHaveClass('state ok');
    await page.clock.runFor(Math.floor(residualMs/2));
    await expect.poll(()=>pending.length).toBe(1);
    await expect(headline).toHaveClass('state ok');
    if (residualMs===1550) {
      pending[0](documents.same);
      await expect(page.locator('body')).toHaveAttribute('data-max-age-seconds','0.775');
      await page.clock.runFor(775);
      await expect.poll(()=>pending.length).toBe(2);
    }
    if (residualMs!==670) {
      await page.clock.runFor(Date.parse(documents.received)-await page.evaluate(()=>Date.now()));
      await expect(headline).toHaveClass('state neutral');
      await expect(headline).toContainText('REFRESHING STATUS');
      await expect(page.locator('html')).not.toHaveClass(/not-current/);
    }
    pending.at(-1)(documents.next);
    await expect(page.locator('body')).toHaveAttribute('data-generated-at',documents.received);
    await expect(headline).toHaveClass(residualMs===1550?'state fail':'state ok');
    await expect(details).toHaveJSProperty('open',true);
    await expect(page.locator('[data-slot-id]')).toHaveCount(20);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  });
}

test('a loaded mobile page receives installation progress without downloading retained HTML',async({page,request})=>{
  const fixture=JSON.parse(fs.readFileSync(process.env.SENTINEL_DOM_FIXTURE,'utf8'));
  const docs=fixture.review_documents;
  const assets=await panelAssets(request,docs.initial);
  const start=Date.parse(docs.initial.match(/data-generated-at="([^"]+)"/)[1]);
  let polls=0;
  const label='Software installation · checking stored authority';
  await page.clock.install({time:new Date(start)});
  await page.route('**/*',async route=>{
    const req=route.request();
    const path=new URL(req.url()).pathname;
    if(assets.has(path))return route.fulfill({status:200,...assets.get(path)});
    if(path!=='/')return route.fulfill({status:404,body:''});
    if(req.isNavigationRequest())return route.fulfill({status:200,contentType:'text/html',
      headers:{'X-Sentinel-Panel-Status':'CURRENT'},body:docs.initial});
    expect(req.headers()['x-sentinel-refresh']).toBe('1');
    polls++;
    return route.fulfill({status:503,headers:polls===1?
      {'Retry-After':'5','X-Sentinel-Deployment-Progress':encodeURIComponent(label)}:{'Retry-After':'5'},body:''});
  });
  await page.goto('http://127.0.0.1:18947/');
  const progress=page.locator('#deployment-progress');
  const details=page.locator('#system-details');
  await expect(progress).toBeHidden();
  await expect(details.locator('#operator-review')).toBeHidden();
  await page.clock.runFor(5000);
  await expect(progress).toHaveText(label);
  await expect(progress).toBeVisible();
  await expect(page.locator('body')).toHaveAttribute('data-generated-at',new Date(start).toISOString().replace('.000Z','+00:00'));
  await expect(page.locator('#review-acknowledge')).toHaveCount(0);
  await page.clock.runFor(5000);
  await expect(progress).toBeHidden();
  await expect(details).toHaveJSProperty('open',false);
});

test('near-expiry PARTIAL renews its current book card with bounded reads',async({page,request})=>{
  const fixture=JSON.parse(fs.readFileSync(process.env.SENTINEL_DOM_FIXTURE,'utf8'));
  const documents=fixture.short_partial;
  const assets=await panelAssets(request,documents.initial,documents.same,documents.next);
  const arrival=Date.parse(documents.arrival);
  const pending=[];
  await page.clock.install({time:new Date(arrival-60000)});
  await page.clock.pauseAt(new Date(arrival));
  await page.route('**/*',async route=>{
    const path=new URL(route.request().url()).pathname;
    if(assets.has(path))return route.fulfill({status:200,...assets.get(path)});
    if(path!=='/')return route.fulfill({status:404,body:''});
    const body=route.request().isNavigationRequest() ? documents.initial :
      await new Promise(resolve=>pending.push(resolve));
    await route.fulfill({status:200,contentType:'text/html',
      headers:{'X-Sentinel-Panel-Status':'PARTIAL'},body});
  });
  await page.goto('http://127.0.0.1:18947/');
  const body=page.locator('body');
  const book=page.locator('#status-book');
  const plan=page.locator('#status-paper_plan');
  await expect(body).toHaveAttribute('data-observation-current','false');
  await expect(book).toHaveAttribute('data-current','true');
  await expect(page.locator('.overview-card.core-slots')).toHaveAttribute('data-current','true');
  await expect(plan).toHaveAttribute('data-current','false');
  await expect(page.locator('#operational-state')).toHaveClass('state neutral');
  await page.clock.runFor(335);
  await expect.poll(()=>pending.length).toBe(1);
  pending[0](documents.same);
  await expect(body).toHaveAttribute('data-max-age-seconds','0.335');
  await expect(body).toHaveAttribute('data-observation-current','false');
  await expect(book).toHaveAttribute('data-current','true');
  await page.clock.runFor(335);
  await expect.poll(()=>pending.length).toBe(2);
  await expect(body).toHaveAttribute('data-max-age-seconds','0.335');
  await page.clock.runFor(20);
  pending[1](documents.next);
  await expect(body).toHaveAttribute('data-generated-at',documents.received);
  await expect(body).toHaveAttribute('data-observation-current','false');
  await expect(book).toHaveAttribute('data-current','true');
  await expect(plan).toHaveAttribute('data-current','false');
  await expect(page.locator('#operational-state')).toHaveClass('state neutral');
  await expect(page.locator('html')).not.toHaveClass(/not-current/);
  await page.clock.runFor(1000);
  expect(pending).toHaveLength(2);
  await expect(book).toHaveAttribute('data-current','true');
});

test('refresh preserves the live document, scroll, focus and details while border follows evidence',async({page,request})=>{
  const fixture=JSON.parse(fs.readFileSync(process.env.SENTINEL_DOM_FIXTURE,'utf8'));
  const assets=await panelAssets(request,fixture.green,fixture.red);
  let html=fixture.green,release=null,held=false,requests=0;
  let serverNow=fixture.now;
  await page.clock.install({time:new Date(fixture.now)});
  await page.route('**/*',async route=>{
    const path=new URL(route.request().url()).pathname;
    if(assets.has(path))return route.fulfill({status:200,...assets.get(path)});
    if(path!=='/')return route.fulfill({status:404,body:''});
    requests++;
    if(held)await new Promise(resolve=>{release=resolve;});
    await route.fulfill({status:200,contentType:'text/html',headers:{'X-Sentinel-Panel-Status':'CURRENT'},body:html.replace(/data-generated-at="[^"]+"/,'data-generated-at="'+serverNow+'"')});
  });
  await page.goto('http://127.0.0.1:18947/');
  await expect.poll(()=>page.locator('.brand img[data-banner-src]').evaluate(img=>img.naturalWidth)).toBe(512);
  await expect(page.locator('#market-open-countdown')).toHaveText('Market open in 1 day 22 hours 4 minutes');
  await expect(page.locator('#operational-state')).toHaveCSS('clip-path','inset(50%)');
  await expect(page.locator('#review-acknowledge, #health-history, footer, #plan-readiness, .overview-mode, .mode-guide')).toHaveCount(0);
  await expect(page.locator('.brand')).toHaveCSS('border-top-width','4px');
  const baseline=await page.evaluate(()=>{
    const details=document.getElementById('system-details');details.open=true;
    details.querySelector('summary').focus();window.scrollTo(0,700);
    window.saved={body:document.body,wrap:document.querySelector('.wrap'),brand:document.querySelector('.brand'),
      slot:document.querySelector('[data-slot-id="0"]'),details,focus:document.activeElement};
    return {scroll:scrollY,border:getComputedStyle(saved.brand).borderTopColor};
  });
  held=true;
  await page.clock.runFor(5000);
  await expect.poll(()=>requests).toBe(2);
  expect(await page.locator('.brand').evaluate(el=>getComputedStyle(el).borderTopColor)).toBe(baseline.border);
  serverNow=new Date(Date.parse(fixture.now)+5000).toISOString();
  held=false;release();
  await expect(page.locator('body')).toHaveAttribute('data-generated-at',serverNow);
  const after=await page.evaluate(()=>({
    same:saved.body===document.body&&saved.wrap===document.querySelector('.wrap')&&
      saved.brand===document.querySelector('.brand')&&saved.slot===document.querySelector('[data-slot-id="0"]')&&
      saved.details===document.getElementById('system-details'),
    focus:saved.focus===document.activeElement,open:saved.details.open,scroll:scrollY,
    border:getComputedStyle(saved.brand).borderTopColor,
    expected:getComputedStyle(document.body).getPropertyValue('--fail').trim()
  }));
  expect(after.same).toBe(true);expect(after.focus).toBe(true);expect(after.open).toBe(true);
  expect(after.scroll).toBe(baseline.scroll);expect(after.border).toBe(baseline.border);
  html=fixture.red;serverNow=new Date(Date.parse(fixture.now)+10000).toISOString();await page.clock.runFor(5000);
  await expect(page.locator('body')).toHaveAttribute('data-health','red');
  expect(await page.locator('.brand').evaluate(el=>getComputedStyle(el).borderTopColor)).not.toBe(baseline.border);
  await page.context().setOffline(true);
  await expect(page.locator('.brand')).toHaveCSS('border-top-color','rgb(139, 139, 147)');
  await page.clock.runFor(1000);
  await expect(page.locator('#market-open-countdown')).toHaveText('Market-open time not current');
});
