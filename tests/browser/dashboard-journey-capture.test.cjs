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
