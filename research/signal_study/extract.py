"""Recover dated append-only observations from matching retained checkpoints."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from sentinel.feed.rolling_contract import digest
from research.exposure_oracle import inputs
from .guard import CoreGuard


def prefixes(blob):
    result={}; hasher=hashlib.sha256(); size=0
    for line in blob.splitlines(keepends=True):
        hasher.update(line); size+=len(line)
        result[json.loads(line)['session']]=dict(bytes=size,sha256=hasher.hexdigest())
    return result


def validate(blob,filename,rows_by_date,expected_prefix):
    if filename!='checkpoint-'+inputs.sha(blob)+'.json.gz':
        raise ValueError('checkpoint filename/content hash mismatch')
    packet=json.loads(gzip.decompress(blob)); cursor=packet['cursor']
    if cursor not in rows_by_date: return packet,'outside_retained_period'
    if packet['state_sha256']!=rows_by_date[cursor]['state_sha256']:
        return packet,'different_canonical_state'
    if packet['outputs'].get('daily.jsonl')!=expected_prefix[cursor]:
        return packet,'different_daily_prefix'
    state=packet['state']
    if digest(state)!=packet['state_sha256']:
        raise ValueError('checkpoint serialized state hash mismatch')
    if state['last_processed_session']!=cursor or state['last_evidence']['observation']['session']!=cursor:
        raise ValueError('checkpoint observation date mismatch')
    return packet,'eligible'


def put(table,date,key,value,source):
    if value is None: return
    value=float(value)
    if not math.isfinite(value): raise ValueError('nonfinite retained observation')
    cell=table[date]['values']; origins=table[date]['origins']
    if key in cell and not math.isclose(cell[key],value,rel_tol=1e-12,abs_tol=1e-12):
        raise ValueError('conflicting historical observations: '+date+' '+key)
    cell[key]=value
    if key not in origins or source['preserved_through']<origins[key]['preserved_through']:
        origins[key]=source


def recover(packet,filename,rows,table):
    dates=[r['session'] for r in rows]; index={d:i for i,d in enumerate(dates)}
    state=packet['state']; cursor=packet['cursor']; i=index[cursor]
    evidence=state['last_evidence']; observation=evidence['observation']
    source=dict(checkpoint=filename,preserved_through=cursor)
    core=state['shadow_nav_history']
    if not 1<=len(core)<=41: raise ValueError('unexpected Core observation window')
    for offset,value in enumerate(core):
        j=i-len(core)+1+offset
        if j>=0 and not math.isclose(float(rows[j]['core']['nav']),float(value),rel_tol=1e-12,abs_tol=1e-8):
            raise ValueError('stored history is not aligned with retained Core closes')
    for key,value in observation.items():
        if key not in ('session','shadow_nav'):
            put(table,cursor,'recorded_'+key,value,source)
    for key,value in evidence.get('recent_leadership',{}).items():
        put(table,cursor,'recorded_'+key,value,source)
    witness=state['median5']['witness_nav']
    if not 1<=len(witness)<=41: raise ValueError('unexpected leadership observation window')
    for offset,value in enumerate(witness):
        j=i-len(witness)+1+offset
        if j>=0: put(table,dates[j],'leadership_nav',value,source)
    damage=state['breadth_history']
    if len(damage)>6: raise ValueError('unexpected damage observation window')
    for offset,value in enumerate(damage):
        j=i-len(damage)+1+offset
        if j>=0: put(table,dates[j],'recorded_damaged_breadth',value,source)
    window=state['controller_session_history']
    expected=[d for d in dates[max(0,i-19):i+1]]
    retained=[d for d in window if d in index]
    if retained!=expected: raise ValueError('stop window date alignment changed')
    stops=Counter(state['trailing_stop_sessions'])
    if any(d not in window for d in stops): raise ValueError('stop outside declared window')
    for d in retained: put(table,d,'recorded_stops_today',stops[d],source)
    held=evidence['breadth']['holdings']
    if held:
        for field in ('own_dd','r21','r63','age_sessions'):
            vals=[float(h[field]) for h in held if h[field] is not None]
            if len(vals)==len(held):
                put(table,cursor,'holdings_median_'+field,float(np.median(vals)),source)
                put(table,cursor,'holdings_dispersion_'+field,float(np.std(vals)),source)


def run(snapshot: Path,archive: Path,output: Path):
    snapshot,archive,output=snapshot.resolve(),archive.resolve(),output.resolve()
    if any(output==p or output in p.parents or p in output.parents for p in (snapshot,archive)):
        raise ValueError('observation output must be separate from protected inputs')
    output.mkdir(parents=True,exist_ok=False)
    _,rows=inputs.load(snapshot)
    by_date={r['session']:r for r in rows}; pref=prefixes((snapshot/'daily.jsonl').read_bytes())
    table={d:dict(session=d,values={},origins={}) for d in by_date}
    files=sorted(archive.glob('**/checkpoint-*.json.gz'))
    if not files: raise ValueError('no retained checkpoint files found')
    inventory=[]; seen=set()
    for n,path in enumerate(files):
        blob=path.read_bytes(); sha=inputs.sha(blob)
        if sha in seen:
            inventory.append(dict(path=str(path.relative_to(archive)),sha256=sha,status='duplicate_bytes'))
            continue
        seen.add(sha)
        packet,status=validate(blob,path.name,by_date,pref)
        record=dict(path=str(path.relative_to(archive)),sha256=sha,status=status,
                    cursor=packet['cursor'],source_binding=packet['binding'])
        inventory.append(record)
        if status=='eligible': recover(packet,path.name,rows,table)
        if (n+1)%40==0: print(json.dumps(dict(status='EXTRACTING',examined=n+1,total=len(files))),flush=True)
    values=list(table.values())
    keys=sorted({k for row in values for k in row['values']})
    coverage={k:sum(k in row['values'] for row in values) for k in keys}
    summary=dict(schema='sentinel-retained-observations/1',source_manifest=json.loads((snapshot/'manifest.json').read_text()),
        extraction_source_sha256=inputs.sha(Path(__file__).read_bytes()),files=len(files),
        statuses=dict(Counter(r['status'] for r in inventory)),coverage=coverage,
        caveat='Only exact matching state/prefix histories; preserved dates are not feature dates; missing remains unavailable.')
    with (output/'observations.jsonl').open('w',encoding='utf8') as stream:
        for row in values: stream.write(json.dumps(row,sort_keys=True,allow_nan=False)+'\n')
    summary['observations_sha256']=inputs.sha((output/'observations.jsonl').read_bytes())
    inputs.write_json(output/'summary.json',summary)
    inputs.write_json(output/'checkpoints.json',inventory)
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',type=Path,required=True)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    with CoreGuard() as guard:
        result=run(args.snapshot,args.archive,args.output)
    inputs.write_json(args.output/'core-preservation.json',guard.receipt())
    print(json.dumps(result,indent=2),flush=True)
