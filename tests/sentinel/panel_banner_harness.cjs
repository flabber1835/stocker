'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const request=JSON.parse(fs.readFileSync(0,'utf8'));
const asset='/static/caesars-status-green.gif',assignments=[];
const window={};
function boot(cachedFailure=false){
 const listeners={},wake={},attributes={'data-banner-src':asset},imageClasses=new Set(),classes=new Set();
 let observer;
 const fallback={hidden:true};
 const image={complete:true,naturalWidth:0,hidden:true,
  classList:{toggle:(name,on)=>on?imageClasses.add(name):imageClasses.delete(name)},
  getAttribute:name=>attributes[name]??null,
  addEventListener:(name,fn)=>listeners[name]=fn};
 Object.defineProperty(image,'src',{set(value){
  assignments.push(value);attributes.src=value;image.complete=cachedFailure&&value===asset;image.naturalWidth=0;
 }});
 window.addEventListener=(name,fn)=>wake[name]=fn;
 const motion={matches:false,addEventListener:(_name,fn)=>wake.motion=fn};
 window.matchMedia=()=>motion;
 if(request.browserState)classes.add(request.browserState);
 const document={body:{dataset:{health:request.health??'green',refreshPending:String(request.refreshPending===true)}},
  documentElement:{classList:{contains:name=>classes.has(name)}},
  querySelector:selector=>selector==='.brand img[data-banner-src]'?image:
  selector==='.brand-fallback'?fallback:null};
 class MutationObserver {constructor(fn){observer=fn;} observe(){}}
 vm.runInNewContext(request.script,{window,document,Date,Math,MutationObserver},{timeout:1000});
 return {image,fallback,wake,motion,imageClasses,src:()=>attributes.src,
  update(color,...state){document.body.dataset.health=color;classes.clear();state.forEach(c=>classes.add(c));observer();},
  fail(){image.complete=true;image.naturalWidth=0;listeners.error();},
  load(){image.complete=true;image.naturalWidth=1086;listeners.load();}};
}
if(request.case==='foreign-state')window.__sentinelMarqueeResources={[asset]:{url:'https://unrelated.invalid/',recovered:false,failed:false}};
const first=boot(request.case==='already-failed');
switch(request.case){
 case 'selection':
  console.log(JSON.stringify({src:first.src(),unknown:first.imageClasses.has('unknown-sign')}));
  break;
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
  assert.equal(window.__sentinelMarqueeResources[asset].failed,true,'second failure was not terminal');
  assert.equal(first.image.hidden,true);assert.equal(first.fallback.hidden,false);
  first.wake.pageshow();const second=boot();second.wake.pageshow();
  assert.equal(assignments.length,2,'consumed recovery budget was renewed');
  assert.equal(second.fallback.hidden,false);break;
 case 'replacement':
  first.fail();const selected=first.src();first.load();
  const next=boot();assert.equal(next.src(),selected);assert.equal(window.__sentinelMarqueeResources[asset].recovered,true);
  next.load();assert.equal(next.image.hidden,false);assert.equal(next.fallback.hidden,true);break;
 case 'foreign-state':
  assert.deepEqual(assignments,[asset]);break;
 case 'status':
  first.update('green');assert.equal(assignments.length,1,'same status cannot restart a loaded sign');
  first.update('amber');assert.match(first.src(),/amber\.gif$/);
  first.update('amber','checking-status');assert.match(first.src(),/amber-still\.gif$/);
  first.update('red');assert.match(first.src(),/red\.gif$/);
  first.update('red','not-current');assert.match(first.src(),/green-still\.gif$/);
  assert(first.imageClasses.has('unknown-sign'));
  first.update('green','checking-status');assert(first.imageClasses.has('unknown-sign'),'expired green must be colorless');
  first.update('blue');assert(first.imageClasses.has('unknown-sign'));
  first.update('green');assert(!first.imageClasses.has('unknown-sign'));
  first.motion.matches=true;first.wake.motion();assert.match(first.src(),/green-still\.gif$/,'reduced motion must use a single frame');
  break;
 default:throw Error('Unknown banner case');
}
if(request.case!=='selection')console.log(JSON.stringify({case:request.case,assignments,passed:true}));
