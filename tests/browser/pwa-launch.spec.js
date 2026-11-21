'use strict';
const {test,expect}=require('@playwright/test');
const http=require('node:http');
const assert=require('node:assert/strict');
const {panelAssets,servePanelAsset}=require('./panel-assets.cjs');

async function fixture(request,{workerOnly=false,legacyWorker=false,partial=false,externalStyle=false}={}) {
  let source=await (await request.get('/service-worker.js')).text();
  const match=source.match(/^const LAUNCH_DOCUMENT = (.+);$/m);
  expect(match,'shipped worker must expose only its static launch document').not.toBeNull();
  const launch=JSON.parse(match[1]);
  if(legacyWorker) {
    const current=source;
    source=source.replace(/  var url = new URL\(event.request.url\);[\s\S]*?\n    return;\n  }\n/,'');
    expect(source).not.toBe(current);
  }
  let template=await (await request.get('/?document=1')).text();
  if(externalStyle) {
    const inline=/<style id="dashboard-stylesheet" data-source-href="([^"]+)">[\s\S]*?<\/style>/;
    expect(template).toMatch(inline);
    template=template.replace(inline,'<link id="dashboard-stylesheet" rel="stylesheet" href="$1">');
  }
  const assets=await panelAssets(request,template);
  const pending=new Set(),sockets=new Set(),requests=[];
  let held=true;
  function current(response) {
    // The private ASGI fixture has unconfigured/negative rows. Move only its
    // synthetic document time; never fabricate a healthy financial verdict.
    const html=template.replace(/data-generated-at="[^"]+"/,
      `data-generated-at="${new Date().toISOString()}"`)
      .replace(/(<body\b[^>]*\bdata-observation-current=")[^"]+("[^>]*>)/,
        `$1${partial?'false':'true'}$2`);
    response.writeHead(200,{'Content-Type':'text/html','Cache-Control':'no-store',
      'X-Sentinel-Panel-Status':partial?'PARTIAL':'CURRENT'});response.end(html);
  }
  const server=http.createServer((req,res)=>{
    const path=new URL(req.url,'http://fixture.invalid').pathname;
    if(assets.has(path)) {
      servePanelAsset(res,assets.get(path));return;
    }
    if(path==='/service-worker.js') {
      res.writeHead(200,{'Content-Type':'application/javascript','Cache-Control':'no-store'});
      res.end(source);return;
    }
    if(path==='/install') {
      res.writeHead(200,{'Content-Type':'text/html','Cache-Control':'no-store'});
      res.end('<!doctype html><title>Private worker installation</title><script>navigator.serviceWorker.register("/service-worker.js",{scope:"/",updateViaCache:"none"});</script>');return;
    }
    if(path==='/') {
      const navigation=req.headers['sec-fetch-mode']==='navigate'||
        req.headers['sec-fetch-dest']==='document'||(req.headers.accept||'').includes('text/html');
      requests.push({navigation,at:Date.now()});
      if(navigation && !workerOnly) {
        res.writeHead(200,{'Content-Type':'text/html','Cache-Control':'no-store',
          'X-Sentinel-Panel-Status':'CONNECTING'});res.end(launch);return;
      }
      if(held) {pending.add(res);res.once('close',()=>pending.delete(res));return;}
      current(res);return;
    }
    res.writeHead(404);res.end();
  });
  server.on('connection',socket=>{sockets.add(socket);socket.once('close',()=>sockets.delete(socket));});
  await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
  return {url:`http://127.0.0.1:${server.address().port}/`,requests,
    release(){held=false;for(const response of pending) current(response);pending.clear();},
    async close(){for(const response of pending)response.destroy();
      const stopped=new Promise(resolve=>server.close(resolve));
      for(const socket of sockets)socket.destroy();await stopped;}};
}

test.describe('First document before current evidence',()=>{
  test.use({serviceWorkers:'block'});
  async function firstStyledDocument(page,request,{externalStyle=false,failed=false}={}) {
    const f=await fixture(request,{externalStyle});
    let cssRequests=0,releaseCSS;
    const held=new Promise(resolve=>{releaseCSS=resolve;});
    await page.route('**/*.css',async route=>{
      cssRequests++;
      if(failed)return route.abort('failed');
      await held;return route.continue();
    });
    try {
      await page.goto(f.url,{waitUntil:'domcontentloaded'});
      await expect(page.locator('#launch-status')).toBeVisible();
      f.release();await expect(page.locator('#operational-state')).toBeAttached();
      const state=await page.evaluate(()=>{
        const sheet=document.getElementById('dashboard-stylesheet');
        return {inline:sheet.tagName==='STYLE',ready:!!sheet.sheet&&sheet.sheet.cssRules.length>0,
          border:getComputedStyle(document.querySelector('.brand')).borderTopWidth};
      });
      return {...state,cssRequests};
    } finally {releaseCSS();f.release();await page.goto('about:blank',{waitUntil:'commit'});await f.close();}
  }
  function atomicStyle(state) {
    assert.equal(state.inline,true,'essential styles depended on another request');
    assert.equal(state.ready,true,'meaningful dashboard appeared before its styles');
    assert.equal(state.border,'4px','meaningful dashboard was unstyled');
    assert.equal(state.cssRequests,0,'essential styles started another request');
  }
  for(const failed of [false,true]) {
    test(`cold launch is styled when external CSS is ${failed?'unavailable':'held'}`,async({page,request})=>{
      atomicStyle(await firstStyledDocument(page,request,{failed}));
    });
  }
  test('restoring an external stylesheet reproduces the cold-launch failure',async({page,request})=>{
    const state=await firstStyledDocument(page,request,{externalStyle:true});
    expect(()=>atomicStyle(state)).toThrow(/essential styles depended on another request/);
  });
  test('a visible cold launch recovers from a lost first status request',async({page,request})=>{
    const f=await fixture(request);
    let interrupted=false;
    try {
      await page.route(f.url,async route=>{
        if (!interrupted && !route.request().isNavigationRequest()) {
          interrupted=true;
          return route.abort('connectionreset');
        }
        return route.continue();
      });
      await page.goto(f.url,{waitUntil:'domcontentloaded'});
      await expect(page.locator('#launch-status')).toContainText('CONNECTION DELAYED');
      expect(interrupted).toBe(true);
      await expect(page.locator('#operational-state')).toHaveCount(0);
      f.release();
      await expect(page.locator('#operational-state')).toBeVisible({timeout:12000});
    } finally {await page.goto('about:blank');await f.close();}
  });
  test('a fresh partial response installs with explicit non-current observation metadata',async({page,request})=>{
    const f=await fixture(request,{partial:true});
    try {
      await page.goto(f.url,{waitUntil:'domcontentloaded'});
      await expect(page.locator('#launch-status')).toBeVisible();
      f.release();await expect(page.locator('.brand')).toBeVisible();
      await expect(page.locator('body')).toHaveAttribute('data-observation-current','false');
      await expect(page.locator('body')).toHaveAttribute('data-refresh-pending','false');
      await expect(page.locator('#review-acknowledge')).toHaveCount(0);
    } finally {f.release();await page.goto('about:blank',{waitUntil:'commit',timeout:3000}).catch(()=>{});await f.close();}
  });
  test('uncontrolled iPhone-sized launch paints while the status request is held',async({page,request},testInfo)=>{
    const f=await fixture(request);
    try {
      const started=Date.now();await page.goto(f.url,{waitUntil:'domcontentloaded'});
      await expect(page.locator('#launch-status')).toBeVisible();
      expect(Date.now()-started).toBeLessThan(2000);
      await expect.poll(()=>f.requests.filter(x=>!x.navigation).length).toBe(1);
      await expect(page.locator('#operational-state')).toHaveCount(0);
      await testInfo.attach('launch-before-status',{body:await page.screenshot(),contentType:'image/png'});
      f.release();await expect(page.locator('.brand')).toBeVisible();
      await expect(page.locator('[data-panel-launch]')).toHaveCount(0);
    } finally {f.release();await page.goto('about:blank',{waitUntil:'commit',timeout:3000}).catch(()=>{});await f.close();}
  });
});

test.describe('Installed worker launch',()=>{
  test.skip(({browserName})=>browserName!=='chromium');
  test.use({serviceWorkers:'allow'});
  test('a previous network-first worker also receives the fast server launch document',async({page,request})=>{
    const f=await fixture(request,{legacyWorker:true});
    try {
      await page.goto(f.url+'install');await page.evaluate(()=>navigator.serviceWorker.ready);
      await expect.poll(()=>page.evaluate(()=>Boolean(navigator.serviceWorker.controller))).toBe(true);
      const started=Date.now();await page.goto(f.url,{waitUntil:'domcontentloaded'});
      await expect(page.locator('#launch-status')).toBeVisible();
      expect(Date.now()-started).toBeLessThan(2000);
      await expect.poll(()=>f.requests.filter(x=>!x.navigation).length).toBe(1);
      expect(f.requests.filter(x=>x.navigation)).toHaveLength(1);
      await expect(page.locator('#operational-state')).toHaveCount(0);
      f.release();await expect(page.locator('.brand')).toBeVisible();
    } finally {f.release();await page.goto('about:blank',{waitUntil:'commit',timeout:3000}).catch(()=>{});await f.close();}
  });
  test('closed page reopens immediately through the real worker with no cached health',async({context,page,request},testInfo)=>{
    const f=await fixture(request,{workerOnly:true});
    let reopened;
    try {
      await page.goto(f.url+'install');
      await page.evaluate(()=>navigator.serviceWorker.ready);
      await expect.poll(()=>page.evaluate(()=>Boolean(navigator.serviceWorker.controller))).toBe(true);
      await page.close();reopened=await context.newPage();
      const started=Date.now();const response=await reopened.goto(f.url,{waitUntil:'domcontentloaded'});
      expect(response.fromServiceWorker()).toBe(true);
      expect(response.headers()['x-sentinel-panel-status']).toBe('CONNECTING');
      await expect(reopened.locator('#launch-status')).toBeVisible();
      expect(Date.now()-started).toBeLessThan(2000);
      await expect.poll(()=>f.requests.length).toBe(1);
      expect(f.requests[0].navigation).toBe(false);
      await expect(reopened.locator('#operational-state')).toHaveCount(0);
      expect(await reopened.evaluate(()=>caches.keys())).toEqual([]);
      await testInfo.attach('controlled-reopen-before-status',{body:await reopened.screenshot(),contentType:'image/png'});
      f.release();await expect(reopened.locator('.brand')).toBeVisible();
    } finally {if(reopened)await reopened.goto('about:blank');await f.close();}
  });
  test('offline reopening paints a neutral document and stores no financial snapshot',async({context,page,request})=>{
    const f=await fixture(request,{workerOnly:true});
    try {
      await page.goto(f.url+'install');await page.evaluate(()=>navigator.serviceWorker.ready);
      await expect.poll(()=>page.evaluate(()=>Boolean(navigator.serviceWorker.controller))).toBe(true);
      await context.setOffline(true);await page.goto(f.url,{waitUntil:'domcontentloaded'});
      await expect(page.locator('#launch-status')).toContainText('OFFLINE');
      await expect(page.locator('#operational-state')).toHaveCount(0);
      expect(await page.evaluate(()=>caches.keys())).toEqual([]);
      expect(f.requests).toHaveLength(0);
    } finally {await context.setOffline(false);await page.goto('about:blank');await f.close();}
  });
});
