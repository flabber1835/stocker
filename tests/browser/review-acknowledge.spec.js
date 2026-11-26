'use strict';
const {test,expect}=require('@playwright/test');
const fs=require('node:fs');
const {panelAssets}=require('./panel-assets.cjs');

test.use({serviceWorkers:'block'});

test('keyboard review of older entries leaves the dashboard and its baseline available', async({page,context,request})=>{
  const documents=JSON.parse(fs.readFileSync(process.env.SENTINEL_DOM_FIXTURE,'utf8')).history_documents;
  const assets=await panelAssets(request,documents.dashboard,documents.first);
  const writes=[];
  await page.clock.install({time:new Date(documents.dashboard.match(/data-generated-at="([^"]+)"/)[1])});
  await context.route('**/*', async route=>{
    const req=route.request();
    const url=new URL(req.url());
    if(req.method()!=='GET')writes.push(req.method());
    if(assets.has(url.pathname))return route.fulfill({status:200,...assets.get(url.pathname)});
    if(url.pathname==='/')return route.fulfill({contentType:'text/html',body:documents.dashboard});
    if(url.pathname==='/review/history' && url.searchParams.get('head')==='22'
        && url.searchParams.get('reviewed_head')==='1' && url.searchParams.get('scope')==='a'.repeat(64)){
      const body={22:documents.first,2:documents.last}[url.searchParams.get('first')];
      if(body)return route.fulfill({contentType:'text/html',body});
    }
    return route.fulfill({status:404,body:''});
  });
  await page.goto('http://127.0.0.1:18947/');
  await page.locator('#system-details > summary').click();
  const all=page.getByRole('link',{name:/Review all 21 entries/});
  await all.focus();
  const newTab=page.waitForEvent('popup');
  await page.keyboard.press('Enter');
  const history=await newTab;
  await expect(history.getByRole('heading',{name:'Health history'})).toBeVisible();
  await expect(history.locator('li')).toHaveCount(20);
  await history.getByRole('link',{name:'Older entries'}).click();
  await expect(history.locator('li')).toHaveCount(1);
  await expect(history.locator('li')).toContainText('Opening verifier failure');
  await expect(history.getByRole('link',{name:'Older entries'})).toHaveCount(0);
  await history.getByRole('link',{name:'Newer entries'}).click();
  await expect(history.locator('li')).toHaveCount(20);
  await history.close();
  await expect(page.locator('#review-acknowledge')).toBeEnabled();
  expect(writes).toEqual([]);
});

test('mobile review names each recovered incident and explains what acknowledgment covers',async({page,request})=>{
  const document=JSON.parse(fs.readFileSync(process.env.SENTINEL_DOM_FIXTURE,'utf8')).mobile_history;
  const assets=await panelAssets(request,document);
  await page.clock.install({time:new Date(document.match(/data-generated-at="([^"]+)"/)[1])});
  const writes=[];
  await page.route('**/*',async route=>{
    const req=route.request();
    const path=new URL(req.url()).pathname;
    if(req.method()!=='GET')writes.push(req.method());
    if(assets.has(path))return route.fulfill({status:200,...assets.get(path)});
    if(path==='/')return route.fulfill({contentType:'text/html',body:document});
    return route.fulfill({status:404,body:''});
  });
  await page.goto('http://127.0.0.1:18947/');
  const review=page.locator('#operator-review');
  await expect(review).toBeHidden();
  await page.locator('#system-details > summary').click();
  const incidents=review.locator('.review-incident');
  await expect(incidents).toHaveCount(2);
  for(const article of await incidents.all()) {
    await expect(article.getByRole('heading',{name:'Notification delivery'})).toBeVisible();
    await expect(article).toContainText('Recovery recorded');
    await expect(article).toContainText('Pacific');
  }
  await expect(review.locator('.review-decision')).toHaveText(
    'Current checks are clear. Acknowledge after reviewing the outstanding history.');
  await expect(review).toContainText('records your review of all 5 outstanding entries');
  await expect(review.getByRole('button',{name:'Acknowledge reviewed history'})).toBeVisible();
  await expect(review.locator('[data-detail-key="review-history"]')).not.toHaveAttribute('open','');
  await review.getByText('Recorded evidence (5 recorded entries)',{exact:true}).click();
  await expect(review.locator('[data-detail-key="review-history"] li')).toHaveCount(5);
  expect(await review.evaluate(node=>node.scrollWidth<=node.clientWidth+1)).toBe(true);
  expect(writes).toEqual([]);
});

for(const outcome of ['accepted','refused']) {
  test(`review action introduced by refresh is keyboard accessible and ${outcome}`,async({page,request})=>{
    const documents=JSON.parse(fs.readFileSync(process.env.SENTINEL_DOM_FIXTURE,'utf8')).review_documents;
    const assets=await panelAssets(request,documents.initial,documents.ready,documents.done);
    const now=Date.parse(documents.initial.match(/data-generated-at="([^"]+)"/)[1]);
    const posted=[];
    let navigations=0;
    await page.clock.install({time:new Date(now)});
    await page.route('**/*',async route=>{
      const request=route.request();
      const path=new URL(request.url()).pathname;
      if(assets.has(path))return route.fulfill({status:200,...assets.get(path)});
      if(path==='/review/acknowledge') {
        posted.push({method:request.method(),body:request.postDataJSON(),
          origin:request.headers().origin});
        return route.fulfill({status:outcome==='accepted'?200:409,
          contentType:'application/json',body:outcome==='accepted'?
            JSON.stringify({status:'CLEAN',head:3,reviewed_head:3}):
            JSON.stringify({detail:'State changed; review again'})});
      }
      if(path!=='/')return route.fulfill({status:404,body:''});
      const navigation=request.isNavigationRequest();
      if(navigation)navigations++;
      const body=navigation?(navigations===1?documents.initial:documents.done):documents.ready;
      await route.fulfill({status:200,contentType:'text/html',body,
        headers:{'X-Sentinel-Panel-Status':'CURRENT',
          'X-Sentinel-Server-Time':String(Date.parse(body.match(/data-generated-at="([^"]+)"/)[1]))}});
    });
    await page.goto('http://127.0.0.1:18947/');
    const review=page.locator('#operator-review');
    const systemDetails=page.locator('#system-details');
    await expect(systemDetails.locator('#operator-review')).toHaveCount(1);
    await expect(review).toBeHidden();
    await systemDetails.locator(':scope > summary').focus();
    await page.keyboard.press('Enter');
    await expect(review).toBeVisible();
    await expect(review.locator('h2')).toHaveText('Health history');
    await expect(review.locator('a[href="#system-details"]')).toBeVisible();
    await expect(page.locator('#review-acknowledge')).toHaveCount(0);
    await expect(page.locator('body')).toHaveAttribute('data-health','amber');
    await page.clock.runFor(5000);
    const button=page.getByRole('button',{name:'Acknowledge reviewed history'});
    await expect(button).toBeVisible();
    await expect(review).toContainText('PAPER results have a separate verification check.');
    expect(posted).toHaveLength(0);
    await button.focus();
    await page.keyboard.press('Enter');
    await expect.poll(()=>posted.length).toBe(1);
    expect(posted[0]).toEqual({method:'POST',
      body:{token:'browser-qualified-review-view'},origin:'http://127.0.0.1:18947'});
    if(outcome==='accepted') {
      await expect.poll(()=>navigations).toBe(2);
      await expect(page.locator('body')).toHaveAttribute('data-health','green');
      await expect(page.locator('#review-acknowledge')).toHaveCount(0);
      await expect(review).toBeHidden();
      await systemDetails.locator(':scope > summary').click();
      await expect(review).toContainText('Expected operation');
    } else {
      await expect(button).toBeDisabled();
      await expect(review.locator('#review-result')).toContainText('Refresh and review again.');
      await expect(page.locator('body')).toHaveAttribute('data-health','amber');
      expect(navigations).toBe(1);
      await page.keyboard.press('Enter');
      expect(posted).toHaveLength(1);
    }
  });
}
