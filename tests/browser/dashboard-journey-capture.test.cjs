'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {assessCapture,serverDocument}=require('./support/dashboard-journey-capture.cjs');
const generation=index=>new Date(Date.parse('2026-10-31T00:00:00Z')+index*5000).toISOString();

function healthy() {
  const responses=[0,1,2].map(index=>({request_id:index+1,kind:index ? 'refresh' : 'navigation',
    request_started_ms:index*5000,completed_ms:index*5000+500,http_status:200,panel_status:'CURRENT',
    document:{generated_at:generation(index),max_age_seconds:9,headline_class:'state ok',warning_ids:[]}}));
  return {capture:{complete:true,status:'COMPLETE',event_overflow:false},responses,events:[
    {type:'paint',start_ms:600},{type:'navigation-timing',document_time_origin_ms:100000,timing:{startTime:0,responseEnd:500}},
    ...responses.map(item=>({type:'meaningful-content',generated_at:item.document.generated_at,
      document_time_origin_ms:100000,browser_ms:item.completed_ms+100,node_ms:item.completed_ms+100}))]};
}
test('complete fast healthy evidence passes; targets remain independent',()=>{
  assert.equal(assessCapture(healthy()).status,'PASS');
  const report=healthy();report.events.find(item=>item.type==='meaningful-content').browser_ms=4000;
  assert.deepEqual(assessCapture(report).findings.map(item=>item.code),['SLOW_LAUNCH','SLOW_CONTENT_AFTER_RESPONSE']);
});
test('missing timing, overflow and incomplete evidence never pass',()=>{
  for (const change of [report=>report.events=[],report=>report.capture.complete=false,report=>report.capture.event_overflow=true]) {
    const report=healthy();change(report);assert.equal(assessCapture(report).status,'FAIL');
  }
});
test('negative server evidence is separate and cannot be masked by browser green',()=>{
  const report=healthy();report.responses[1].document.headline_class='state fail';
  report.events.push({type:'visible-state',generated_at:generation(1),headline_class:'state ok'});
  const codes=assessCapture(report).findings.map(item=>item.code);
  assert.ok(codes.includes('BACKEND_NOT_HEALTHY'));assert.ok(codes.includes('NEGATIVE_PRECEDENCE_LOST'));
  assert.ok(!codes.includes('HEALTHY_REFRESH_FLICKER'));
});
test('even a short healthy amber mutation remains an acceptance failure',()=>{
  const report=healthy();report.events.push({type:'badge-transition',generated_at:generation(0),headline_class:'state warn'});
  assert.ok(assessCapture(report).findings.some(item=>item.code==='HEALTHY_REFRESH_FLICKER'));
});
test('unattributed status, expired green and a blank document cannot pass',()=>{
  for (const event of [
    {type:'badge-transition',generated_at:'unknown',headline_class:'state warn'},
    {type:'visible-state',generated_at:generation(0),headline_class:null,meaningful_visible:false,node_ms:1000},
  ]) {
    const report=healthy();report.events.push(event);assert.equal(assessCapture(report).status,'FAIL');
  }
  const report=healthy();report.responses[0].document.generated_at='2026-10-31T00:00:00Z';
  report.events[2].generated_at=report.responses[0].document.generated_at;
  report.events.push({type:'badge-transition',generated_at:report.responses[0].document.generated_at,
    headline_class:'state ok',wall_time_ms:Date.parse('2026-10-31T00:00:10Z')});
  assert.ok(assessCapture(report).findings.some(item=>item.code==='STALE_GREEN'));
});
test('malformed original generation cannot pass the source identity check',()=>{
  const report=healthy();report.responses[1].document.generated_at='not-a-date';
  assert.ok(assessCapture(report).findings.some(item=>item.code==='NON_CURRENT_SERVER_DOCUMENT'));
});
test('server document summary keeps original identity and warning IDs without account payload',()=>{
  const html='<body data-generated-at="2026-10-31T00:00:00Z" data-max-age-seconds="9" data-refresh-pending="false"><span id="operational-state" class="state warn">Needs &amp; attention</span><a href="#status-sender">secret account amount</a>';
  const doc=serverDocument(html);
  assert.equal(doc.headline_label,'Needs & attention');assert.deepEqual(doc.warning_ids,['sender']);
  assert.equal(doc.sha256.length,64);assert.ok(!JSON.stringify(doc).includes('secret account amount'));
});

function withBanners(report=healthy()) {
  for (const response of report.responses) Object.assign(response.document,{
    banner_required:true,banner_path:'/static/caesars-palace-512.png'});
  for (const event of report.events.filter(item=>item.type==='meaningful-content')) Object.assign(event,{
    banner_present:true,banner_assigned:true,banner_complete:true,banner_width:512,banner_height:512,
    banner_displayed:true,banner_path:'/static/caesars-palace-512.png'});
  return report;
}

test('banner acceptance is additional to unchanged financial content timing',()=>{
  const original=healthy(),report=withBanners();
  assert.equal(assessCapture(report).status,'PASS');
  assert.deepEqual(assessCapture(report).metrics,assessCapture(original).metrics);
  assert.deepEqual(assessCapture(report).targets,assessCapture(original).targets);
});

test('blank completed image cannot pass even when all financial content is visible',()=>{
  const report=withBanners();
  const event=report.events.find(item=>item.generated_at===generation(1));
  Object.assign(event,{banner_width:0,banner_height:0,banner_displayed:false});
  assert.deepEqual(assessCapture(report).findings.map(item=>item.code),['BANNER_UNAVAILABLE']);
  assert.equal(assessCapture(report).findings[0].request_id,2);
});

test('every banner document requires its own positive decoded and displayed evidence',()=>{
  for (const change of [
    event=>{delete event.banner_present;},
    event=>{event.banner_complete=false;},
    event=>{event.banner_displayed=false;},
    event=>{event.banner_width=1;event.banner_height=1;},
    event=>{event.banner_path='/static/other.png';}
  ]) {
    const report=withBanners();
    change(report.events.find(item=>item.generated_at===generation(2)));
    const codes=assessCapture(report).findings.map(item=>item.code);
    assert.ok(codes.includes('MISSING_BANNER_EVIDENCE') || codes.includes('BANNER_UNAVAILABLE'));
    assert.equal(assessCapture(report).status,'FAIL');
  }
});

test('source detection keeps only the banner path and never its recovery query',()=>{
  for (const attribute of ['src','data-banner-src']) {
    const doc=serverDocument(`<body><div class="brand"><img ${attribute}="/static/caesars-palace-512.png?recovery=private-token"></div></body>`);
    assert.equal(doc.banner_required,true);
    assert.equal(doc.banner_path,'/static/caesars-palace-512.png');
    assert.ok(!JSON.stringify(doc).includes('private-token'));
  }
  assert.equal(serverDocument('<body>Recorder-only fixture</body>').banner_required,false);
});

test('removing banner admission makes the blank-image oracle fail',()=>{
  const fs=require('node:fs'),vm=require('node:vm');
  const filename=require.resolve('./support/dashboard-journey-capture.cjs');
  const source=fs.readFileSync(filename,'utf8'),guard='if (doc?.banner_required) {';
  assert.equal(source.split(guard).length,2);
  const context={module:{exports:{}},require};
  vm.runInNewContext(source.replace(guard,'if (false) {'),context,{filename:'removed-banner-admission'});
  const report=withBanners();
  Object.assign(report.events.find(item=>item.generated_at===generation(1)),{
    banner_width:0,banner_height:0,banner_displayed:false});
  assert.throws(()=>assert.equal(context.module.exports.assessCapture(report).status,'FAIL'),assert.AssertionError);
});
