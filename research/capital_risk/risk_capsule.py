"""Lossless audit transport: omit/rebuild only redundant event-history lists."""
from pathlib import Path
from copy import deepcopy
import gzip,hashlib,json,shutil

def need(v,c):
    if not v:raise ValueError(c)
def encode(v):return json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(v):return hashlib.sha256(encode(v)).hexdigest()
def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def records(path):
    with gzip.open(path,'rb') as f:
        for line in f:
            need(line.endswith(b'\n'),'CAPSULE_COMPLETE_LINE');yield json.loads(line)

def compact_event(observation,history):
    expected=history+[observation['record']['event']['event_id']]
    need(observation['record']['state_without_chain']['applied_events']==expected,'CAPSULE_ORIGINAL_EVENT_HISTORY')
    value=deepcopy(observation);del value['record']['state_without_chain']['applied_events']
    return dict(observation=value,history_records=len(expected),history_sha256=digest(expected),original_raw_sha256=hashlib.sha256(encode(observation)+b'\n').hexdigest()),expected

def expand_event(capsule,history):
    value=deepcopy(capsule['observation']);identifier=value['record']['event']['event_id'];need(identifier not in history,'CAPSULE_DUPLICATE_EVENT')
    expected=history+[identifier];need(capsule['history_records']==len(expected) and capsule['history_sha256']==digest(expected),'CAPSULE_EVENT_HISTORY_COMMITMENT')
    need('applied_events' not in value['record']['state_without_chain'],'CAPSULE_UNEXPECTED_INLINE_HISTORY');value['record']['state_without_chain']['applied_events']=expected
    need(hashlib.sha256(encode(value)+b'\n').hexdigest()==capsule['original_raw_sha256'],'CAPSULE_ORIGINAL_EVENT_BYTES')
    return value,expected

def compact_checkpoint(cp,history,path,original_gzip_sha256):
    value=deepcopy(cp);actual=value['runtime']['account']['state'].pop('applied_events');n=len(actual)
    need(actual==history[:n],'CAPSULE_ORIGINAL_CHECKPOINT_HISTORY')
    return dict(path=path,checkpoint=value,history_records=n,history_sha256=digest(actual),original_gzip_sha256=original_gzip_sha256,
        original_raw_sha256=hashlib.sha256(encode(cp)+b'\n').hexdigest())

def expand_checkpoint(capsule,history):
    value=deepcopy(capsule['checkpoint']);n=capsule['history_records'];need(0<=n<=len(history) and digest(history[:n])==capsule['history_sha256'],'CAPSULE_CHECKPOINT_HISTORY_COMMITMENT')
    state=value['runtime']['account']['state'];need('applied_events' not in state,'CAPSULE_CHECKPOINT_INLINE_HISTORY');state['applied_events']=history[:n]
    need(digest(state)==value['runtime']['account']['state_sha256'] and hashlib.sha256(encode(value)+b'\n').hexdigest()==capsule['original_raw_sha256'],'CAPSULE_ORIGINAL_CHECKPOINT_BYTES')
    return value

def pack_book(source,destination,*,history_base=()):
    source=Path(source);destination=Path(destination);destination.mkdir(parents=True,exist_ok=False);history=list(history_base)
    current=None
    with gzip.open(destination/'events.compact.jsonl.gz','wb',compresslevel=6) as out,gzip.open(source/'events.jsonl.gz','rb') as incoming:
        for raw in incoming:
            value=json.loads(raw);need(encode(value)+b'\n'==raw,'CAPSULE_CANONICAL_ORIGINAL_RECORD')
            compact,history=compact_event(value,history);out.write(encode(compact)+b'\n')
    paths=[source/'checkpoint.json.gz']
    if (source/'restart-boundary.json.gz').exists():paths.append(source/'restart-boundary.json.gz')
    paths+=sorted((source/'month-end').glob('*.json.gz'))+sorted((source/'pre-event').glob('*.json.gz'))
    mapping={}
    with gzip.open(destination/'checkpoints.compact.jsonl.gz','wb',compresslevel=6) as out:
        for path in paths:
            with gzip.open(path,'rb') as f:raw=f.read()
            cp=json.loads(raw);need(encode(cp)+b'\n'==raw,'CAPSULE_CANONICAL_ORIGINAL_CHECKPOINT');name=path.relative_to(source).as_posix()
            item=compact_checkpoint(cp,history,name,sha(path));mapping[name]=item['original_gzip_sha256'];out.write(encode(item)+b'\n')
            if name=='checkpoint.json.gz':current=cp
    for name in ('daily.jsonl.gz','formation.jsonl.gz','checkpoint.json.gz','restart-boundary.json.gz','book-summary.json','retained-checkpoint-review.json'):
        if (source/name).exists():shutil.copyfile(source/name,destination/name)
    metadata=dict(schema='research.lossless-risk-audit-book/1',history_base=list(history_base),history_base_sha256=digest(list(history_base)),
        checkpoint_files=mapping,original_journals=current['journals'],original_final_account_sha256=current['runtime']['account']['state_sha256'])
    (destination/'capsule-book.json').write_bytes(encode(metadata)+b'\n');return metadata

def event_rows(root):
    root=Path(root);metadata=json.loads((root/'capsule-book.json').read_bytes());history=metadata['history_base']
    need(digest(history)==metadata['history_base_sha256'],'CAPSULE_BOUNDARY_HISTORY')
    for item in records(root/'events.compact.jsonl.gz'):
        value,history=expand_event(item,history);yield value

def verify_book(root):
    root=Path(root);metadata=json.loads((root/'capsule-book.json').read_bytes());history=list(metadata['history_base'])
    need(digest(history)==metadata['history_base_sha256'],'CAPSULE_BASE_HISTORY_HASH')
    for item in records(root/'events.compact.jsonl.gz'):_value,history=expand_event(item,history)
    specs={n:{} for n in ('events','daily','formation')};seen={};current=None;base=len(metadata['history_base'])
    for item in records(root/'checkpoints.compact.jsonl.gz'):
        path=item['path'];need(path in metadata['checkpoint_files'] and path not in seen and metadata['checkpoint_files'][path]==item['original_gzip_sha256'],'CAPSULE_ALL_ORIGINAL_CHECKPOINT_FILES')
        cp=expand_checkpoint(item,history);need(cp['runtime']['event_count']==item['history_records'] and cp['journals']['events']['records']==item['history_records']-base,'CAPSULE_ACCOUNT_EVENT_PREFIX_AXIS')
        seen[path]=True
        for name in specs:
            s=cp['journals'][name];n=s['records'];need(n not in specs[name] or specs[name][n]==s,'CAPSULE_CONSISTENT_CHECKPOINT_PREFIX');specs[name][n]=s
        if path=='checkpoint.json.gz':current=cp
    need(set(seen)==set(metadata['checkpoint_files']) and current is not None,'CAPSULE_EVERY_ORIGINAL_CHECKPOINT_PRESENT')
    proof={}
    for name,wanted in specs.items():
        h=hashlib.sha256();size=count=0;found=set()
        def check():
            if count in wanted:need(wanted[count]==dict(bytes=size,records=count,prefix_sha256=h.hexdigest()),'CAPSULE_ORIGINAL_JOURNAL_PREFIX');found.add(count)
        check()
        if name=='events':stream=(encode(v)+b'\n' for v in event_rows(root))
        else:stream=gzip.open(root/(name+'.jsonl.gz'),'rb')
        try:
            for raw in stream:need(raw.endswith(b'\n'),'CAPSULE_NO_PARTIAL_LINE');h.update(raw);size+=len(raw);count+=1;check()
        finally:
            if hasattr(stream,'close'):stream.close()
        need(found==set(wanted),'CAPSULE_ALL_HISTORICAL_PREFIXES');spec=metadata['original_journals'][name]
        need(spec==dict(bytes=size,records=count,prefix_sha256=h.hexdigest()),'CAPSULE_ZERO_ORIGINAL_TAILS')
        proof[name]=dict(bytes=size,records=count,sha256=h.hexdigest(),tail_bytes=0,tail_records=0)
    need(current['runtime']['account']['state_sha256']==metadata['original_final_account_sha256'],'CAPSULE_FINAL_ACCOUNT_IDENTITY')
    return dict(checkpoints=len(seen),journals=proof),current
