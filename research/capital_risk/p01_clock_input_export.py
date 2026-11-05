"""Retain stopped input qualification separately, then stopped financial evidence."""
import ast
import json
import os
from pathlib import Path
import re

from full_system_benchmark import need
from seal import sha256_file
from system_campaign_parallel_discovery import compile_body
from system_campaign_pxd_financial_body import function
import system_campaign_evidence_export as original
import system_campaign_p01_discovery_export as marker_source

STAGE='campaign-p01-economic-clock-financial'
QUALIFICATION_STAGE='campaign-p01-economic-clock-input-qualification'
PUBLIC=frozenset(('schema','arm','stage','run_id','head','request_sha256','protocol_sha256',
    'strict_parent_outer_sha256','status','production_contacted','qualification_worker','worker','reviewer',
    'qualification_encrypted_output','encrypted_output','encrypted_output_exported','export_error',
    'export_qualification_sha256','qualification_exported','review_stop_unknown'))
STOP={'stopped','exit_code','oom_killed','wait_error'}
ASSET={'name','bytes','sha256','manifest_sha256','compression'}


def sealed(root,target,key,request,*,stage=STAGE):
    need(stage in (STAGE,QUALIFICATION_STAGE),'P01_CLOCK_INPUT_DECLARED_EXPORT_SCOPE')
    call=function('system_campaign_evidence_export.py','seal',{
        'campaign-factual-suffix':stage,'P02':'P01',
        'RETAINED_EXPORT_EXACT_P02_RESEARCH_SCOPE':'P01_CLOCK_INPUT_EXACT_EXPORT_SCOPE'},vars(original))
    return call(root,target,key,request,'P01',stage=stage,
        protocol_sha256=json.loads(request.read_bytes())['protocol_sha256'])


def qualify_export(path,request):
    fn,=[n for n in ast.parse(Path(marker_source.__file__).read_bytes()).body
          if isinstance(n,ast.FunctionDef) and n.name=='qualify_export']
    return compile_body(fn,dict(vars(marker_source),STAGE=STAGE,sealed=sealed,__file__=__file__))(path,request)


def write_receipt(path,r):
    need(set(r)<=PUBLIC and r['arm']=='P01' and r['stage']==STAGE and r['production_contacted'] is False,
         'P01_CLOCK_INPUT_PUBLIC_ALLOWLIST')
    nested={'qualification_worker','worker','reviewer','qualification_encrypted_output','encrypted_output','export_error'}
    need(all(type(v) in (str,int,bool,type(None)) for k,v in r.items() if k not in nested),
         'P01_CLOCK_INPUT_PUBLIC_METADATA_ONLY')
    for name in ('qualification_worker','worker','reviewer'):
        if name in r:
            value=r[name]
            need(set(value)==STOP and value['stopped'] is True and type(value['exit_code']) is int
                 and type(value['oom_killed']) is bool and type(value['wait_error']) in (str,type(None)),
                 'P01_CLOCK_INPUT_PUBLIC_EXACT_STOP')
    for name in ('qualification_encrypted_output','encrypted_output'):
        if name in r:need(set(r[name])==ASSET,'P01_CLOCK_INPUT_PUBLIC_EXACT_ASSET')
    if 'export_error' in r:need(set(r['export_error'])=={'type','code'},'P01_CLOCK_INPUT_PUBLIC_ERROR_CODE_ONLY')
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);pending=path.with_suffix('.partial')
    with pending.open('w',encoding='utf8',newline='\n') as stream:
        stream.write(json.dumps(r,sort_keys=True,indent=2)+'\n');stream.flush();os.fsync(stream.fileno())
    os.replace(pending,path)


def preserve_qualification(receipt,root,path,key,request):
    s=receipt['qualification_worker']
    need(s['stopped'] is True and s['exit_code']==0 and not s['oom_killed'],
         'P01_CLOCK_INPUT_ONLY_KNOWN_SUCCESSFUL_QUALIFICATION_EXPORT')
    allowed={'spec.json','request.json','source-bindings.json'}|{
        'qualification/'+name for name in ('clock-input.json','zero-session-startup-proof.json',
            'prefix-and-tail-proof.json','actual-codec-component-path.json.gz',
            'qualification-input-checkpoint.json','qualification-summary.json','worker-inspect.json','worker.log')}
    files=[p for p in root.rglob('*') if p.is_file()]
    need({p.relative_to(root).as_posix() for p in files}==allowed
         and not any(p.is_symlink() for p in root.rglob('*'))
         and sum(p.stat().st_size for p in files)<=64*1024**2,
         'P01_CLOCK_INPUT_ONLY_QUALIFICATION_PROOFS_NO_DISPOSABLE_FINANCIAL_BOOK_EXPORT')
    wrapped=json.loads((root/'qualification/qualification-input-checkpoint.json').read_bytes())
    need(wrapped['financial_authority'] is False and wrapped['financial_predecessor_authorized'] is False,
         'P01_CLOCK_INPUT_QUALIFICATION_WRAPPER_NEVER_FINANCIAL_AUTHORITY')
    receipt['qualification_encrypted_output']=sealed(root,path.parent/'p01-clock-input-qualification.tar.crseal',
        key,request,stage=QUALIFICATION_STAGE)
    receipt['qualification_exported']=True;write_receipt(path,receipt)


def finish(receipt,root,path,key,request,*,known):
    receipt['encrypted_output_exported']=False;write_receipt(path,receipt)
    if known:
        try:
            receipt['encrypted_output']=sealed(root,path.parent/'p01-clock-input-financial.tar.crseal',key,request)
            receipt['encrypted_output_exported']=True
        except Exception as error:
            code=str(error);receipt['export_error']=dict(type=type(error).__name__,
                code=code if re.fullmatch('REFUSED_[A-Z0-9_]+',code) else 'EXPORT_OPERATION_FAILED')
            receipt['status']='KNOWN_STOP_EXPORT_FAILED_NO_PLAINTEXT_FALLBACK'
    write_receipt(path,receipt)
