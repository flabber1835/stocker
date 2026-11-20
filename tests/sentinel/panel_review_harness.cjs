// Execute the real acknowledgement control; no browser or backend network.
const vm = require('node:vm');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
let click, request, reloads = 0, timer, requests = 0;
const button = {disabled:false, dataset:{viewToken:'reviewed-view'},
  closest:selector=>selector==='#review-acknowledge'?button:null};
const result = {textContent:''};
let resolve, reject;
const response = new Promise((a,b)=>{resolve=a;reject=b;});
const win = {location:{reload:()=>reloads++}};
vm.runInNewContext(input.script, {
  document:{getElementById:id=>id==='review-result'?result:button,
    addEventListener:(name,fn)=>{if(name==='click')click=fn;}},
  window:win, AbortController,
  setTimeout:fn=>{timer=fn;return 1;},clearTimeout:()=>{},
  fetch:(url,options)=>{requests++;request={url,options};options.signal.addEventListener('abort',()=>reject(new Error('timeout')));return response;}
});
assert.equal(request,undefined,'rendering cannot acknowledge');
if (input.case==='absent') {
  click({target:{closest:()=>null}});
  assert.equal(request,undefined);process.stdout.write('PASS\n');
} else {
  const operation = click({target:button});
  click({target:button});
  assert.equal(requests,1,'one click owns one acknowledgement');
  assert.equal(button.disabled,true);
  assert.equal(request.url,'/review/acknowledge');
  assert.equal(request.options.method,'POST');
  assert.equal(request.options.credentials,'same-origin');
  assert.equal(request.options.cache,'no-store');
  assert.deepEqual(JSON.parse(request.options.body),{token:'reviewed-view'});
  assert.equal(reloads,0,'only a fresh server page can establish green');
  if(input.case==='renew-during'){
    button.dataset.viewToken='new-view'; win.syncReviewControl(); click({target:button});
    assert.equal(requests,1,'pending attempt owns the page through refresh');
  }
  if (input.case==='timeout') timer();
  else if (input.case==='network') reject(new Error('offline'));
  else resolve({ok:input.case==='success' || input.case==='malformed',
    json:async()=>input.case==='malformed'?{status:'REVIEW',head:2,reviewed_head:1}:
      {status:'CLEAN',head:2,reviewed_head:2}});
  operation.then(()=>{
    assert.equal(reloads,input.case==='success'?1:0,'failed acknowledgement cannot refresh into success');
    if(input.case==='renew-during' || input.case==='renew-after'){
      if(input.case==='renew-after'){assert.equal(button.disabled,true); button.dataset.viewToken='new-view'; win.syncReviewControl();}
      assert.equal(button.disabled,false,'a fresh eligible view is actionable');
      assert.equal(requests,1,'refresh cannot acknowledge automatically');
      click({target:button});
      assert.equal(requests,2); assert.equal(JSON.parse(request.options.body).token,'new-view');
    }else assert.equal(button.disabled,true,'consumed view stays disabled');
    if(!input.case.startsWith('renew-')) assert(result.textContent.includes(input.case==='success'?'recorded':'unavailable'));
    process.stdout.write('PASS\n');
  }).catch(error=>{console.error(error.message);process.exitCode=1;});
}
