const {test,expect}=require('@playwright/test');
const fs=require('node:fs');

test.use({serviceWorkers:'block'});
test('refresh preserves the live document, scroll, focus and details while border follows evidence',async({page})=>{
  const fixture=JSON.parse(fs.readFileSync(process.env.SENTINEL_DOM_FIXTURE,'utf8'));
  let html=fixture.green,release=null,held=false,requests=0;
  let serverNow=fixture.now;
  await page.clock.install({time:new Date(fixture.now)});
  await page.route('**/*',async route=>{
    if(new URL(route.request().url()).pathname.startsWith('/static/'))return route.fulfill({status:200,contentType:'image/png',body:Buffer.from(fixture.png,'base64')});
    if(new URL(route.request().url()).pathname!=='/')return route.fulfill({status:404,body:''});
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
