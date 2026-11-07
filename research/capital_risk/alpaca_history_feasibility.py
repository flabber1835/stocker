"""Four market-data-only coverage requests; no financial runtime imports."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import time

from alpaca_fit_collect import Client,BARS,ACTIONS


def run(output):
    root=Path(output);root.mkdir(parents=True,exist_ok=False);client=Client(root);started=time.monotonic();results=[]
    symbols='AAPL,IBM,SPY,BIL'
    base={'symbols':symbols,'timeframe':'1Day','start':'2016-01-04T00:00:00-05:00','end':'2016-01-08T23:59:59-05:00',
        'feed':'sip','asof':'2026-10-27','sort':'asc','limit':1000}
    queries=[(BARS,{**base,'adjustment':value}) for value in ('raw','split')]
    queries.extend((ACTIONS,{'symbols':symbols,'start':start,'end':end,'limit':1000,'data_quality':'all','sort':'asc'})
        for start,end in [('2015-01-01','2016-12-31'),('2020-01-01','2020-12-31')])
    try:
        for endpoint,params in queries:
            if len(client.receipts)>=4 or time.monotonic()-started>150:raise ValueError('REFUSED_COVERAGE_REQUEST_BOUND')
            if endpoint not in {BARS,ACTIONS}:raise ValueError('REFUSED_NON_MARKET_COVERAGE_ENDPOINT')
            reply=client.call(endpoint,params);key='bars' if endpoint==BARS else 'corporate_actions';rows=reply.get(key)
            if not isinstance(rows,dict):raise ValueError('REFUSED_COVERAGE_RESPONSE_SHAPE')
            results.append({'endpoint':endpoint,'params':params,'counts':{k:len(v) for k,v in rows.items()},
                'next_page_token_present':reply.get('next_page_token') is not None,
                'response_file':client.receipts[-1]['file'],'response_sha256':client.receipts[-1]['raw_sha256']})
        status='BOUNDED_COVERAGE_OBSERVED'
    except Exception as exc:
        status='INCOMPLETE';results.append({'error_type':type(exc).__name__,'reason':str(exc) if isinstance(exc,ValueError) else None})
    finally:client.keys.clear()
    result={'schema':'research.alpaca-history-feasibility/1','status':status,'results':results,'requests':len(client.receipts),
        'seconds':time.monotonic()-started,'completed_at':datetime.now(timezone.utc).isoformat(),
        'provider':'ALPACA','account_order_position_activity_calls':0,'financial_runtime_executed':False,'production_modified':False,
        'full_history_or_identity_qualification':False,'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (root/'coverage.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':status,'requests':result['requests'],'results':results,'financial_runtime_executed':False}))
    return 0 if status=='BOUNDED_COVERAGE_OBSERVED' else 2


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);raise SystemExit(run(p.parse_args().output))
