'use strict';

const {createHash}=require('node:crypto');
const {expect}=require('@playwright/test');

// The private loopback origins must serve what the real renderer declared.
// Keep HTML independent from the assets, just as the production route does.
async function panelAssets(request,...documents) {
  const paths=new Set();
  for(const html of documents) {
    for(const match of html.matchAll(/\s(?:src|href)="(\/static\/[a-z0-9.-]+)"/g)) {
      paths.add(match[1]);
    }
  }
  const assets=await Promise.all([...paths].map(async path=>{
    const response=await request.get(path);
    expect(response.status(),path).toBe(200);
    const {'content-type':type,'cache-control':cache}=response.headers();
    const body=await response.body();
    const fingerprint=path.match(/\.([a-f0-9]{64})\.(css|js)$/);
    if(fingerprint) {
      expect(createHash('sha256').update(body).digest('hex'),path).toBe(fingerprint[1]);
      expect(type,path).toMatch(fingerprint[2]==='css' ? /^text\/css\b/ : /^text\/javascript\b/);
      expect(cache,path).toContain('immutable');
    }
    return [path,{headers:{'content-type':type,'cache-control':cache},body}];
  }));
  return new Map(assets);
}

function servePanelAsset(response,asset) {
  response.writeHead(200,{...asset.headers,'content-length':asset.body.length});
  response.end(asset.body);
}

module.exports={panelAssets,servePanelAsset};
