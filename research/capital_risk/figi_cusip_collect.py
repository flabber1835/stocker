"""Anonymous metadata-only CUSIP corroboration for temporal identity work."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import time
from alpaca_fit_collect import Client,FIGI,canonical,digest


def collect(spec_path,output):
    spec_raw=Path(spec_path).read_bytes();spec=json.loads(spec_raw)
    if (spec['schema']!='research.figi-cusip-query-set/1' or spec['batch_size']!=10
        or spec['max_requests']!=600 or spec['max_seconds']!=1800
        or spec['no_prices_holdings_or_outcomes_used'] is not True):raise ValueError('REFUSED_CUSIP_QUERY_SCOPE')
    cusips=spec['cusips']
    if not (0<len(cusips)<=6000 and cusips==sorted(set(cusips)) and all(re.fullmatch('[A-Z0-9]{9}',c) for c in cusips)):
        raise ValueError('REFUSED_CUSIP_QUERY_VALUES')
    root=Path(output);root.mkdir(parents=True,exist_ok=False);client=Client(root,keys={});started=time.monotonic();status='INCOMPLETE';results=[];failure=None
    try:
        for offset in range(0,len(cusips),10):
            if time.monotonic()-started>1800 or len(client.receipts)>=600:raise ValueError('REFUSED_CUSIP_COLLECTION_BOUND')
            batch=cusips[offset:offset+10];body=[{'idType':'ID_CUSIP','idValue':c,'exchCode':'US','marketSecDes':'Equity'} for c in batch]
            replies=client.call(FIGI,body=body)
            if not isinstance(replies,list) or len(replies)!=len(batch):raise ValueError('REFUSED_CUSIP_RESPONSE_COUNT')
            for cusip,reply in zip(batch,replies):
                if not isinstance(reply,dict):raise ValueError('REFUSED_CUSIP_RESPONSE_SHAPE')
                rows=reply.get('data');facts=[]
                if isinstance(rows,list):
                    facts=sorted({(r.get('compositeFIGI'),r.get('shareClassFIGI'),r.get('securityType'),r.get('securityType2'))
                        for r in rows if r.get('marketSector')=='Equity' and r.get('exchCode')=='US'
                        and all(isinstance(r.get(k),str) and r[k] for k in ('compositeFIGI','shareClassFIGI','securityType','securityType2'))})
                results.append({'cusip':cusip,'status':'UNIQUE_US_EQUITY_CLASS' if len(facts)==1 else 'UNMAPPED_OR_AMBIGUOUS',
                    'facts':[dict(zip(('composite_figi','share_class_figi','security_type','security_type2'),f)) for f in facts],
                    'response_file':client.receipts[-1]['file'],'raw_response_sha256':client.receipts[-1]['raw_sha256']})
        status='COMPLETE_CUSIP_METADATA_QUERY_SET'
    except Exception as exc:failure={'type':type(exc).__name__,'reason':str(exc) if isinstance(exc,ValueError) else None}
    result={'schema':'research.figi-cusip-metadata-capture/1','status':status,'query_spec_sha256':digest(spec_raw),
        'requested_cusips':len(cusips),'processed_cusips':len(results),'unique_us_classes':sum(r['status']=='UNIQUE_US_EQUITY_CLASS' for r in results),
        'requests':len(client.receipts),'failure':failure,'seconds':time.monotonic()-started,'results':results,
        'completed_at':datetime.now(timezone.utc).isoformat(),'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'authenticated_provider_keys_read':False,'financial_runtime_executed':False,'production_contacted':False}
    (root/'capture.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='results'}));return 0 if status=='COMPLETE_CUSIP_METADATA_QUERY_SET' else 2


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--spec',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();raise SystemExit(collect(a.spec,a.output))
