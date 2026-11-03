"""Bounded metadata-only lineage extension using the existing market loader."""
import argparse
from collections import Counter
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import time

from alpaca_fit_collect import Client,ACTIONS

TYPES='name_change,unit_split,cash_merger,stock_merger,stock_and_cash_merger,redemption,worthless_removal,spin_off'


def collect(output):
    root=Path(output);root.mkdir(parents=True,exist_ok=False);client=Client(root);started=time.monotonic();token=None;seen=set()
    counts=Counter();status='INCOMPLETE';failure=None
    try:
        for page in range(240):
            if time.monotonic()-started>600:raise ValueError('REFUSED_IDENTITY_COLLECTION_TIME_BOUND')
            params={'start':'2015-01-01','end':'2026-10-27','types':TYPES,'limit':1000,'data_quality':'all','sort':'asc'}
            if token is not None:params['page_token']=token
            reply=client.call(ACTIONS,params);events=reply.get('corporate_actions')
            if not isinstance(events,dict):raise ValueError('REFUSED_IDENTITY_ACTION_SHAPE')
            for kind,items in events.items():
                if not isinstance(items,list):raise ValueError('REFUSED_IDENTITY_ACTION_ARRAY')
                counts[kind]+=len(items)
            token=reply.get('next_page_token')
            if token is None:status='COMPLETE_METADATA_INTERVAL';break
            if not isinstance(token,str) or not token or token in seen:raise ValueError('REFUSED_IDENTITY_ACTION_CURSOR')
            seen.add(token)
        else:raise ValueError('REFUSED_IDENTITY_ACTION_PAGE_BOUND')
    except Exception as exc:failure={'type':type(exc).__name__,'reason':str(exc) if isinstance(exc,ValueError) else None}
    finally:client.keys.clear()
    result={'schema':'research.alpaca-temporal-identity-capture/1','status':status,'start':'2015-01-01','end':'2026-10-27',
        'types':TYPES.split(','),'counts':dict(counts),'requests':len(client.receipts),'pagination_complete':token is None and status=='COMPLETE_METADATA_INTERVAL',
        'failure':failure,'seconds':time.monotonic()-started,'completed_at':datetime.now(timezone.utc).isoformat(),
        'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'account_order_position_activity_calls':0,
        'financial_runtime_executed':False,'production_modified':False,'full_price_or_economic_qualification':False}
    (root/'capture.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result));return 0 if status=='COMPLETE_METADATA_INTERVAL' else 2


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);raise SystemExit(collect(p.parse_args().output))
