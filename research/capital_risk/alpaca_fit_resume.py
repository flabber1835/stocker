"""Exact market-price suffix; the failed encrypted prefix stays failed."""
import argparse
from datetime import datetime,timedelta
import hashlib
import json
from pathlib import Path
import ssl
import sys
import time
from zoneinfo import ZoneInfo
import alpaca_fit_collect as capture


def price_plan(protocol,symbols):
    ny=ZoneInfo('America/New_York')
    lo=datetime.fromisoformat(protocol['data_start']+'T00:00:00').replace(tzinfo=ny).isoformat()
    hi=(datetime.fromisoformat(protocol['data_end']+'T00:00:00').replace(tzinfo=ny)+timedelta(days=1)-timedelta(microseconds=1)).isoformat()
    base={'timeframe':'1Day','start':lo,'end':hi,'feed':'sip','asof':protocol['data_end'],'sort':'asc','limit':10000}
    plan=[];symbols=sorted(symbols)
    for adjustment in ('raw','split'):
        for offset in range(0,len(symbols),400):plan.append({**base,'symbols':','.join(symbols[offset:offset+400]),'adjustment':adjustment})
    for adjustment in ('raw','all'):plan.append({**base,'symbols':'BIL,SPY','adjustment':adjustment})
    return plan


def without_token(params):return {k:v for k,v in params.items() if k!='page_token'}


class Client(capture.Client):
    def __init__(self,root,prefix):
        super().__init__(root);self.prefix_count=prefix['requests'];self.raw_total=prefix['raw_bytes'];self.compressed_total=prefix['gzip_bytes']
    def call(self,*args,**kwargs):
        if time.monotonic()-self.started>900:raise ValueError('REFUSED_PRICE_SUFFIX_TIME_BOUND')
        if self.prefix_count+len(self.receipts)>=2400:raise ValueError('REFUSED_COMBINED_REQUEST_COUNT')
        for attempt in range(3):
            try:return super().call(*args,**kwargs)
            except ssl.SSLError:
                if attempt==2:raise ValueError('REFUSED_BOUNDED_TLS_RETRIES') from None
                time.sleep(3*(attempt+1))


def run(args):
    capture.STREAM=True;sys.stdout.buffer.write(b'ALPCAP01');sys.stdout.buffer.flush()
    root=Path(args.output);root.mkdir(parents=True,exist_ok=False)
    old=Path(args.predecessor);transport=json.loads(Path(args.transport).read_bytes())
    prefix=json.loads((old/'capture.json').read_bytes());proofs=[json.loads(line) for line in (old/'request-receipts.jsonl').read_bytes().splitlines()]
    protocol=json.loads(Path(args.protocol).read_bytes());classified=json.loads((old/'classification.json').read_bytes())
    if (prefix['status']!='INCOMPLETE' or prefix.get('failure')!='SSLError' or transport['status']!='FAILED'
        or transport['collector_exit_code']!=1 or transport['protocol_sha256']!=capture.digest(Path(args.protocol).read_bytes())
        or len(proofs)!=prefix['requests']):raise ValueError('REFUSED_EXACT_FAILED_PREFIX')
    plan=price_plan(protocol,[r['ticker'] for r in classified['selected']]);last=proofs[-1]
    group=without_token(last['params'])
    if last['endpoint']!=capture.BARS or group not in plan:raise ValueError('REFUSED_PRICE_SUFFIX_BOUNDARY')
    ordinal=plan.index(group);client=Client(root,prefix);first=True;original_emit=capture.emit
    comparison=json.loads(Path(args.comparison).read_bytes()) if args.comparison else None
    def emit(meta,payload=b''):
        nonlocal first
        if comparison is None and first and meta['kind']=='PROVIDER':meta['receipt']['purpose']='EXACT_PREDECESSOR_CORROBORATION';first=False
        return original_emit(meta,payload)
    capture.emit=emit
    result={'schema':'research.alpaca-fit-price-suffix/1','status':'INCOMPLETE','standalone_full_input':False,
        'predecessor_manifest_sha256':transport['manifest_sha256'],'predecessor_ciphertext_sha256':transport['ciphertext_sha256'],
        'predecessor_receipts_sha256':capture.digest((old/'request-receipts.jsonl').read_bytes()),
        'protocol_sha256':capture.digest(Path(args.protocol).read_bytes()),'production_contacted':False,
        'account_order_position_activity_calls':0,'query_plan_sha256':capture.digest(capture.canonical(plan))}
    try:
        capture.write(root/'predecessor.json',{'transport':transport,'capture':prefix,'last_receipt':last})
        if comparison is None:
            reply=client.call(capture.BARS,last['params']);observed=client.receipts[-1]
            if any(observed[k]!=last[k] for k in ('raw_bytes','raw_sha256','params','endpoint')):raise ValueError('REFUSED_CHANGED_PREDECESSOR_PAGE')
            capture.write(root/'corroboration.json',{'status':'BYTE_EXACT_PREDECESSOR','original':last,'observed':observed,
                'next_page_token':reply.get('next_page_token')})
            token=reply.get('next_page_token')
        else:
            if (comparison['old_manifest_sha256']!=transport['manifest_sha256'] or comparison['old_raw_sha256']!=last['raw_sha256']
                or comparison['parsed_json_values_and_array_order_equal'] is not True or comparison['same_query'] is not True
                or comparison['both_complete_ciphertexts_authenticated_before_parsing'] is not True
                or comparison['both_full_inventories_verified'] is not True
                or comparison['corroboration_receipt']['params']!=last['params']):raise ValueError('REFUSED_QUALIFIED_JSON_PREDECESSOR')
            capture.write(root/'corroboration.json',{'status':'JSON_VALUE_EXACT_PREDECESSOR','review':comparison})
            result['corroboration_manifest_sha256']=comparison['new_manifest_sha256']
            token=comparison['corroborated_next_page_token']
        seen=set()
        while token is not None:
            if token in seen or len(seen)>=65:raise ValueError('REFUSED_SUFFIX_PAGINATION')
            seen.add(token);reply=client.call(capture.BARS,{**group,'page_token':token});token=reply.get('next_page_token')
            client.progress('PRICE_SUFFIX',completed_groups=ordinal,required_groups=len(plan))
        for i,query in enumerate(plan[ordinal+1:],ordinal+1):
            for page in client.pages(capture.BARS,query,'bars',65):client.progress('PRICE_SUFFIX',completed_groups=i,required_groups=len(plan))
        result.update(status='COMPLETE',pagination_complete=True,remaining_query_plan_complete=True,
            completed_query_groups=len(plan),last_prefix_query_ordinal=ordinal)
    except Exception as exc:result['failure']=str(exc) if isinstance(exc,ValueError) else type(exc).__name__
    result.update(requests=len(client.receipts),combined_request_count=prefix['requests']+len(client.receipts),
        raw_bytes=client.raw_total,gzip_bytes=client.compressed_total,seconds=time.monotonic()-client.started)
    capture.write(root/'capture.json',result);capture.emit({'kind':'END','status':result['status']})
    return 0 if result['status']=='COMPLETE' else 1


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for n in ('protocol','predecessor','transport','output'):p.add_argument('--'+n,required=True)
    p.add_argument('--comparison')
    raise SystemExit(run(p.parse_args()))
