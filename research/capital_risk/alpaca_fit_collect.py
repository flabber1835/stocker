"""Bounded market-only capture. Never imports strategy, account, broker or DB code."""
from __future__ import annotations
import argparse
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import struct
import sys
import time
from urllib import request, parse, error
from zoneinfo import ZoneInfo

from forecast_collect import ASSETS, BARS, FIGI, CONFIG, ROOT_STATE_SHA, NoRedirect, provider_keys, canonical, digest

ACTIONS = 'https://data.alpaca.markets/v1/corporate-actions'
TYPES = {'Common Stock':'Common Stock','ADR':'Depositary Receipt','GDR':'Depositary Receipt',
         'MLP':'Partnership Shares','Ltd Part':'Partnership Shares','REIT':'REIT',
         'Royalty Trst':'Common Stock','NY Reg Shrs':'Depositary Receipt','Closed-End Fund':'Mutual Fund'}
STREAM = False


def emit(metadata, payload=b''):
    encoded=canonical(metadata)
    if len(encoded)>16*1024**2 or len(payload)>32*1024**2:raise ValueError('REFUSED_FRAME_BOUND')
    output=sys.stdout.buffer
    output.write(struct.pack('>II',len(encoded),len(payload)));output.write(encoded);output.write(payload);output.flush()


def write(path, value, *, replace=False):
    raw = canonical(value) + b'\n'
    if replace:
        temporary = path.with_suffix('.tmp')
        with temporary.open('wb') as f: f.write(raw)
        temporary.replace(path)
    else:
        with path.open('xb') as f: f.write(raw)
        if STREAM:emit({'kind':'FILE','name':path.name},raw)


def prepare(state_path, protocol_path, destination):
    state_raw, protocol_raw = Path(state_path).read_bytes(), Path(protocol_path).read_bytes()
    state = json.loads(state_raw)
    if digest(canonical(state)) != ROOT_STATE_SHA: raise ValueError('REFUSED_ROSTER_SOURCE')
    roster = []
    for sid, row in state['feed']['series'].items():
        if sid != row['security_id']: raise ValueError('REFUSED_ROSTER_IDENTITY')
        roster.append({'asset_id':sid,'ticker':row['ticker']})
    if len({r['ticker'] for r in roster}) != len(roster): raise ValueError('REFUSED_ROSTER_TICKER_ALIAS')
    write(Path(destination), {'schema':'research.alpaca-fit-roster/1','retained_provider':'ALPACA_OPENFIGI',
        'retained_state_sha256':digest(state_raw),'retained_state_canonical_sha256':ROOT_STATE_SHA,
        'protocol_sha256':digest(protocol_raw),'selection':'ALL_RETAINED_FEED_IDENTITIES_NO_PRICE_RANKING',
        'roster':sorted(roster,key=lambda r:r['asset_id']),'financial_state_exported':False,
        'created_at':datetime.now(timezone.utc).isoformat()})


def classify(asset, response):
    if not isinstance(response,dict): raise ValueError('REFUSED_FIGI_RESPONSE')
    if 'error' in response: raise ValueError('REFUSED_FIGI_PROVIDER_ERROR')
    rows=response.get('data')
    if rows is None and isinstance(response.get('warning'),str): return None,'NO_MAPPING'
    if not isinstance(rows,list) or not rows: raise ValueError('REFUSED_FIGI_COVERAGE')
    facts=set()
    for row in rows:
        if (row.get('marketSector')!='Equity' or row.get('exchCode')!='US'
                or row.get('ticker')!=asset['ticker'].replace('.','/')
                or not all(row.get(k) for k in ('compositeFIGI','shareClassFIGI','securityType','securityType2'))):
            return None,'INCOMPLETE_OR_FOREIGN'
        facts.add(tuple(row[k] for k in ('compositeFIGI','shareClassFIGI','securityType','securityType2')))
    if len(facts)!=1:return None,'AMBIGUOUS_MAPPING'
    composite,share,kind,broad=next(iter(facts))
    if TYPES.get(kind)!=broad:return None,'NON_ORDINARY_EQUITY'
    return {**asset,'composite_figi':composite,'share_class_figi':share,'security_type':kind,'security_type2':broad},None


class Client:
    def __init__(self,root):
        self.root=root;self.keys=provider_keys(CONFIG);self.started=time.monotonic()
        self.opener=request.build_opener(NoRedirect());self.last={};self.receipts=[]
        self.raw_total=0;self.compressed_total=0

    def call(self,endpoint,params=None,body=None):
        if endpoint not in {ASSETS,BARS,ACTIONS,FIGI} or (endpoint==FIGI)!=(body is not None):
            raise ValueError('REFUSED_PROVIDER_ENDPOINT_OR_METHOD')
        if time.monotonic()-self.started>3300:raise ValueError('REFUSED_CAPTURE_TIME_BOUND')
        if len(self.receipts)>=2400:raise ValueError('REFUSED_REQUEST_COUNT_BOUND')
        if shutil.disk_usage(self.root).free<(256*1024**2 if STREAM else 1024**3):raise ValueError('REFUSED_PRIVATE_CAPTURE_DISK_BOUND')
        headers={'User-Agent':'Stocker-private-policy-fit/1'}
        payload=None
        if endpoint==FIGI:payload=canonical(body);headers['Content-Type']='application/json'
        else:headers.update({'APCA-API-KEY-ID':self.keys['ALPACA_API_KEY'],'APCA-API-SECRET-KEY':self.keys['ALPACA_SECRET_KEY']})
        url=endpoint+('?' + parse.urlencode(params) if params else '')
        for attempt in range(3):
            wait=(2.6 if endpoint==FIGI else .4)-(time.monotonic()-self.last.get(endpoint,0))
            if wait>0:time.sleep(wait)
            self.last[endpoint]=time.monotonic()
            try:
                with self.opener.open(request.Request(url,data=payload,headers=headers),timeout=25) as response:
                    raw=response.read(32*1024*1024+1)
                if len(raw)>32*1024*1024:raise ValueError('REFUSED_RESPONSE_BYTE_BOUND')
                self.raw_total+=len(raw)
                if self.raw_total>2*1024**3:raise ValueError('REFUSED_TOTAL_RAW_BOUND')
                value=json.loads(raw);compressed=gzip.compress(raw,compresslevel=1,mtime=0)
                self.compressed_total+=len(compressed)
                if self.compressed_total>512*1024**2:raise ValueError('REFUSED_COMPRESSED_BYTE_BOUND')
                name=f'provider-{len(self.receipts):04d}.json.gz'
                proof={'file':name,'endpoint':endpoint,'method':'POST' if body is not None else 'GET',
                    'params':params,'body':body,'raw_bytes':len(raw),'raw_sha256':digest(raw),
                    'bytes':len(compressed),'sha256':digest(compressed),'observed_at':datetime.now(timezone.utc).isoformat()}
                if STREAM:emit({'kind':'PROVIDER','name':name,'receipt':proof},compressed)
                else:
                    with (self.root/name).open('xb') as f:f.write(compressed)
                self.receipts.append(proof)
                with (self.root/'request-receipts.jsonl').open('ab') as f:f.write(canonical(proof)+b'\n')
                return value
            except error.HTTPError as exc:
                if exc.code not in {429,500,502,503,504} or attempt==2:
                    raise ValueError('PROVIDER_HTTP_'+str(exc.code)) from None
                time.sleep(3*(attempt+1))
            except (error.URLError,TimeoutError):
                if attempt==2:raise ValueError('PROVIDER_NETWORK_FAILURE') from None
                time.sleep(3*(attempt+1))
        raise ValueError('REFUSED_RETRY_EXHAUSTED')

    def progress(self,phase,**facts):
        write(self.root/'progress.json',{'status':'RUNNING','phase':phase,'requests':len(self.receipts),
            'raw_bytes':self.raw_total,'gzip_bytes':self.compressed_total,'seconds':time.monotonic()-self.started,
            'utc':datetime.now(timezone.utc).isoformat(),**facts},replace=True)

    def pages(self,endpoint,params,key,max_pages):
        token=None;seen=set()
        for page in range(max_pages):
            query=dict(params)
            if token is not None:query['page_token']=token
            reply=self.call(endpoint,query)
            if key not in reply or not isinstance(reply[key],dict):raise ValueError('REFUSED_PAGED_RESPONSE')
            yield reply[key]
            token=reply.get('next_page_token')
            if token is None:return
            if not isinstance(token,str) or token in seen:raise ValueError('REFUSED_PAGINATION')
            seen.add(token)
        raise ValueError('REFUSED_PAGE_LIMIT')


def collect(roster_path,protocol_path,destination):
    root=Path(destination);root.mkdir(parents=True,exist_ok=False)
    rr,pr=Path(roster_path).read_bytes(),Path(protocol_path).read_bytes();roster,protocol=json.loads(rr),json.loads(pr)
    if roster['protocol_sha256']!=digest(pr):raise ValueError('REFUSED_ROSTER_PROTOCOL')
    client=Client(root)
    result={'schema':'research.alpaca-fit-market-capture/1','status':'INCOMPLETE','roster_sha256':digest(rr),
        'protocol_sha256':digest(pr),'production_contacted':False,'account_order_position_activity_calls':0,
        'providers':['ALPACA','OPENFIGI_FREE']}
    try:
        client.progress('CATALOG')
        assets=client.call(ASSETS,{'status':'active','asset_class':'us_equity'})
        if not isinstance(assets,list) or len({a['id'] for a in assets})!=len(assets):raise ValueError('REFUSED_CATALOG')
        byid={a['id']:a for a in assets};proposed=[];excluded=[]
        for row in roster['roster']:
            a=byid.get(row['asset_id'],{})
            if (a.get('symbol')!=row['ticker'] or a.get('class')!='us_equity' or a.get('status')!='active' or a.get('exchange')=='OTC'):
                excluded.append({**row,'reason':'CURRENT_CATALOG_IDENTITY_OR_MEMBERSHIP'})
            else:proposed.append({**row,'exchange':a['exchange'],'name':a.get('name') or ''})
        # Qualify the required provider action endpoint before the long free mapping.
        start=(datetime.fromisoformat(protocol['data_start'])-timedelta(days=365)).date().isoformat()
        count=0
        for page in client.pages(ACTIONS,{'start':start,'end':protocol['data_end'],'limit':1000,'data_quality':'all','sort':'asc'},'corporate_actions',240):
            count+=sum(len(v) for v in page.values());client.progress('ACTIONS',action_records=count)
        selected=[]
        for offset in range(0,len(proposed),10):
            batch=proposed[offset:offset+10]
            body=[{'idType':'TICKER','idValue':r['ticker'].replace('.','/'),'exchCode':'US',
                   'marketSecDes':'Equity','includeUnlistedEquities':False} for r in batch]
            replies=client.call(FIGI,body=body)
            if not isinstance(replies,list) or len(replies)!=len(batch):raise ValueError('REFUSED_FIGI_BATCH')
            for asset,reply in zip(batch,replies):
                mapped,reason=classify(asset,reply)
                if mapped is None:excluded.append({**asset,'reason':reason})
                else:selected.append(mapped)
            client.progress('FREE_OPENFIGI',classified=min(offset+10,len(proposed)),required=len(proposed),selected=len(selected))
        if len(selected)<200:raise ValueError('REFUSED_INSUFFICIENT_BROAD_UNIVERSE')
        write(root/'classification.json',{'selected':selected,'excluded':excluded})
        ny=ZoneInfo('America/New_York');lo=datetime.fromisoformat(protocol['data_start']+'T00:00:00').replace(tzinfo=ny).isoformat()
        hi=(datetime.fromisoformat(protocol['data_end']+'T00:00:00').replace(tzinfo=ny)+timedelta(days=1)-timedelta(microseconds=1)).isoformat()
        counts={};symbols=sorted({r['ticker'] for r in selected})
        for adjustment in ('raw','split'):
            total=0
            for offset in range(0,len(symbols),400):
                query={'symbols':','.join(symbols[offset:offset+400]),'timeframe':'1Day','start':lo,'end':hi,
                       'adjustment':adjustment,'feed':'sip','asof':protocol['data_end'],'sort':'asc','limit':10000}
                for page in client.pages(BARS,query,'bars',65):
                    total+=sum(len(v) for v in page.values());client.progress('STOCK_'+adjustment.upper(),completed_symbols=offset,required_symbols=len(symbols),bar_records=total)
            counts[adjustment]=total
        for adjustment in ('raw','all'):
            total=0
            for page in client.pages(BARS,{'symbols':'BIL,SPY','timeframe':'1Day','start':lo,'end':hi,
                'adjustment':adjustment,'feed':'sip','asof':protocol['data_end'],'sort':'asc','limit':10000},'bars',3):
                total+=sum(len(v) for v in page.values())
            counts['benchmarks_'+adjustment]=total
        result.update(status='COMPLETE',selected_count=len(selected),excluded_count=len(excluded),
                      stock_and_benchmark_bar_counts=counts,action_records=count,pagination_complete=True)
    except Exception as exc:
        result['failure']=str(exc) if isinstance(exc,ValueError) else type(exc).__name__
        raise
    finally:
        result.update(requests=len(client.receipts),raw_bytes=client.raw_total,gzip_bytes=client.compressed_total,
                      seconds=time.monotonic()-client.started,completed_at=datetime.now(timezone.utc).isoformat())
        write(root/'capture.json',result)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','collect'])
    for n in ('protocol','output'):p.add_argument('--'+n,required=True)
    p.add_argument('--state');p.add_argument('--roster');p.add_argument('--stream',action='store_true');a=p.parse_args()
    STREAM=a.stream
    if STREAM:
        if a.mode!='collect':raise SystemExit('REFUSED_STREAM_MODE')
        sys.stdout.buffer.write(b'ALPCAP01');sys.stdout.buffer.flush()
    try:
        if a.mode=='prepare':prepare(a.state,a.protocol,a.output)
        else:collect(a.roster,a.protocol,a.output)
        if STREAM:emit({'kind':'END','status':'COMPLETE'})
        else:print(json.dumps({'status':'COMPLETE','mode':a.mode}))
    except Exception as exc:
        failure={'status':'FAILED','reason':str(exc) if isinstance(exc,ValueError) else type(exc).__name__}
        if STREAM:emit({'kind':'END',**failure})
        else:print(json.dumps(failure))
        raise SystemExit(1) from None
