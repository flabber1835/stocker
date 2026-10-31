'use strict';

const crypto = require('node:crypto');
const path = require('node:path');
const {performance} = require('node:perf_hooks');

const SCHEMA = 'sentinel.dashboard-journey/1';
const TARGETS = {launch_ms:3000, content_after_response_ms:1000};
function plain(value) {
  return String(value || '').replace(/<[^>]*>/g, '').replace(/&amp;/g, '&')
    .replace(/&quot;/g, '"').replace(/&#x27;|&#39;/g, "'").replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>').trim().slice(0, 300);
}
function serverDocument(body) {
  const field = name => body.match(new RegExp(`${name}="([^"]*)"`))?.[1] ?? null;
  const badge = body.match(/<span id="operational-state" class="([^"]+)"[^>]*>([\s\S]*?)<\/span>/);
  return {
    generated_at:field('data-generated-at'), max_age_seconds:Number(field('data-max-age-seconds')),
    refresh_pending:field('data-refresh-pending'), headline_class:badge?.[1] ?? null,
    headline_label:badge ? plain(badge[2]) : null,
    warning_ids:[...body.matchAll(/href="#status-([^"<>]+)"/g)].map(match => match[1]).slice(0, 80),
    sha256:crypto.createHash('sha256').update(body).digest('hex')
  };
}

// This function executes in the browser. It observes only; it changes no HTML,
// clocks, worker registration, request or financial state.
function installRecorder({binding}) {
  const send = value => {
    const record = {...value, browser_ms:performance.now(), document_time_origin_ms:performance.timeOrigin,wall_time_ms:Date.now()};
    try { window[binding](record).catch(() => {}); } catch (_) {}
  };
  let root = null;
  let signature = '';
  let shownGeneration = null;
  let rootNumber = 0;
  let meaningfulScheduled = null;
  function visible(element) {
    if (!element) return false;
    const box = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return box.width > 0 && box.height > 0 && box.bottom > 0 && box.top < innerHeight &&
      box.right > 0 && box.left < innerWidth && style.display !== 'none' && style.visibility !== 'hidden';
  }
  function state() {
    const badge = document.getElementById('operational-state');
    const card = document.querySelector('.next-plan') || document.querySelector('#portfolio-overview .overview-card');
    return {
      generated_at:document.body?.dataset.generatedAt || null,
      max_age_seconds:Number(document.body?.dataset.maxAgeSeconds),
      headline_class:badge?.className || null, headline_label:badge?.textContent.trim().slice(0, 300) || null,
      preparation_label:document.getElementById('preparation-stage')?.textContent.trim().slice(0, 200) || null,
      plan_readiness_label:document.getElementById('plan-readiness')?.textContent.trim().slice(0, 200) || null,
      meaningful_visible:visible(badge) && visible(card), root_number:rootNumber,
      visibility:document.visibilityState, online:navigator.onLine,
      refreshing:document.documentElement?.classList.contains('refreshing-status') || false,
      not_current:document.documentElement?.classList.contains('not-current') || false
    };
  }
  function navigation() {
    const item = performance.getEntriesByType('navigation')[0];
    if (!item) return;
    const keys = ['startTime','domainLookupStart','domainLookupEnd','connectStart','connectEnd',
      'secureConnectionStart','requestStart','responseStart','responseEnd','domContentLoadedEventEnd','loadEventEnd'];
    send({type:'navigation-timing', timing:Object.fromEntries(keys.map(key => [key, item[key]]))});
  }
  function workers() {
    const supported = 'serviceWorker' in navigator;
    send({type:'service-worker', supported, controller:!!navigator.serviceWorker?.controller,
      push_supported:'PushManager' in window, standalone:!!navigator.standalone || matchMedia('(display-mode: standalone)').matches});
    if (supported) navigator.serviceWorker.getRegistration().then(reg => send({type:'worker-registration',
      registered:!!reg, active_state:reg?.active?.state || null, controller:!!navigator.serviceWorker.controller})).catch(() => {});
  }
  function attachLifecycle() {
    for (const name of ['pageshow','pagehide','focus','online','offline']) {
      window.addEventListener(name, event => {
        send({type:'lifecycle', name, persisted:typeof event.persisted==='boolean' ? event.persisted : null,
          visibility:document.visibilityState, generated_at:document.body?.dataset.generatedAt || null});
        if (name==='pageshow') { navigation(); workers(); }
      });
    }
    document.addEventListener('visibilitychange', () => send({type:'lifecycle', name:'visibilitychange',
      visibility:document.visibilityState, generated_at:document.body?.dataset.generatedAt || null}));
    navigator.serviceWorker?.addEventListener('controllerchange', workers);
  }
  function snapshot() {
    if (root !== document.documentElement) {
      root = document.documentElement;
      if (root) { rootNumber += 1; send({type:'document-root', root_number:rootNumber}); attachLifecycle(); workers(); }
    }
    const next = state();
    const key = JSON.stringify(next);
    if (key !== signature) { signature = key; send({type:'visible-state', ...next}); }
    if (next.meaningful_visible && shownGeneration !== next.generated_at && meaningfulScheduled !== next.generated_at) {
      meaningfulScheduled = next.generated_at;
      requestAnimationFrame(() => requestAnimationFrame(() => {
        const current = state();
        meaningfulScheduled = null;
        if (current.meaningful_visible && shownGeneration !== current.generated_at) {
          shownGeneration = current.generated_at;
          send({type:'meaningful-content', method:'visible_content_after_two_animation_frames', ...current});
          navigation();
        }
      }));
    }
  }
  const observer = new MutationObserver(records => {
    const changes = records.filter(item => item.type==='attributes' && item.attributeName==='class' && item.target.id==='operational-state');
    changes.forEach((item, index) => {
      const following = changes.slice(index+1).find(other => other.target===item.target);
      send({type:'badge-transition', old_class:item.oldValue,
        headline_class:following ? following.oldValue : item.target.className,
        generated_at:item.target.closest('body')?.dataset.generatedAt || null});
    });
    snapshot();
  });
  // Observe Document itself: document.open/write replaces its descendants.
  observer.observe(document, {subtree:true,childList:true,attributes:true,attributeOldValue:true,
    attributeFilter:['class','data-generated-at','data-max-age-seconds']});
  try {
    new PerformanceObserver(list => list.getEntries().forEach(item => send({type:'paint', name:item.name,
      start_ms:item.startTime, duration_ms:item.duration}))).observe({type:'paint',buffered:true});
  } catch (_) { send({type:'paint-unavailable'}); }
  snapshot();
}

function assessCapture(report) {
  const findings = [];
  const add = (code, detail, fields={}) => findings.push({code,detail,...fields});
  if (!report.capture?.complete || report.capture.status!=='COMPLETE') add('INCOMPLETE_CAPTURE','The journey recorder did not complete.');
  if (report.capture?.event_overflow) add('EVENT_OVERFLOW','The finite event limit was exceeded.');
  const responses = report.responses || [];
  const events = report.events || [];
  const initial = responses.find(item => item.kind==='navigation');
  const content = events.find(item => item.type==='meaningful-content' && item.generated_at===initial?.document?.generated_at);
  const nav = events.find(item => item.type==='navigation-timing' &&
    item.document_time_origin_ms===content?.document_time_origin_ms && item.timing?.responseEnd>0);
  const launch = content && nav && Number.isFinite(content.browser_ms) ? content.browser_ms-nav.timing.startTime : null;
  const after = content && nav && Number.isFinite(content.browser_ms) ? content.browser_ms-nav.timing.responseEnd : null;
  const paint = events.some(item => item.type==='paint' && Number.isFinite(item.start_ms));
  if (!Number.isFinite(launch) || !Number.isFinite(after) || launch<0 || after<0 || !paint || !nav) add('MISSING_TIMING','Comparable browser navigation, paint and meaningful-content timing are all required.');
  if (Number.isFinite(launch) && launch>TARGETS.launch_ms) add('SLOW_LAUNCH','First meaningful content exceeded the launch target.',{actual_ms:launch});
  if (Number.isFinite(after) && after>TARGETS.content_after_response_ms) add('SLOW_CONTENT_AFTER_RESPONSE','Content exceeded the post-response display target.',{actual_ms:after});
  const byGeneration = new Map(responses.filter(item => item.document).map(item => [item.document.generated_at,item]));
  if (responses.length<3) add('MISSING_REFRESH_RESPONSES','One initial HTML document and two actual refresh responses are required.');
  for (const response of responses) {
    const doc = response.document;
    if (response.http_status!==200 || response.panel_status!=='CURRENT' || !doc ||
        !doc.generated_at || !Number.isFinite(doc.max_age_seconds) || doc.max_age_seconds<=0) {
      add('NON_CURRENT_SERVER_DOCUMENT','An original response did not contain complete CURRENT evidence.',{request_id:response.request_id});
    }
    if (doc && doc.headline_class!=='state ok') add('BACKEND_NOT_HEALTHY','Original server health was not green.',{request_id:response.request_id,warning_ids:doc.warning_ids});
  }
  const seen = new Set();
  if (report.capture?.reasons?.includes('OVERLAPPING_REFRESHES')) add('OVERLAPPING_REFRESHES','More than one foreground document refresh was active.');
  for (const event of events) {
    if (!['visible-state','badge-transition'].includes(event.type)) continue;
    if (event.type==='visible-state' && !event.meaningful_visible && content && event.node_ms>content.node_ms) {
      add('BLANK_CONTENT','Main dashboard content disappeared after first meaningful display.');
    }
    const source = byGeneration.get(event.generated_at);
    if (!event.headline_class) continue;
    if (!source) {
      if (!seen.has('UNATTRIBUTED_STATUS')) { seen.add('UNATTRIBUTED_STATUS'); add('UNATTRIBUTED_STATUS','A browser headline has no matching original response document.'); }
      continue;
    }
    if (source.document.headline_class==='state ok' && event.headline_class==='state warn') {
      if (!seen.has('HEALTHY_REFRESH_FLICKER')) { seen.add('HEALTHY_REFRESH_FLICKER'); add('HEALTHY_REFRESH_FLICKER','A healthy original server document became amber during the journey.',{request_id:source.request_id}); }
    }
    if (source.document.headline_class!=='state ok' && event.headline_class==='state ok') add('NEGATIVE_PRECEDENCE_LOST','Browser green masked original negative server evidence.');
    if (event.headline_class==='state ok' && Number.isFinite(event.wall_time_ms) &&
        event.wall_time_ms-Date.parse(source.document.generated_at)>source.document.max_age_seconds*1000 && !seen.has('STALE_GREEN')) {
      seen.add('STALE_GREEN'); add('STALE_GREEN','The browser displayed green after the original response proof expired.');
    }
    if (event.headline_class==='state fail' && source.document.headline_class==='state ok' && !seen.has('CLIENT_NEGATIVE_TRANSITION')) {
      seen.add('CLIENT_NEGATIVE_TRANSITION'); add('CLIENT_NEGATIVE_TRANSITION','Healthy server evidence became red; correlate lifecycle, expiry and transport events.',{request_id:source.request_id});
    }
  }
  return {status:findings.length ? 'FAIL' : 'PASS',findings,
    metrics:{launch_ms:launch,content_after_response_ms:after,
      node_request_to_content_ms:content && initial ? content.node_ms-initial.request_started_ms : null},
    targets:{...TARGETS},physical_home_screen:'NOT_RUN'};
}

async function startCapture(page, options) {
  const target = new URL(options.url);
  if (!['http:','https:'].includes(target.protocol) || target.username || target.password || target.search || target.hash) throw new Error('A plain HTTP(S) dashboard URL without secrets is required');
  const maxEvents = Math.min(options.maxEvents || 300,300);
  const maxDuration = Math.min(options.maxDurationMs || 110000,110000);
  const started = performance.now();
  const report = {schema:SCHEMA,project:options.project,target_origin:target.origin,
    capture:{status:'INCOMPLETE',complete:false,reasons:[],duration_ms:0,event_count:0,event_overflow:false,expected_html_responses:3},
    responses:[],events:[],screenshots:[],physical_home_screen:{status:'NOT_RUN',reason:'Desktop browser capture is not physical iOS evidence'}};
  const nodeTime = () => performance.now()-started;
  let closed = false, done = false, resolveDone, screenshotCount=0;
  const pending = new Set(), requests = new Map(), listeners=[];
  const completion = new Promise(resolve => { resolveDone=resolve; });
  const mark = code => { if (!report.capture.reasons.includes(code)) report.capture.reasons.push(code); };
  function finishWaiting() { if (!done) { done=true; resolveDone(); } }
  function add(event) {
    if (closed) return;
    if (report.events.length>=maxEvents) { report.capture.event_overflow=true; mark('EVENT_OVERFLOW'); finishWaiting(); return; }
    report.events.push({...event,node_ms:nodeTime()});
    if (event.type==='meaningful-content') takeScreenshot('content');
    if (event.type==='badge-transition' && event.headline_class==='state warn') takeScreenshot('amber');
    const docs = report.responses.filter(item => item.document);
    if (docs.length>=3 && report.events.some(item => item.type==='meaningful-content' && item.generated_at===docs[2].document.generated_at)) finishWaiting();
  }
  async function takeScreenshot(name) {
    if (!options.outputDir || screenshotCount>=2 || (name==='content' && screenshotCount>0)) return;
    const filename = `${++screenshotCount}-${name}.png`;
    const task = page.screenshot({path:path.join(options.outputDir,filename),fullPage:false,timeout:5000})
      .then(() => report.screenshots.push(filename)).catch(() => mark('SCREENSHOT_UNAVAILABLE'));
    pending.add(task); task.finally(() => pending.delete(task));
  }
  const binding = '__sentinelJourney'+crypto.randomBytes(8).toString('hex');
  await page.exposeBinding(binding, (source,event) => { if (source.frame===page.mainFrame()) add(event); });
  await page.addInitScript(installRecorder,{binding});
  function listen(name, callback) { page.on(name,callback); listeners.push([name,callback]); }
  const rootRequest = request => {
    const url = new URL(request.url());
    return url.origin===target.origin && url.pathname===target.pathname && request.method()==='GET';
  };
  listen('request', request => {
    const url = new URL(request.url());
    if (url.origin!==target.origin) return;
    add({type:'request',path:url.pathname,method:request.method(),resource_type:request.resourceType()});
    if (request.method()!=='GET') mark('UNEXPECTED_MUTATING_REQUEST');
    if (!rootRequest(request)) return;
    const kind = request.isNavigationRequest() ? 'navigation' : 'refresh';
    if (kind==='refresh' && [...requests.values()].some(item => item.kind==='refresh' && item.completed_ms===undefined)) mark('OVERLAPPING_REFRESHES');
    const item = {request_id:requests.size+1,kind,request_started_ms:nodeTime()};
    requests.set(request,item); report.responses.push(item);
  });
  listen('response', response => {
    const item = requests.get(response.request());
    if (!item) return;
    item.response_received_ms=nodeTime(); item.http_status=response.status();
    const task = (async () => {
      const headers=await response.allHeaders(); if (closed) return;
      item.panel_status=headers['x-sentinel-panel-status'] || null;
      item.cache_control=headers['cache-control'] || null;
      const body=await response.body(); if (closed) return; item.completed_ms=nodeTime();
      if (body.length>2*1024*1024) { mark('DOCUMENT_TOO_LARGE'); return; }
      item.document=serverDocument(body.toString('utf8'));
      add({type:'html-response',request_id:item.request_id,generated_at:item.document.generated_at});
    })().catch(() => mark('HTML_RESPONSE_UNREADABLE'));
    pending.add(task); task.finally(() => pending.delete(task));
  });
  listen('requestfinished', request => {
    const item=requests.get(request);
    if (item) { item.timing=request.timing(); item.finished_ms=nodeTime(); }
  });
  listen('requestfailed', request => {
    const item=requests.get(request);
    if (item) { item.completed_ms=nodeTime(); item.transport_failed=true; add({type:'request-failed',request_id:item.request_id}); }
  });
  listen('pageerror', () => { mark('BROWSER_SCRIPT_ERROR'); add({type:'script-error'}); });
  const timer=setTimeout(() => { mark('CAPTURE_DEADLINE'); finishWaiting(); },maxDuration);
  const controller={report,waitForCompletion:() => completion,recordFailure:mark};
  controller.finishCapture=async () => {
    if (closed) return report;
    closed=true;
    clearTimeout(timer);
    for (const [name,callback] of listeners) page.off(name,callback);
    let settledTimer;
    const settled=await Promise.race([Promise.allSettled([...pending]).then(()=>true),
      new Promise(resolve=>{settledTimer=setTimeout(()=>resolve(false),5000);})]);
    clearTimeout(settledTimer);
    if (!settled) mark('PENDING_CAPTURE_TASKS');
    const docs=report.responses.filter(item => item.document && item.document.generated_at);
    const displayed=docs.slice(0,3).every(item => report.events.some(event => event.type==='meaningful-content' && event.generated_at===item.document.generated_at));
    if (docs.length<3 || !displayed) mark('MISSING_DISPLAYED_RESPONSES');
    if (!report.events.some(event => event.type==='meaningful-content')) mark('RECORDER_UNAVAILABLE');
    if (assessCapture(report).findings.some(item=>item.code==='MISSING_TIMING')) mark('MISSING_TIMING');
    if (options.outputDir && screenshotCount<3) {
      const filename=`${++screenshotCount}-final.png`;
      try { await page.screenshot({path:path.join(options.outputDir,filename),fullPage:false,timeout:3000}); report.screenshots.push(filename); } catch (_) { mark('SCREENSHOT_UNAVAILABLE'); }
    }
    report.capture.duration_ms=nodeTime(); report.capture.event_count=report.events.length;
    report.capture.complete=report.capture.reasons.length===0;
    report.capture.status=report.capture.complete ? 'COMPLETE' : 'INCOMPLETE';
    report.acceptance=assessCapture(report);
    finishWaiting(); return report;
  };
  return controller;
}
async function finishCapture(controller) { return controller.finishCapture(); }

module.exports={SCHEMA,TARGETS,startCapture,finishCapture,assessCapture,serverDocument};
