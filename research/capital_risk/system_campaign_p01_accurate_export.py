"""P01 financial evidence encryption; allowlisted public metadata only."""
import json,os,re
from pathlib import Path
from full_system_benchmark import need
from seal import sha256_file
from system_campaign_pxd_financial_body import function
import system_campaign_evidence_export as original
import system_campaign_p01_discovery_export as probe_source

STAGE='campaign-p01-accurate-prefix'
PUBLIC=frozenset(('schema','arm','stage','run_id','head','request_sha256','protocol_sha256',
 'strict_parent_outer_sha256','strict_parent_run_id','status','production_contacted',
 'worker','reviewer','encrypted_output','encrypted_output_exported','export_error',
 'export_qualification_sha256','review_stop_unknown'))

def sealed(root,target,key,request):
    call=function('system_campaign_evidence_export.py','seal',{
        'campaign-factual-suffix':STAGE,'P02':'P01',
        'RETAINED_EXPORT_EXACT_P02_RESEARCH_SCOPE':'P01_ACCURATE_EXACT_EXPORT_SCOPE'},vars(original))
    return call(root,target,key,request,'P01',stage=STAGE,
                protocol_sha256=json.loads(request.read_bytes())['protocol_sha256'])

def qualify_export(path,request):
    # The actual original marker encrypt/authenticate/decrypt function, with
    # only its stage, sealing adapter and implementation identity rebound.
    import ast
    from system_campaign_parallel_discovery import compile_body
    fn,=[n for n in ast.parse(Path(probe_source.__file__).read_bytes()).body
         if isinstance(n,ast.FunctionDef) and n.name=='qualify_export']
    return compile_body(fn,dict(vars(probe_source),STAGE=STAGE,sealed=sealed,__file__=__file__))(path,request)

def write_receipt(path,receipt):
    need(set(receipt)<=PUBLIC and receipt['arm']=='P01' and receipt['stage']==STAGE
         and receipt['production_contacted'] is False,'P01_ACCURATE_PUBLIC_ALLOWLIST')
    nested={'worker','reviewer','encrypted_output','export_error'}
    need(all(type(v) in (str,int,bool,type(None)) for k,v in receipt.items() if k not in nested),
         'P01_ACCURATE_ONLY_PUBLIC_METADATA')
    for k in ('worker','reviewer'):
        if k in receipt:
            s=receipt[k]
            need(set(s)=={'stopped','exit_code','oom_killed','wait_error'}
                 and s['stopped'] is True and type(s['exit_code']) is int
                 and type(s['oom_killed']) is bool and type(s['wait_error']) in (str,type(None)),
                 'P01_ACCURATE_PUBLIC_STOP_METADATA')
    if 'encrypted_output' in receipt:
        need(set(receipt['encrypted_output'])=={'name','bytes','sha256','manifest_sha256','compression'},
             'P01_ACCURATE_PUBLIC_ENCRYPTED_ASSET_ONLY')
    if 'export_error' in receipt:need(set(receipt['export_error'])=={'type','code'},'P01_ACCURATE_PUBLIC_ERROR_ONLY')
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);temporary=path.with_suffix('.partial')
    with temporary.open('w',encoding='utf8',newline='\n') as f:
        f.write(json.dumps(receipt,sort_keys=True,indent=2)+'\n');f.flush();os.fsync(f.fileno())
    os.replace(temporary,path)

def finish(receipt,root,path,key,request,*,known):
    receipt['encrypted_output_exported']=False;write_receipt(path,receipt)
    if known:
        try:
            receipt['encrypted_output']=sealed(root,path.parent/'p01-accurate.tar.crseal',key,request)
            receipt['encrypted_output_exported']=True
        except Exception as error:
            code=str(error)
            receipt['export_error']=dict(type=type(error).__name__,
                code=code if re.fullmatch('REFUSED_[A-Z0-9_]+',code) else 'EXPORT_OPERATION_FAILED')
            receipt['status']='KNOWN_STOP_EXPORT_FAILED_NO_PLAINTEXT_FALLBACK'
    write_receipt(path,receipt)
