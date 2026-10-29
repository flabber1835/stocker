"""Complete long market capture; no trading catalog or financial endpoints."""
import argparse
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import sys
import time
from zoneinfo import ZoneInfo

import alpaca_fit_collect as base
from alpaca_fit_collect import Client,ACTIONS,BARS,canonical,digest,write,emit


def need(value,reason):
    if not value:raise ValueError('REFUSED_LONG_CAPTURE_'+reason)


def validate(protocol,roster,classification,protocol_raw,classification_raw):
    need(protocol['schema']=='research.bounded-alpaca-policy-fit/2'
        and protocol['study_id']=='alpaca-owned55-long-fit-001'
        and protocol['source_capture_scope']=='LONG_HISTORY','PROTOCOL_SCOPE')
    need((protocol['capture_max_seconds'],protocol['capture_max_requests'],protocol['capture_max_raw_bytes'],
        protocol['capture_max_gzip_bytes'])==base.CAPTURE_BOUNDS['LONG_HISTORY'],'FROZEN_BOUNDS')
    need(roster['protocol_sha256']==digest(protocol_raw)
        and roster['parent_classification_sha256']==digest(classification_raw),'INPUT_BINDINGS')
    expected={r['asset_id']:r['ticker'] for r in roster['roster']}
    selected=classification['selected']
    need(len(expected)==len(roster['roster']) and len(selected)==len({r['asset_id'] for r in selected})
        and len(selected)==len({r['ticker'] for r in selected})
        and all(expected.get(r['asset_id'])==r['ticker'] for r in selected),'CLASSIFICATION_MEMBERSHIP')
    need(len(selected)>=200 and not ({'SPY','BIL'}&{r['ticker'] for r in selected}),'STOCK_SCOPE')
    return sorted(r['ticker'] for r in selected)


def collect(args):
    root=Path(args.output);root.mkdir(parents=True,exist_ok=False)
    rr,pr,cr=(Path(v).read_bytes() for v in (args.roster,args.protocol,args.classification))
    roster,protocol,classification=map(json.loads,(rr,pr,cr))
    symbols=validate(protocol,roster,classification,pr,cr)
    client=Client(root,scope='LONG_HISTORY')
    result={'schema':'research.alpaca-long-market-capture/1','status':'INCOMPLETE','roster_sha256':digest(rr),
        'protocol_sha256':digest(pr),'classification_sha256':digest(cr),'production_contacted':False,
        'account_order_position_activity_calls':0,'trading_catalog_calls':0,'providers':['ALPACA','OPENFIGI_FREE'],
        'classification_reused_byte_exact':True,'current_cohort_survivor_conditioned':True}
    counts={};action_count=0
    try:
        with (root/'classification.json').open('xb') as f:f.write(cr)
        if base.STREAM:emit({'kind':'FILE','name':'classification.json'},cr)
        client.progress('ACTIONS')
        for page in client.pages(ACTIONS,{'start':protocol['corporate_action_process_start'],
            'end':protocol['corporate_action_process_end'],'limit':1000,'data_quality':'all','sort':'asc'},'corporate_actions',300):
            action_count+=sum(len(rows) for rows in page.values());client.progress('ACTIONS',action_records=action_count)
        ny=ZoneInfo('America/New_York')
        lo=datetime.fromisoformat(protocol['data_start']+'T00:00:00').replace(tzinfo=ny).isoformat()
        hi=(datetime.fromisoformat(protocol['data_end']+'T00:00:00').replace(tzinfo=ny)+timedelta(days=1)-timedelta(microseconds=1)).isoformat()
        def bars(batch,adjustment,max_pages):
            query={'symbols':','.join(batch),'timeframe':'1Day','start':lo,'end':hi,'adjustment':adjustment,
                'feed':'sip','asof':protocol['data_end'],'sort':'asc','limit':10000}
            return client.pages(BARS,query,'bars',max_pages)
        for adjustment in protocol['stock_price_domains']:
            need(adjustment in ('raw','split','all'),'PRICE_DOMAIN');total=0
            for offset in range(0,len(symbols),200):
                for page in bars(symbols[offset:offset+200],adjustment,65):
                    total+=sum(len(rows) for rows in page.values())
                    client.progress('STOCK_'+adjustment.upper(),completed_symbols=offset,required_symbols=len(symbols),bar_records=total)
            counts[adjustment]=total
        for adjustment in ('raw','all'):
            total=0
            for page in bars(['BIL','SPY'],adjustment,5):total+=sum(len(rows) for rows in page.values())
            counts['benchmarks_'+adjustment]=total
        total=0
        for page in bars(['BIL'],'split',3):total+=sum(len(rows) for rows in page.values())
        counts['bil_split']=total
        result.update(status='COMPLETE',selected_count=len(symbols),stock_and_benchmark_bar_counts=counts,
            action_records=action_count,pagination_complete=True,
            corporate_action_financial_effect_cutoff=protocol['corporate_action_financial_effect_cutoff'],
            equity_all_domain_use=protocol['equity_all_domain_use'])
    except Exception as exc:
        result['failure']=str(exc) if isinstance(exc,ValueError) else type(exc).__name__
        raise
    finally:
        result.update(requests=len(client.receipts),raw_bytes=client.raw_total,gzip_bytes=client.compressed_total,
            seconds=time.monotonic()-client.started,completed_at=datetime.now(timezone.utc).isoformat())
        write(root/'capture.json',result)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('roster','protocol','classification','output'):p.add_argument('--'+name,required=True)
    p.add_argument('--stream',action='store_true');a=p.parse_args();base.STREAM=a.stream
    if a.stream:sys.stdout.buffer.write(b'ALPCAP01');sys.stdout.buffer.flush()
    try:
        collect(a)
        if a.stream:emit({'kind':'END','status':'COMPLETE'})
        else:print(json.dumps({'status':'COMPLETE'}))
    except Exception as exc:
        failure={'status':'FAILED','reason':str(exc) if isinstance(exc,ValueError) else type(exc).__name__}
        if a.stream:emit({'kind':'END',**failure})
        else:print(json.dumps(failure))
        raise SystemExit(1) from None
