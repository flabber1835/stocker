'use strict';
const http=require('node:http');
const crypto=require('node:crypto');
const {performance}=require('node:perf_hooks');
const MAX_BODY=2*1024*1024;
const SAFE_HEADERS=['content-type','cache-control','x-sentinel-panel-status','retry-after',
  'service-worker-allowed','content-security-policy','x-content-type-options','referrer-policy',
  'expires','pragma','date','age','etag','vary'];

function hold(ms,signal) {
  return new Promise((resolve,reject)=>{
    if (signal.aborted) { reject(new Error('OWNED_REQUEST_ABORTED')); return; }
    const abort=()=>{clearTimeout(timer);reject(new Error('OWNED_REQUEST_ABORTED'));};
    const timer=setTimeout(()=>{signal.removeEventListener('abort',abort);resolve();},ms);
    signal.addEventListener('abort',abort,{once:true});
  });
}

async function startJourneyTransport({upstreamUrl,refreshFloorMs}) {
  const upstream=new URL(upstreamUrl);
  if (!['http:','https:'].includes(upstream.protocol) || upstream.username || upstream.password ||
      upstream.search || upstream.hash || upstream.pathname!=='/' ||
      !Number.isInteger(refreshFloorMs) || refreshFloorMs<0 || refreshFloorMs>15000) {
    throw new Error('Invalid plain root origin or bounded refresh floor');
  }
  const profile={name:'slow-refresh-floor',refresh_floor_ms:refreshFloorMs,
    upstream_origin:upstream.origin,proxy_origin:null,upstream_requests:[],errors:[]};
  const controllers=new Set(),sockets=new Set(),tasks=new Set();
  let closed=false,firstRoot=true;
  const handle=async (request,response)=>{
    if (closed) { response.destroy(); return; }
    let requested;
    try { requested=new URL(request.url,profile.proxy_origin); } catch (_) { response.writeHead(400);response.end();return; }
    if (request.method!=='GET' || requested.origin!==profile.proxy_origin ||
        requested.search || requested.hash || requested.username || requested.password) {
      profile.errors.push('NON_GET_OR_UNSAFE_REQUEST');response.writeHead(405);response.end();return;
    }
    const controller=new AbortController();controllers.add(controller);
    const abort=()=>{if (!response.writableEnded) controller.abort();};
    response.once('close',abort);request.once('aborted',()=>controller.abort());
    const timeout=setTimeout(()=>controller.abort(),20000);
    const root=requested.pathname==='/';
    let record;
    if (root) {
      const navigation=firstRoot || request.headers['sec-fetch-mode']==='navigate' || request.headers['sec-fetch-dest']==='document';
      firstRoot=false;
      record={sequence:profile.upstream_requests.length+1,kind:navigation ? 'navigation' : 'refresh',
        http_status:null,panel_status:null,cache_control:null,sha256:null,upstream_ms:null,
        hold_ms:0,total_ms:null,served:false};
      if (record.sequence>32) { profile.errors.push('ROOT_REQUEST_LIMIT');response.writeHead(503);response.end();clearTimeout(timeout);controllers.delete(controller);return; }
      profile.upstream_requests.push(record);
    }
    const started=performance.now();
    try {
      const result=await fetch(new URL(requested.pathname,upstream.origin),{method:'GET',redirect:'manual',
        credentials:'omit',headers:{'accept-encoding':'identity',accept:request.headers.accept || '*/*'},signal:controller.signal});
      if (result.status>=300 && result.status<400) throw new Error('UPSTREAM_REDIRECT_REFUSED');
      const chunks=[];let size=0;
      if (result.body) {
        const reader=result.body.getReader();
        for (;;) {
          const item=await reader.read();if (item.done) break;
          size+=item.value.byteLength;
          if (size>MAX_BODY) { controller.abort();throw new Error('UPSTREAM_ENTITY_TOO_LARGE'); }
          chunks.push(Buffer.from(item.value));
        }
      }
      const body=Buffer.concat(chunks),upstreamMs=performance.now()-started;
      if (record) Object.assign(record,{http_status:result.status,panel_status:result.headers.get('x-sentinel-panel-status'),
        cache_control:result.headers.get('cache-control'),sha256:crypto.createHash('sha256').update(body).digest('hex'),upstream_ms:upstreamMs});
      if (record?.kind==='refresh') {
        const before=performance.now();await hold(Math.max(0,refreshFloorMs-upstreamMs),controller.signal);
        record.hold_ms=performance.now()-before;
      }
      if (controller.signal.aborted || closed) throw new Error('OWNED_REQUEST_ABORTED');
      // fetch may decode an entity. Old compression/length/transfer headers
      // and private cookie fields must not describe this local transport.
      const headers={};for (const key of SAFE_HEADERS) if (result.headers.has(key)) headers[key]=result.headers.get(key);
      response.writeHead(result.status,headers);
      if (record) Object.assign(record,{total_ms:performance.now()-started,served:true});
      response.end(body);
    } catch (_) {
      profile.errors.push('UPSTREAM_TRANSPORT_ERROR');
      if (!response.destroyed && !response.headersSent) response.writeHead(502,{'Content-Type':'text/plain','Cache-Control':'no-store'});
      if (!response.destroyed) response.end('Owned journey transport could not complete.');
    } finally {clearTimeout(timeout);controllers.delete(controller);response.removeListener('close',abort);}
  };
  const server=http.createServer((request,response)=>{
    const task=handle(request,response);tasks.add(task);
    task.catch(()=>profile.errors.push('PROXY_HANDLER_ERROR')).finally(()=>tasks.delete(task));
  });
  server.on('connection',socket=>{sockets.add(socket);socket.once('close',()=>sockets.delete(socket));});
  await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
  profile.proxy_origin=`http://127.0.0.1:${server.address().port}`;
  return {url:profile.proxy_origin+'/',profile,async close(){
    if (closed) return;closed=true;
    for (const controller of controllers) controller.abort();
    const stopping=new Promise((resolve,reject)=>server.close(error=>error ? reject(error) : resolve()));
    for (const socket of sockets) socket.destroy();
    await stopping;
    await Promise.allSettled([...tasks]);
  }};
}

function bindTransport(report,profile) {
  const upstream=profile.upstream_requests.filter(item=>item.served);
  const captured=report.responses || [];
  const errors=[],pairs=[];
  if (profile.errors.length) errors.push('PROXY_TRANSPORT_ERROR');
  if (upstream.length!==3 || captured.length!==3) errors.push('RESPONSE_COUNT_MISMATCH');
  for (let index=0;index<3;index++) {
    const source=upstream[index],observed=captured[index];
    if (!source || !observed || source.kind!==observed.kind || source.sha256!==observed.document?.sha256 ||
        source.http_status!==observed.http_status || source.panel_status!==observed.panel_status ||
        source.cache_control!==observed.cache_control) errors.push(`ENTITY_OR_VERDICT_MISMATCH_${index+1}`);
    else pairs.push({upstream_sequence:source.sequence,request_id:observed.request_id,sha256:source.sha256});
  }
  return {matched:errors.length===0,pairs,errors};
}
module.exports={startJourneyTransport,bindTransport};
