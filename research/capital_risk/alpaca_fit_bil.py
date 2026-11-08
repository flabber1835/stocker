"""Small market-only BIL split corroboration supplement; no strategy imports."""
import argparse
from datetime import datetime,timedelta
from pathlib import Path
import json
import sys
from zoneinfo import ZoneInfo
import alpaca_fit_collect as capture


def run(args):
    capture.STREAM=True;sys.stdout.buffer.write(b'ALPCAP01');sys.stdout.buffer.flush()
    root=Path(args.output);root.mkdir(parents=True,exist_ok=False)
    protocol=json.loads(Path(args.protocol).read_bytes());client=capture.Client(root)
    result={'schema':'research.alpaca-fit-bil-supplement/1','status':'INCOMPLETE',
            'production_contacted':False,'account_order_position_activity_calls':0,
            'protocol_sha256':capture.digest(Path(args.protocol).read_bytes())}
    try:
        ny=ZoneInfo('America/New_York')
        lo=datetime.fromisoformat(protocol['data_start']+'T00:00:00').replace(tzinfo=ny).isoformat()
        hi=(datetime.fromisoformat(protocol['data_end']+'T00:00:00').replace(tzinfo=ny)
            +timedelta(days=1)-timedelta(microseconds=1)).isoformat()
        rows=0
        for page in client.pages(capture.BARS,{'symbols':'BIL','timeframe':'1Day','start':lo,'end':hi,
                'adjustment':'split','feed':'sip','asof':protocol['data_end'],'sort':'asc','limit':10000},'bars',3):
            rows+=sum(len(v) for v in page.values())
        result.update(status='COMPLETE',bar_records=rows,pagination_complete=True)
    except Exception as exc:
        result['failure']=str(exc) if isinstance(exc,ValueError) else type(exc).__name__
    capture.write(root/'capture.json',result)
    capture.emit({'kind':'END','status':result['status']})
    return 0 if result['status']=='COMPLETE' else 1


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--protocol',required=True);p.add_argument('--output',required=True)
    raise SystemExit(run(p.parse_args()))
