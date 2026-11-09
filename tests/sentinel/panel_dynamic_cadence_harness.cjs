// Execute the real controller and reconciler with a finite DOM-shaped model.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const stamp=Date.parse(input.initial.generatedAt);
let now=stamp,mono=0,sequence=0;
const timers=new Map(),listeners={},reads=[],heartbeatWrites=[];
let liveBody=null;
function isLive(node){while(node.parentNode)node=node.parentNode;return node===liveBody;}
class Text {
 constructor(value){this.nodeType=3;this.nodeName='#text';this.value=value;this.parentNode=null;}
 get nodeValue(){return this.value;}
 set nodeValue(value){this.value=value;if(this.parentNode?.id==='dashboard-heartbeat'&&isLive(this))heartbeatWrites.push({at:mono,text:value});}
 get nextSibling(){return sibling(this);}
 cloneNode(){return new Text(this.value);}
 isEqualNode(other){return other.nodeType===3&&this.value===other.value;}
 remove(){detach(this);}
}
function sibling(node){const list=node.parentNode?.childNodes||[];return list[list.indexOf(node)+1]||null;}
function detach(node){if(node.parentNode){const list=node.parentNode.childNodes;list.splice(list.indexOf(node),1);node.parentNode=null;}}
class Element {
 constructor(name,attrs={}){this.nodeType=1;this.nodeName=name.toUpperCase();this.tagName=this.nodeName;this.attrs={...attrs};this.childNodes=[];this.parentNode=null;}
 get id(){return this.attrs.id||'';}
 get attributes(){return Object.entries(this.attrs).map(([name,value])=>({name,value}));}
 get dataset(){return new Proxy({}, {get:(_,key)=>this.attrs['data-'+String(key).replace(/[A-Z]/g,c=>'-'+c.toLowerCase())],set:(_,key,value)=>{this.setAttribute('data-'+String(key).replace(/[A-Z]/g,c=>'-'+c.toLowerCase()),value);return true;}});}
 get classList(){return{contains:value=>(this.attrs.class||'').split(' ').includes(value)};}
 get className(){return this.attrs.class||'';}set className(value){this.attrs.class=value;}
 get firstChild(){return this.childNodes[0]||null;}get nextSibling(){return sibling(this);}
 get open(){return this.hasAttribute('open');}set open(value){if(value)this.setAttribute('open','');else this.removeAttribute('open');}
 hasAttribute(name){return Object.hasOwn(this.attrs,name);}getAttribute(name){return this.attrs[name]??null;}
 setAttribute(name,value){this.attrs[name]=String(value);}removeAttribute(name){delete this.attrs[name];}
 get textContent(){return this.childNodes.map(n=>n.nodeType===3?n.nodeValue:n.textContent).join('');}
 set textContent(value){if(this.id==='dashboard-heartbeat'&&isLive(this))heartbeatWrites.push({at:mono,text:value});this.childNodes=[];this.append(new Text(value));}
 append(node){detach(node);this.childNodes.push(node);node.parentNode=this;return node;}
 insertBefore(node,cursor){detach(node);const index=cursor?this.childNodes.indexOf(cursor):this.childNodes.length;assert(index>=0);this.childNodes.splice(index,0,node);node.parentNode=this;}
 remove(){detach(this);}
 cloneNode(deep){const copy=new Element(this.nodeName,this.attrs);if(deep)this.childNodes.forEach(n=>copy.append(n.cloneNode(true)));return copy;}
 querySelectorAll(selector){const all=[];for(const child of this.childNodes)if(child.nodeType===1){if(selector==='script'&&child.nodeName==='SCRIPT')all.push(child);all.push(...child.querySelectorAll(selector));}return all;}
 isEqualNode(other){return other.nodeType===1&&this.nodeName===other.nodeName&&JSON.stringify(this.attrs)===JSON.stringify(other.attrs)&&this.childNodes.length===other.childNodes.length&&this.childNodes.every((n,i)=>n.isEqualNode(other.childNodes[i]));}
}
function find(root,id){if(root.id===id)return root;for(const child of root.childNodes||[]){const result=find(child,id);if(result)return result;}return null;}
function makeDocument(meta){
 const body=new Element('body',Object.fromEntries(Object.entries(meta).map(([key,value])=>['data-'+key.replace(/[A-Z]/g,c=>'-'+c.toLowerCase()),String(value)])));
 const wrap=body.append(new Element('div',{class:'wrap'}));
 const badge=wrap.append(new Element('span',{id:'operational-state',class:'state ok'}));badge.textContent='Healthy';
 const heart=wrap.append(new Element('span',{id:'dashboard-heartbeat'}));heart.textContent='DASHBOARD HEARTBEAT · UPDATED 0s AGO';
 wrap.append(new Element('details',{'data-detail-key':'orders'}));
 const style=new Element('style');style.textContent='stable stylesheet';
 return {body,title:'Fixture',querySelector:selector=>selector==='.wrap'?wrap:selector==='head style'?style:null,getElementById:id=>find(body,id)};
}
const document=makeDocument(input.initial),classes=new Set();
liveBody=document.body;
document.visibilityState='visible';document.addEventListener=(name,fn)=>{listeners[name]=fn;};
document.documentElement={classList:{add:value=>classes.add(value),remove:(...values)=>values.forEach(v=>classes.delete(v))}};
const detail=document.querySelector('.wrap').childNodes[2];detail.open=true;
let scrollCalls=0;
function schedule(fn,delay){const id=++sequence;timers.set(id,{fn,delay,due:now+delay,age:fn.name==='heartbeatTick'});return id;}
class Clock extends Date {static now(){return now;}}
const context={document,Date:Clock,DOMParser:class{parseFromString(html){return makeDocument(JSON.parse(html));}},AbortController,
 performance:{now:()=>mono},navigator:{onLine:true},location:{href:'https://fixture.invalid/'},
 window:{scrollY:42,scrollTo(){scrollCalls++;},addEventListener:(name,fn)=>{listeners[name]=fn;}},
 setTimeout:schedule,clearTimeout:id=>timers.delete(id),setInterval:()=>{throw new Error('one owned heartbeat timeout required');},
 fetch:(_url,options)=>new Promise((resolve,reject)=>{reads.push({resolve,reject,started:now});options.signal.addEventListener('abort',()=>reject(new Error('timeout')));})};
function setClock(utc,monotonic=utc){now=stamp+utc;mono=monotonic;}
async function settled(){for(let i=0;i<12;i++)await Promise.resolve();}
async function advance(target){
 for(let guard=0;guard<5000;guard++){
  const entry=[...timers.entries()].filter(([,t])=>t.due<=stamp+target).sort((a,b)=>a[1].due-b[1].due||a[0]-b[0])[0];
  if(!entry){mono+=stamp+target-now;now=stamp+target;await settled();return;}
  mono+=entry[1].due-now;now=entry[1].due;timers.delete(entry[0]);entry[1].fn();await settled();
 }throw new Error('unbounded timer loop');
}
function activePoll(){return [...timers.values()].filter(t=>!t.age).map(t=>t.delay);}
async function accept(budget,lag=0){
 const meta={...input.incoming,generatedAt:new Date(now-lag).toISOString(),maxAgeSeconds:String(budget)};
 reads.at(-1).resolve({ok:true,status:200,headers:{get:()=> 'CURRENT'},text:async()=>JSON.stringify(meta)});await settled();
}
function ageTick(){const entry=[...timers.entries()].find(([,t])=>t.age);assert(entry);timers.delete(entry[0]);entry[1].fn();}
(async()=>{
 vm.runInNewContext(input.script,context);
 if(input.scenario==='initial-cadence'){
  assert.deepEqual(activePoll(),[input.expectedPoll],'initial cadence must follow the actual health proof');
  assert.equal(timers.size,2,'one heartbeat owner and one refresh owner');
 }else if(input.scenario==='cadence'){
  await advance(13000);assert.equal(reads.length,1);await accept(8);
  assert.deepEqual(activePoll(),[5000],'accepted short publication must replace the old cadence');
  const first=reads[0].started;
  for(let i=1;i<=12;i++){
   await advance(13000+i*5000);assert.equal(reads.length,i+1,'one ordinary read per current five-second cadence');
   assert(!classes.has('not-current'),'short current documents cannot expire before their new ordinary read');
   await accept(8);assert.equal(timers.size,2,'one heartbeat owner and one refresh owner');
   assert(detail.open&&document.querySelector('.wrap').childNodes[2]===detail,'reconciliation preserves open inspection identity');
  }
  assert.equal(reads[1].started-first,5000);assert.equal(scrollCalls,0);assert.equal(context.window.scrollY,42);
 }else if(input.scenario==='late-visual'){
  heartbeatWrites.length=0;setClock(5200);ageTick();
  assert.equal(heartbeatWrites.length,1,'late callback writes current visual age once');
  assert(heartbeatWrites[0].text.includes('UPDATED 5s'));
  const count=heartbeatWrites.length;listeners.pageshow({persisted:false});assert.equal(heartbeatWrites.length,count,'unchanged heartbeat text is not rewritten');
  const timer=[...timers.values()].find(t=>t.age);assert.equal(timer.delay,800,'next visual boundary is aligned, not a digit catch-up loop');
 }else if(input.scenario==='monotonic-visual'){
  setClock(3000,3000);ageTick();assert(document.getElementById('dashboard-heartbeat').textContent.includes('UPDATED 3s'));
  setClock(1000,4000);ageTick();assert(document.getElementById('dashboard-heartbeat').textContent.includes('UPDATED 4s'),'visual elapsed progression must use monotonic time');
  setClock(30000,5000);ageTick();assert(classes.has('not-current'),'monotonic display cannot renew the UTC evidence deadline');
 }else if(input.scenario==='owned-heartbeat'){
  await advance(13000);heartbeatWrites.length=0;await accept(8,1900);
  assert(!heartbeatWrites.some(v=>v.text.includes('UPDATED 0s')),'server DOM must not reset the client heartbeat to zero');
  assert(document.getElementById('dashboard-heartbeat').textContent.includes('UPDATED 1s'));
 }else if(input.scenario==='resume'){
  await advance(13000);document.visibilityState='hidden';listeners.visibilitychange();
  await accept(8);assert.equal(document.body.dataset.maxAgeSeconds,input.initial.maxAgeSeconds,'hidden response must not replace document');
  setClock(14000);document.visibilityState='visible';listeners.visibilitychange();listeners.focus();listeners.pageshow({persisted:true});
  assert.equal(reads.length,2,'foreground events share one resumed read');await accept(8);
  assert.deepEqual(activePoll(),[5000]);assert.equal(timers.size,2);
 }else throw new Error('unknown scenario');
 process.stdout.write('PASS\n');
})().catch(error=>{console.error(error);process.exit(1);});
