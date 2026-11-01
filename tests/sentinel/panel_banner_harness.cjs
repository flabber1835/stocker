'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const request=JSON.parse(fs.readFileSync(0,'utf8'));
const asset='/static/caesars-palace-512.png',assignments=[];
const window={};
function boot(cachedFailure=false){
 const listeners={},wake={},attributes={'data-banner-src':asset};
 const fallback={hidden:true};
 const image={complete:true,naturalWidth:0,hidden:true,
  getAttribute:name=>attributes[name]??null,
  addEventListener:(name,fn)=>listeners[name]=fn};
 Object.defineProperty(image,'src',{set(value){
  assignments.push(value);attributes.src=value;image.complete=cachedFailure&&value===asset;image.naturalWidth=0;
 }});
 window.addEventListener=(name,fn)=>wake[name]=fn;
 const document={querySelector:selector=>selector==='.brand img[data-banner-src]'?image:
  selector==='.brand-fallback'?fallback:null};
 vm.runInNewContext(request.script,{window,document,Date,Math},{timeout:1000});
 return {image,fallback,wake,src:()=>attributes.src,
  fail(){image.complete=true;image.naturalWidth=0;listeners.error();},
  load(){image.complete=true;image.naturalWidth=512;listeners.load();}};
}
if(request.case==='foreign-state')window.__sentinelBannerResource={asset,url:'https://unrelated.invalid/',recovered:false,failed:false};
const first=boot(request.case==='already-failed');
switch(request.case){
 case 'healthy':
  first.load();assert.equal(assignments.length,1);assert.equal(first.src(),asset);
  assert.equal(first.image.hidden,false);assert.equal(first.fallback.hidden,true);break;
 case 'pending':
  first.wake.pageshow();assert.equal(first.image.complete,false);
  assert.equal(assignments.length,1,'pending image identity changed');
  assert.equal(first.fallback.hidden,true);break;
 case 'first-failure':
  first.fail();assert.equal(assignments.length,2);assert.match(first.src(),/\?banner-load=[a-z0-9-]+$/);
  first.load();assert.equal(first.image.hidden,false);assert.equal(first.fallback.hidden,true);break;
 case 'already-failed':
  assert.equal(assignments.length,2);assert.notEqual(first.src(),asset);break;
 case 'second-failure':
  first.fail();first.fail();
  assert.equal(window.__sentinelBannerResource.failed,true,'second failure was not terminal');
  assert.equal(first.image.hidden,true);assert.equal(first.fallback.hidden,false);
  first.wake.pageshow();const second=boot();second.wake.pageshow();
  assert.equal(assignments.length,2,'consumed recovery budget was renewed');
  assert.equal(second.fallback.hidden,false);break;
 case 'replacement':
  first.fail();const selected=first.src();first.load();
  const next=boot();assert.equal(next.src(),selected);assert.equal(window.__sentinelBannerResource.recovered,true);
  next.load();assert.equal(next.image.hidden,false);assert.equal(next.fallback.hidden,true);break;
 case 'foreign-state':
  assert.deepEqual(assignments,[asset]);break;
 default:throw Error('Unknown banner case');
}
console.log(JSON.stringify({case:request.case,assignments,passed:true}));
