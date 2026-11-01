const { test, expect } = require("@playwright/test");

test.describe('Banner resource recovery', () => {
  // Image-resource behavior is independent of push/navigation worker behavior.
  // Use real PNG decoding and document replacement in each desktop engine;
  // this does not claim an actual iOS Home Screen acceptance result.
  test.use({serviceWorkers:'block'});

  const assetPath='/static/caesars-palace-512.png';
  const assetSha256='87d7efa50b7335de0f82614456c18baa81299c1fe7c62c7b8ab9670e46b0d31f';

  async function bannerFixture(page,{failures=0,hold=false}={}) {
    const http=require('node:http');
    const crypto=require('node:crypto');
    const documentResponse=await page.request.get('/');
    expect(documentResponse.status()).toBe(200);
    const html=await documentResponse.text();
    const imageResponse=await page.request.get(assetPath);
    expect(imageResponse.status()).toBe(200);
    const png=await imageResponse.body();
    expect(crypto.createHash('sha256').update(png).digest('hex')).toBe(assetSha256);
    expect([png.readUInt32BE(16),png.readUInt32BE(20)]).toEqual([512,512]);
    const requests=[],pending=new Set(),sockets=new Set(),timers=new Set();
    let held=hold;
    function image(response,body) {
      if (response.destroyed) return;
      response.writeHead(200,{'Content-Type':'image/png','Cache-Control':'no-store',
        'Content-Length':body.length});
      response.end(body);
    }
    const server=http.createServer((request,response)=>{
      const url=new URL(request.url,'http://127.0.0.1');
      if (url.pathname===assetPath) {
        requests.push({path:url.pathname,query:url.search,url:request.url});
        if (held) {
          pending.add(response);
          response.once('close',()=>pending.delete(response));
          return;
        }
        if (requests.length<=failures) {
          // Match the causal transport failure: promise the full image, send
          // its first 1,024 real bytes, then interrupt that owned response.
          response.writeHead(200,{'Content-Type':'image/png','Cache-Control':'no-store',
            'Content-Length':png.length});
          response.write(png.subarray(0,1024));
          const timer=setTimeout(()=>{timers.delete(timer);response.destroy();},50);
          timers.add(timer);
          response.once('close',()=>{clearTimeout(timer);timers.delete(timer);});
        } else image(response,png);
      } else if (url.pathname==='/') {
        response.writeHead(200,{'Content-Type':'text/html; charset=utf-8',
          'Cache-Control':'no-store','X-Sentinel-Panel-Status':'CURRENT'});
        // Retain every original financial field, verdict and evidence clock.
        response.end(html);
      } else {
        response.writeHead(404,{'Content-Type':'text/plain','Cache-Control':'no-store'});
        response.end('Not part of the owned banner fixture');
      }
    });
    server.on('connection',socket=>{sockets.add(socket);socket.once('close',()=>sockets.delete(socket));});
    await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
    const url=`http://127.0.0.1:${server.address().port}/`;
    return {html,url,requests,
      async open(){await page.goto(url,{waitUntil:'domcontentloaded'});},
      async replace(){await page.evaluate(body=>{document.open();document.write(body);document.close();},html);},
      release(){held=false;for (const response of pending) image(response,png);pending.clear();},
      async close(){
        await page.goto('about:blank',{waitUntil:'commit',timeout:5000}).catch(()=>undefined);
        for (const timer of timers) clearTimeout(timer);
        timers.clear();
        for (const response of pending) response.destroy();
        const stopped=new Promise((resolve,reject)=>server.close(error=>error ? reject(error) : resolve()));
        for (const socket of sockets) socket.destroy();
        await stopped;
      }
    };
  }

  async function decodedBanner(page) {
    await expect.poll(()=>page.locator('.brand img[data-banner-src]').evaluate(image=>({
      complete:image.complete,width:image.naturalWidth,height:image.naturalHeight,
      hidden:image.hidden
    }))).toEqual({complete:true,width:512,height:512,hidden:false});
    await expect(page.locator('.brand img[data-banner-src]')).toBeVisible();
    await expect(page.locator('.brand-fallback')).toBeHidden();
  }

  async function paintedFrames(page) {
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  }

  test('healthy existing PNG keeps its original resource identity',async ({page})=>{
    const fixture=await bannerFixture(page);
    try {
      await fixture.open();await decodedBanner(page);
      expect(fixture.requests).toHaveLength(1);
      expect(fixture.requests[0].query).toBe('');
      expect(await page.locator('.brand img[data-banner-src]').getAttribute('src')).toBe(assetPath);
    } finally {await fixture.close();}
  });

  test('JavaScript-disabled page displays only the original noscript PNG',async ({browser,baseURL})=>{
    const context=await browser.newContext({baseURL,javaScriptEnabled:false,
      serviceWorkers:'block',viewport:{width:393,height:852}});
    const page=await context.newPage();
    let fixture;
    try {
      fixture=await bannerFixture(page);await fixture.open();
      const original=page.locator('.brand noscript img');
      await expect.poll(()=>original.evaluate(image=>({complete:image.complete,
        width:image.naturalWidth,height:image.naturalHeight})))
        .toEqual({complete:true,width:512,height:512});
      await expect(original).toBeVisible();
      await expect(page.locator('.brand img[data-banner-src]')).toBeHidden();
      await expect(page.locator('.brand-fallback')).toBeHidden();
      await expect(page.locator('.brand img:visible')).toHaveCount(1);
      const box=await page.locator('.brand').boundingBox(),image=await original.boundingBox();
      expect(box.height).toBeLessThanOrEqual(image.height+2);
      expect(fixture.requests).toHaveLength(1);
      expect(fixture.requests[0].url).toBe(assetPath);
    } finally {
      if (fixture) await fixture.close();
      await context.close();
    }
  });

  test('truncated HTTP200 resets only the failed resource identity once',async ({page},testInfo)=>{
    const fixture=await bannerFixture(page,{failures:1});
    try {
      await fixture.open();await decodedBanner(page);
      expect(fixture.requests).toHaveLength(2);
      expect(fixture.requests[0].url).toBe(assetPath);
      expect(fixture.requests[1].path).toBe(assetPath);
      expect(fixture.requests[1].query).not.toBe('');
      const current=await page.locator('.brand img[data-banner-src]').getAttribute('src');
      expect(new URL(current,fixture.url).pathname+new URL(current,fixture.url).search).toBe(fixture.requests[1].url);
      await testInfo.attach('recovered-real-png',{body:await page.locator('.brand').screenshot(),contentType:'image/png'});
    } finally {await fixture.close();}
  });

  test('two failed identities show compact fallback without a replacement loop',async ({page})=>{
    const fixture=await bannerFixture(page,{failures:Infinity});
    try {
      await fixture.open();
      for (let replacement=0;replacement<3;replacement++) {
        await expect(page.locator('.brand-fallback')).toBeVisible();
        await expect(page.locator('.brand-fallback')).toContainText("Caesar's Palace");
        await expect(page.locator('.brand img[data-banner-src]')).toBeHidden();
        await paintedFrames(page);
        expect((await page.locator('.brand').boundingBox()).height).toBeLessThan(100);
        expect(fixture.requests).toHaveLength(2);
        if (replacement<2) await fixture.replace();
      }
    } finally {await fixture.close();}
  });

  test('pending valid resource is not mistaken for a failed decoder',async ({page})=>{
    const fixture=await bannerFixture(page,{hold:true});
    try {
      await fixture.open();
      await expect.poll(()=>fixture.requests.length).toBeGreaterThan(0);
      for (let replacement=0;replacement<2;replacement++) {
        expect(await page.locator('.brand img[data-banner-src]').evaluate(image=>image.complete)).toBe(false);
        await expect(page.locator('.brand-fallback')).toBeHidden();
        await paintedFrames(page);
        expect(fixture.requests.every(request=>request.query==='')).toBe(true);
        await fixture.replace();
      }
      fixture.release();await decodedBanner(page);
      expect(fixture.requests.every(request=>request.query==='')).toBe(true);
    } finally {await fixture.close();}
  });

  test('recovered healthy resource survives ordinary document replacements',async ({page})=>{
    const fixture=await bannerFixture(page,{failures:1});
    try {
      await fixture.open();await decodedBanner(page);
      const recovered=await page.locator('.brand img[data-banner-src]').getAttribute('src');
      expect(fixture.requests).toHaveLength(2);
      for (let replacement=0;replacement<2;replacement++) {
        await fixture.replace();await decodedBanner(page);await paintedFrames(page);
        expect(await page.locator('.brand img[data-banner-src]').getAttribute('src')).toBe(recovered);
        expect(fixture.requests).toHaveLength(2);
      }
    } finally {await fixture.close();}
  });
});

async function openSystemDetails(page) {
  const details = page.locator("#system-details");
  await expect(details).not.toHaveAttribute("open", "");
  await expect(page.locator("#operational-state")).toBeVisible();
  await details.locator(":scope > summary").click();
  await expect(details).toHaveAttribute("open", "");
}

async function waitForActiveWorker(page, observe) {
  await expect.poll(async () => {
    const snapshot = await page.evaluate(async () => {
      const registration = await navigator.serviceWorker.getRegistration();
      return {
        activated: registration?.active?.state === "activated",
        controlsPage: Boolean(registration?.active &&
          navigator.serviceWorker.controller === registration.active)
      };
    });
    observe?.(snapshot);
    return snapshot;
  }).toEqual({ activated: true, controlsPage: true });
}

const REQUIRED_AUTOMATION_STEPS = [
  "automation_step_discovery",
  "automation_step_data",
  "automation_step_prepare",
  "automation_step_open",
  "automation_step_transport",
  "automation_step_reconcile",
  "automation_step_complete"
];

test.describe('App resume presentation', () => {
  // Hold the foreground HTML read deterministically. Worker delivery and
  // offline navigation are qualified separately by the PWA tests below.
  test.use({serviceWorkers:'block'});

  async function shortProofDisplay(page) {
    // Change only the client presentation, exactly as the resume fixture below:
    // CI's real financial rows remain unconfigured/negative. Nine seconds is
    // the observed presentation budget, not a fabricated financial receipt.
    const response = await page.request.get('/');
    const source = await response.text();
    const duePattern = /var ordinaryDue = Date\.now\(\) \+ \d+;/g;
    const refreshPattern = /refreshTimer = setTimeout\(function\(\)\{ checkAge\(\); refreshDocument\(\); \}, \d+\);/g;
    expect([...source.matchAll(duePattern)]).toHaveLength(1);
    expect([...source.matchAll(refreshPattern)]).toHaveLength(1);
    const base = new Date('2026-10-30T23:00:00Z');
    const requests = [];
    let closing = false;
    await page.clock.install({time:base});
    await page.clock.pauseAt(new Date(base.getTime() + 60000));
    const initialNow = await page.evaluate(() => Date.now());

    function documentAt(now, positive) {
      let body = source.replace(/data-generated-at="[^"]+"/,
        `data-generated-at="${new Date(now).toISOString()}"`)
        .replace(/data-max-age-seconds="[^"]+"/, 'data-max-age-seconds="9"')
        .replace(/data-refresh-pending="[^"]+"/, 'data-refresh-pending="false"')
        .replace(duePattern, 'var ordinaryDue = Date.now() + 5000;')
        .replace(refreshPattern,
          'refreshTimer = setTimeout(function(){ checkAge(); refreshDocument(); }, 5000);');
      if (positive) body = body.replace(
        /(<span id="operational-state" class=")state [^"]+("[^>]*>)[\s\S]*?(<\/span>)/,
        '$1state ok$2CLIENT PRESENTATION FIXTURE$3');
      expect(body).toContain('data-max-age-seconds="9"');
      expect(body).toContain('var ordinaryDue = Date.now() + 5000;');
      expect(body).toContain('refreshDocument(); }, 5000);');
      return body;
    }

    await page.route('**/', async route => {
      if (closing) {
        await route.abort('aborted').catch(() => undefined);
        return;
      }
      if (route.request().isNavigationRequest()) {
        await route.fulfill({status:200, headers:{'Content-Type':'text/html',
          'Cache-Control':'no-store', 'X-Sentinel-Panel-Status':'CURRENT'},
          body:documentAt(initialNow, true)});
        return;
      }
      let decide, complete;
      const choice = new Promise(resolve => { decide = resolve; });
      const done = new Promise(resolve => { complete = resolve; });
      const request = {decide, done, allowAbort:false};
      requests.push(request);
      try {
        const kind = await choice;
        if (kind === 'abort') {
          await route.abort('aborted');
        } else {
          const now = await page.evaluate(() => Date.now());
          await route.fulfill({status:200, headers:{'Content-Type':'text/html',
            'Cache-Control':'no-store', 'X-Sentinel-Panel-Status':'CURRENT'},
            body:documentAt(now, kind !== 'negative')});
        }
      } catch (error) {
        if (!request.allowAbort) throw error;
      } finally { complete(); }
    });
    await page.goto('/', {waitUntil:'domcontentloaded'});
    await expect(page.locator('#operational-state')).toHaveClass('state ok');
    return {
      requests,
      async release(index, kind = 'positive') {
        requests[index].decide(kind);
        await requests[index].done;
      },
      async close() {
        closing = true;
        for (const request of requests) {
          request.allowAbort = true;
          request.decide('abort');
        }
        await Promise.all(requests.map(request => request.done));
      }
    };
  }

  test('short original proof stays last-known amber during two healthy foreground refreshes', async ({page}) => {
    const fixture = await shortProofDisplay(page);
    try {
      for (let cycle = 0; cycle < 2; cycle++) {
        const original = await page.locator('body').getAttribute('data-generated-at');
        await page.evaluate(() => {
          window.__pendingHeadlineStates = [];
          const badge = document.getElementById('operational-state');
          new MutationObserver(() => window.__pendingHeadlineStates.push(badge.className))
            .observe(badge, {attributes:true, attributeFilter:['class']});
        });
        await page.clock.runFor(5000);
        await expect.poll(() => fixture.requests.length).toBe(cycle + 1);
        await page.clock.runFor(5001); // First one-second age check after the 9s proof expires.
        await expect(page.locator('#operational-state')).toHaveClass('state warn');
        await expect(page.locator('#operational-state')).toContainText('LAST KNOWN');
        expect(await page.locator('body').getAttribute('data-generated-at')).toBe(original);
        await page.clock.runFor(1399); // Five seconds idle plus 6.4 seconds fetching.
        await expect(page.locator('#operational-state')).toHaveClass('state warn');
        expect(await page.evaluate(() => window.__pendingHeadlineStates)).not.toContain('state fail');
        await fixture.release(cycle);
        await expect(page.locator('#operational-state')).toHaveText('CLIENT PRESENTATION FIXTURE');
        expect(await page.locator('body').getAttribute('data-generated-at')).not.toBe(original);
      }
    } finally { await fixture.close(); }
  });

  test('ordinary refresh expiry is anchored to the first request despite lifecycle wakeups', async ({page}) => {
    const fixture = await shortProofDisplay(page);
    try {
      const original = await page.locator('body').getAttribute('data-generated-at');
      await page.clock.runFor(5000);
      await expect.poll(() => fixture.requests.length).toBe(1);
      fixture.requests[0].allowAbort = true;
      await page.clock.runFor(5001);
      await expect(page.locator('#operational-state')).toHaveClass('state warn');
      await page.evaluate(() => {
        window.dispatchEvent(new Event('focus'));
        window.dispatchEvent(new PageTransitionEvent('pageshow', {persisted:false}));
      });
      await page.clock.runFor(9998);
      await expect(page.locator('#operational-state')).toHaveClass('state warn');
      await page.evaluate(() => window.dispatchEvent(new PageTransitionEvent('pageshow', {persisted:true})));
      await page.clock.runFor(2);
      await expect(page.locator('#operational-state')).toHaveClass('state fail');
      await expect(page.locator('#operational-state')).toContainText('STATUS NOT CURRENT');
      expect(fixture.requests).toHaveLength(1);
      expect(await page.locator('body').getAttribute('data-generated-at')).toBe(original);
    } finally { await fixture.close(); }
  });

  test('a fresh backend failure cannot borrow the foreground refresh allowance', async ({page}) => {
    const fixture = await shortProofDisplay(page);
    try {
      await page.clock.runFor(5000);
      await expect.poll(() => fixture.requests.length).toBe(1);
      await page.clock.runFor(6400);
      await expect(page.locator('#operational-state')).toHaveClass('state warn');
      await fixture.release(0, 'negative');
      await expect(page.locator('#operational-state')).toHaveClass('state fail');
      await page.evaluate(() => window.dispatchEvent(new Event('focus')));
      await expect(page.locator('#operational-state')).toHaveClass('state fail');
    } finally { await fixture.close(); }
  });

  test('an iOS background timeout permits one finite foreground read without renewing clocks', async ({page}) => {
    const fixture = await shortProofDisplay(page);
    try {
      const original = await page.locator('body').getAttribute('data-generated-at');
      await page.clock.runFor(5000);
      await expect.poll(() => fixture.requests.length).toBe(1);
      fixture.requests[0].allowAbort = true;
      await page.evaluate(() => {
        Object.defineProperty(document, 'visibilityState', {configurable:true, get:()=> 'hidden'});
        document.dispatchEvent(new Event('visibilitychange'));
        window.dispatchEvent(new PageTransitionEvent('pagehide', {persisted:true}));
      });
      await page.clock.runFor(120000);
      await fixture.release(0, 'abort');
      expect(fixture.requests).toHaveLength(1);
      await page.evaluate(() => {
        Object.defineProperty(document, 'visibilityState', {configurable:true, get:()=> 'visible'});
        document.dispatchEvent(new Event('visibilitychange'));
        window.dispatchEvent(new Event('focus'));
        window.dispatchEvent(new PageTransitionEvent('pageshow', {persisted:false}));
      });
      await expect.poll(() => fixture.requests.length).toBe(2);
      fixture.requests[1].allowAbort = true;
      await expect(page.locator('#operational-state')).toHaveClass('state warn');
      expect(await page.locator('body').getAttribute('data-generated-at')).toBe(original);
      await page.clock.runFor(14999);
      await page.evaluate(() => {
        window.dispatchEvent(new Event('focus'));
        window.dispatchEvent(new PageTransitionEvent('pageshow', {persisted:true}));
      });
      expect(fixture.requests).toHaveLength(2);
      await page.clock.runFor(2);
      await expect(page.locator('#operational-state')).toHaveClass('state fail');
      expect(await page.locator('body').getAttribute('data-generated-at')).toBe(original);
    } finally { await fixture.close(); }
  });

  for (const expires of [false, true]) {
    test(`a saved positive view is amber during reconnect${expires ? ' and red on timeout' : ''}`, async ({ page }) => {
      // CI's unconfigured server is deliberately red. Only this client-display
      // fixture supplies a positive headline; it is not financial evidence.
      let release;
      const held = new Promise(resolve => { release = resolve; });
      await page.route('**/', async route => {
        if (!route.request().isNavigationRequest()) await held;
        try {
          const response = await route.fetch();
          const source = await response.text();
          const body = source.replace(
            /(<span id="operational-state" class=")state [^"]+("[^>]*>)[\s\S]*?(<\/span>)/,
            '$1state ok$2CLIENT PRESENTATION FIXTURE$3');
          expect(body).not.toBe(source);
          expect(body).toContain('CLIENT PRESENTATION FIXTURE');
          await route.fulfill({response,body});
        } catch (error) {
          if (!expires) throw error; // The expected timeout can abort this request.
        }
      });
      try {
        await page.clock.install();
        await page.goto('/', {waitUntil:'domcontentloaded'});
        await openSystemDetails(page);
        await page.locator('[data-detail-key="mode-guide"] summary').click();
        const generated = await page.locator('body').getAttribute('data-generated-at');
        await page.evaluate(() => {
          window.__resumeRealNow = Date.now;
          const clock = Date.now() + 120000;
          Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'hidden'});
          document.dispatchEvent(new Event('visibilitychange'));
          Date.now = () => clock;
          Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'visible'});
          document.dispatchEvent(new Event('visibilitychange'));
          window.dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true}));
        });
        await expect(page.locator('#operational-state')).toHaveClass('state warn');
        await expect(page.locator('#operational-state')).toContainText('REFRESHING STATUS');
        await expect(page.locator('html')).toHaveClass('refreshing-status');
        expect(await page.locator('body').getAttribute('data-generated-at')).toBe(generated);
        if (expires) {
          await page.clock.runFor(15001);
          await expect(page.locator('#operational-state')).toHaveClass('state fail');
          await expect(page.locator('#operational-state')).toContainText('STATUS NOT CURRENT');
        } else {
          await page.evaluate(() => { Date.now = window.__resumeRealNow; });
          release();
          await expect(page.locator('#operational-state')).toContainText('CLIENT PRESENTATION FIXTURE');
          await expect(page.locator('html')).not.toHaveClass('refreshing-status');
        }
        await expect(page.locator('#system-details')).toHaveAttribute('open','');
        await expect(page.locator('[data-detail-key="mode-guide"]')).toHaveAttribute('open','');
      } finally { release(); }
    });
  }
});

test.describe("Caesar's Palace on iPhone WebKit", () => {
  test.skip(({ browserName }) => browserName !== "webkit");

  for (const appearance of ["light", "dark"]) {
    for (const viewport of [
      { name: "portrait", width: 393, height: 852 },
      { name: "landscape", width: 852, height: 393 }
    ]) {
      test(`${viewport.name} ${appearance} opens every status from the compact view`, async ({ page }) => {
        await page.setViewportSize(viewport);
        await page.emulateMedia({ colorScheme: appearance });
        await page.goto("/", { waitUntil: "domcontentloaded" });

        await expect(page.locator("#operational-state")).toBeVisible();
        await expect(page.locator("#dashboard-heartbeat")).toContainText(
          "DASHBOARD HEARTBEAT");
        await expect(page.locator('[data-key="automation_step_discovery"]')).toBeHidden();
        await openSystemDetails(page);
        for (const key of REQUIRED_AUTOMATION_STEPS) {
          await expect(page.locator(`[data-key="${key}"]`)).toBeVisible();
        }
        for (const key of ["alpaca_account", "backup_restore", "runtime_identity"]) {
          await expect(page.locator(`[data-key="${key}"]`)).toBeVisible();
        }

        const layout = await page.evaluate(() => {
          const body = getComputedStyle(document.body);
          return {
            viewport: window.innerWidth,
            documentWidth: document.documentElement.scrollWidth,
            paddingLeft: Number.parseFloat(body.paddingLeft),
            paddingRight: Number.parseFloat(body.paddingRight)
          };
        });
        expect(layout.documentWidth).toBeLessThanOrEqual(layout.viewport + 1);
        expect(layout.paddingLeft).toBeGreaterThan(0);
        expect(layout.paddingRight).toBeGreaterThan(0);
        await page.locator("#system-details > summary").click();
        await expect(page.locator("#system-details")).not.toHaveAttribute("open", "");
        await expect(page.locator('[data-key="automation_step_discovery"]')).toBeHidden();
        await expect(page.locator("#operational-state")).toBeVisible();
      });
    }
  }

  test("dynamic text, long errors, and wide detail tables stay contained", async ({ page }) => {
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await openSystemDetails(page);
    await page.addStyleTag({ content: "body{font-size:24px!important}" });
    await page.locator(".detail").first().evaluate((node) => {
      node.textContent = "BROKER_ACCOUNT_RUNTIME_FAILURE_".repeat(80);
    });
    // Help and technical text can precede the financial table sections.
    // Require real tables and stress every section instead of depending on
    // the first disclosure or silently skipping the overflow check.
    const tableSections = page.locator("details").filter({
      has: page.locator("table")
    });
    expect(await tableSections.count()).toBeGreaterThan(0);
    for (const details of await tableSections.all()) {
      // DOM order opens ancestors before their children. Never toggle an
      // already-open ancestor closed or match a descendant's summary.
      if (await details.getAttribute("open") === null) {
        await details.locator(":scope > summary").click();
      }
      await expect(details).toHaveAttribute("open", "");
    }
    for (const table of await page.locator("table").all()) {
      await expect(table).toBeVisible();
      await table.evaluate((node) => {
        const row = node.insertRow();
        row.insertCell().textContent = "WIDE_COLUMN_".repeat(100);
      });
    }

    const sizes = await page.evaluate(() => ({
      viewport: window.innerWidth,
      documentWidth: document.documentElement.scrollWidth,
      heartbeat: document.querySelector("#dashboard-heartbeat").getBoundingClientRect(),
      finalStep: document.querySelector('[data-key="automation_step_complete"]').getBoundingClientRect()
    }));
    expect(sizes.documentWidth).toBeLessThanOrEqual(sizes.viewport + 1);
    expect(sizes.heartbeat.width).toBeGreaterThan(0);
    expect(sizes.finalStep.width).toBeGreaterThan(0);
  });

  test("offline transition immediately withdraws current status", async ({
    context,
    page
  }) => {
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await context.setOffline(true);

    await expect(page.locator("#dashboard-heartbeat")).toContainText("LOST");
    await expect(page.locator("#operational-state")).toContainText("STATUS NOT CURRENT");
    await context.setOffline(false);
  });
});

test.describe("Caesar's Palace PWA and push path", () => {
  test.skip(({ browserName }) => browserName !== "chromium");

  test("PWA readiness waits for activation and page control", async ({ context, page }) => {
    let releaseActivation;
    let gateArrived;
    let preparation;
    const gate = new Promise((resolve) => { releaseActivation = resolve; });
    const gateReached = new Promise((resolve) => { gateArrived = resolve; });
    await context.route("**/service-worker.js", async (route) => {
      const response = await route.fetch();
      const source = await response.text();
      expect(source).toContain("var names = await caches.keys();");
      await route.fulfill({
        response,
        body: source.replace("var names = await caches.keys();",
          'await fetch("/__activation_gate__"); var names = await caches.keys();')
      });
    });
    await context.route("**/__activation_gate__", async (route) => {
      gateArrived();
      await gate;
      await route.fulfill({ status: 204 });
    });
    try {
      await page.goto("/", { waitUntil: "domcontentloaded" });
      await gateReached;
      expect(await page.evaluate(async () => {
        const registration = await navigator.serviceWorker.ready;
        return { state: registration.active.state, controller: navigator.serviceWorker.controller };
      })).toEqual({ state: "activating", controller: null });
      const snapshots = [];
      let finished = false;
      preparation = waitForActiveWorker(page, (snapshot) => snapshots.push(snapshot))
        .then(() => { finished = true; });
      await expect.poll(() => snapshots.length).toBeGreaterThan(0);
      expect(snapshots[0]).toEqual({ activated: false, controlsPage: false });
      expect(finished).toBe(false);
      releaseActivation();
      await preparation;
      expect(finished).toBe(true);
    } finally {
      releaseActivation();
      await preparation?.catch(() => undefined);
    }
  });

  test("offline navigation is explicit red and never cached green", async ({
    context,
    page
  }) => {
    await page.goto("/", { waitUntil: "networkidle" });
    await waitForActiveWorker(page);
    await context.setOffline(true);

    const [response] = await Promise.all([
      page.waitForResponse((candidate) => candidate.request().isNavigationRequest() &&
        candidate.request().frame() === page.mainFrame() && candidate.fromServiceWorker()),
      page.reload({ waitUntil: "domcontentloaded" })
    ]);
    expect(response.status()).toBe(503);
    expect(response.headers()["cache-control"]).toBe("no-store");
    await expect(page.locator("body")).toContainText("OPERATIONAL RED — OFFLINE");
    await context.setOffline(false);
  });

  test("permission and PushManager subscription occur only after the explicit click", async ({
    context,
    page
  }) => {
    let enrolled = null;
    await context.grantPermissions(["notifications"]);
    await page.addInitScript(() => {
      window.__permissionRequests = 0;
      window.__subscribeRequests = 0;
      window.__fakeSubscription = null;
      Object.defineProperty(Notification, "requestPermission", {
        configurable: true,
        value: async () => {
          window.__permissionRequests += 1;
          return "granted";
        }
      });
      const manager = {
        getSubscription: async () => window.__fakeSubscription,
        subscribe: async (options) => {
          window.__subscribeRequests += 1;
          if (!options.userVisibleOnly || !(options.applicationServerKey instanceof Uint8Array)) {
            throw new Error("invalid subscription options");
          }
          window.__fakeSubscription = {
            endpoint: "https://push.example.test/device-browser",
            toJSON: () => ({
              endpoint: "https://push.example.test/device-browser",
              keys: { p256dh: "browser-key", auth: "browser-auth" }
            }),
            unsubscribe: async () => true
          };
          return window.__fakeSubscription;
        }
      };
      Object.defineProperty(ServiceWorkerRegistration.prototype, "pushManager", {
        configurable: true,
        get: () => manager
      });
    });
    await page.route("**/push/config", (route) => route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ applicationServerKey: `B${"A".repeat(86)}` })
    }));
    await page.route("**/push/subscriptions", async (route) => {
      enrolled = route.request().postDataJSON();
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({ status: "subscribed", delivery_status: "QUEUED",
          sender_available: true })
      });
    });

    await page.goto("/", { waitUntil: "networkidle" });
    await waitForActiveWorker(page);
    await expect(page.locator("#push-card")).toBeHidden();
    expect(await page.evaluate(() => window.__permissionRequests)).toBe(0);
    expect(await page.evaluate(() => window.__subscribeRequests)).toBe(0);
    await openSystemDetails(page);
    await expect(page.locator("#push-card")).toBeVisible();
    await expect(page.locator("#push-status")).toContainText("off");
    expect(await page.evaluate(() => window.__permissionRequests)).toBe(0);
    expect(await page.evaluate(() => window.__subscribeRequests)).toBe(0);

    await page.locator("#push-enable").click();

    await expect(page.locator("#push-status")).toContainText("single test notification");
    expect(await page.evaluate(() => window.__permissionRequests)).toBe(1);
    expect(await page.evaluate(() => window.__subscribeRequests)).toBe(1);
    expect(enrolled.endpoint).toBe("https://push.example.test/device-browser");
    expect(enrolled.test_id).toMatch(/^[0-9a-f-]{36}$/);
  });

  for (const outcome of ["unavailable", "accepted", "failed", "unreadable"]) {
    test(`test notification shows ${outcome} rather than assuming delivery`, async ({ context, page }) => {
      await context.grantPermissions(["notifications"]);
      await page.addInitScript(() => {
        Object.defineProperty(ServiceWorkerRegistration.prototype, "pushManager", {
          configurable: true,
          get: () => ({ getSubscription: async () => ({
            toJSON: () => ({endpoint: "https://push.example.test/current",
              keys: {p256dh: "fixture", auth: "fixture"}}),
            unsubscribe: async () => true
          }) })
        });
      });
      const alert_id = "a".repeat(64);
      let submissions = 0;
      await page.route("**/push/subscriptions", async route => {
        submissions++;
        await route.fulfill({status: 201, contentType: "application/json",
          body: JSON.stringify({alert_id, delivery_status: "QUEUED",
            sender_available: outcome !== "unavailable"})});
      });
      await page.route("**/push/tests/*", route => route.fulfill({
        status: outcome === "unreadable" ? 503 : 200, contentType: "application/json",
        body: JSON.stringify({alert_id,
          delivery_status: outcome === "accepted" ? "ACCEPTED" : outcome === "failed" ? "FAILED" : "QUEUED",
          sender_available: outcome !== "unavailable"})
      }));
      await page.goto("/", {waitUntil: "networkidle"});
      await waitForActiveWorker(page);
      expect(submissions).toBe(0);
      await openSystemDetails(page);
      expect(submissions).toBe(0);
      await page.locator("#push-enable").click();
      await expect(page.locator("#push-status")).toContainText(
        outcome === "accepted" ? "accepted by the push service"
          : outcome === "failed" ? "notification failed"
          : outcome === "unreadable" ? "status could not be read" : "sender is unavailable");
      expect(submissions).toBe(1);
      if (outcome === "unavailable") {
        await expect(page.locator("#push-status")).not.toContainText("accepted");
      }
    });
  }

  test("the registered worker receives a synthetic push and focuses Sentinel", async ({
    context,
    page
  }) => {
    const registrations = new Map();
    const cdp = await context.newCDPSession(page);
    cdp.on("ServiceWorker.workerErrorReported", (error) => {
      console.error("PWA_WORKER_ERROR", JSON.stringify(error));
    });
    cdp.on("ServiceWorker.workerRegistrationUpdated", ({ registrations: updates }) => {
      for (const registration of updates) {
        if (registration.isDeleted) {
          registrations.delete(registration.registrationId);
        } else {
          registrations.set(registration.registrationId, registration);
        }
      }
    });
    await cdp.send("ServiceWorker.enable");
    await context.grantPermissions(["notifications"]);
    await page.goto("/", { waitUntil: "networkidle" });
    await waitForActiveWorker(page);
    const worker = await page.evaluate(async () => {
      const registration = await navigator.serviceWorker.getRegistration();
      return { scope: registration.scope, origin: location.origin };
    });
    expect(worker.scope).toBe(`${worker.origin}/`);
    const actor = context.serviceWorkers().find(
      (candidate) => candidate.url() === `${worker.origin}/service-worker.js`);
    expect(actor).toBeTruthy();
    await actor.evaluate(() => {
      self.__pushEvidence = { stage: "awaiting_push", notifications: [], error: null };
      const original = self.registration.showNotification.bind(self.registration);
      self.registration.showNotification = async (title, options) => {
        self.__pushEvidence.stage = "native_delivery";
        try {
          await original(title, options);
          self.__pushEvidence.notifications =
            (await self.registration.getNotifications({ tag: options.tag })).map(
              (notification) => ({
                title: notification.title, body: notification.body,
                tag: notification.tag, data: notification.data
              }));
          self.__pushEvidence.stage = "retained_at_delivery";
        } catch (error) {
          self.__pushEvidence.stage = "native_delivery_failed";
          self.__pushEvidence.error = { name: error.name, message: error.message };
          throw error;
        }
      };
    });

    await expect.poll(() => Array.from(registrations.values()).find(
      (registration) => registration.scopeURL === worker.scope
    ) || null).not.toBeNull();
    const registration = Array.from(registrations.values()).find(
      (candidate) => candidate.scopeURL === worker.scope
    );
    const pushed = {
      alert_id: "alert-red-1",
      title: "Caesar's Palace — action required",
      body: "automation retry budget exhausted",
      tag: "alert-red-1",
      url: "/"
    };
    await cdp.send("ServiceWorker.deliverPushMessage", {
      origin: worker.origin,
      registrationId: registration.registrationId,
      data: JSON.stringify(pushed)
    });

    try {
      await expect.poll(() => actor.evaluate(() => self.__pushEvidence.notifications)).toEqual([{
        title: pushed.title,
        body: pushed.body,
        tag: pushed.tag,
        data: { url: "/", alert_id: pushed.alert_id }
      }]);
    } catch (error) {
      console.error("PWA_PUSH_FAILURE", JSON.stringify(
        await actor.evaluate(() => self.__pushEvidence)));
      throw error;
    }

    const result = await page.evaluate(async () => {
      const source = await fetch("/service-worker.js", { cache: "no-store" }).then((r) => r.text());
      const handlers = {};
      const notifications = [];
      const actions = [];
      const client = {
        url: `${location.origin}/before`,
        navigate: async function(url) {
          actions.push(["navigate", url]);
          this.url = url;
          return this;
        },
        focus: async function() {
          actions.push(["focus", this.url]);
          return this;
        }
      };
      const worker = {
        location: { origin: location.origin },
        registration: {
          showNotification: async (title, options) => {
            notifications.push({ title, options });
          }
        },
        clients: {
          claim: async () => undefined,
          matchAll: async () => [client],
          openWindow: async (url) => actions.push(["open", url])
        },
        skipWaiting: async () => undefined,
        addEventListener: (name, handler) => { handlers[name] = handler; }
      };
      const fakeCaches = { keys: async () => [], delete: async () => true };
      new Function("self", "caches", "fetch", "Response", "URL", source)(
        worker, fakeCaches, fetch, Response, URL);

      let pushWork;
      handlers.push({
        data: { json: () => ({
          alert_id: "alert-click-1",
          title: "Caesar's Palace — action required",
          body: "automation retry budget exhausted",
          tag: "alert-click-1",
          url: "/"
        }) },
        waitUntil: (promise) => { pushWork = promise; }
      });
      await pushWork;

      let clickWork;
      handlers.notificationclick({
        notification: {
          data: notifications[0].options.data,
          close: () => actions.push(["close"])
        },
        waitUntil: (promise) => { clickWork = promise; }
      });
      await clickWork;
      return { notifications, actions };
    });

    expect(result.notifications).toHaveLength(1);
    expect(result.notifications[0].title).toContain("action required");
    expect(result.notifications[0].options.tag).toBe("alert-click-1");
    expect(result.actions[0]).toEqual(["close"]);
    expect(result.actions.some(([action]) => action === "navigate")).toBe(true);
    expect(result.actions.some(([action]) => action === "focus")).toBe(true);
    expect(result.actions.some(([action]) => action === "open")).toBe(false);
    await cdp.detach();
  });
});
