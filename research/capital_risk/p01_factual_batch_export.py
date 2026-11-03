"""Separate known-stopped qualifier and fresh OWN526 financial exports."""
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

STAGE = 'campaign-p01-grouped-factual-financial'
QUALIFICATION_STAGE = 'campaign-p01-grouped-factual-qualification'
RECEIPT_SCHEMA = 'research.p01-own526-factual-batch-receipt/1'
QUALIFICATION_FILES = ('batch-input.json','zero-session-boundaries.json','batch-preflight.json',
    'group-action-codec-proof.json','target-independence-component.json.gz',
    'actual-two-session-component.json.gz','action-accounting-and-report.json','qualification-summary.json')
STOP = {'stopped','exit_code','oom_killed','wait_error'}
ASSET = {'name','bytes','sha256','manifest_sha256','compression'}
PUBLIC = frozenset(('schema','arm','stage','run_id','head','request_sha256','protocol_sha256',
    'strict_parent_outer_sha256','status','production_contacted','qualification_worker','worker','reviewer',
    'qualification_encrypted_output','encrypted_output','encrypted_output_exported','export_error',
    'export_qualification_sha256','qualification_exported','review_stop_unknown',
    'qualification_log_copy_failed','worker_log_copy_failed','review_log_copy_failed'))


def sealed(root, target, key, request, *, stage=STAGE):
    need(stage in (STAGE,QUALIFICATION_STAGE), 'P01_BATCH_DECLARED_EXPORT_SCOPE')
    call = function('system_campaign_evidence_export.py','seal',{
        'campaign-factual-suffix':stage,'P02':'P01',
        'RETAINED_EXPORT_EXACT_P02_RESEARCH_SCOPE':'P01_BATCH_EXACT_EXPORT_SCOPE'},vars(original))
    return call(root,target,key,request,'P01',stage=stage,
        protocol_sha256=json.loads(Path(request).read_bytes())['protocol_sha256'])


def qualify_export(path, request):
    fn, = [n for n in ast.parse(Path(marker_source.__file__).read_bytes()).body
           if isinstance(n,ast.FunctionDef) and n.name=='qualify_export']
    return compile_body(fn,dict(vars(marker_source),STAGE=STAGE,sealed=sealed,__file__=__file__))(path,request)


def write_receipt(path, value):
    need(set(value)<=PUBLIC and value['schema']==RECEIPT_SCHEMA and value['arm']=='P01'
         and value['stage']==STAGE and value['production_contacted'] is False, 'P01_BATCH_PUBLIC_ALLOWLIST')
    nested={'qualification_worker','worker','reviewer','qualification_encrypted_output','encrypted_output','export_error'}
    need(all(type(v) in (str,int,bool,type(None)) for k,v in value.items() if k not in nested),
         'P01_BATCH_PUBLIC_METADATA_ONLY')
    for name in ('qualification_worker','worker','reviewer'):
        if name in value:
            stop=value[name]
            need(set(stop)==STOP and stop['stopped'] is True and type(stop['exit_code']) is int
                 and type(stop['oom_killed']) is bool and type(stop['wait_error']) in (str,type(None)),
                 'P01_BATCH_EXACT_PUBLIC_STOP')
    for name in ('qualification_encrypted_output','encrypted_output'):
        if name in value:need(set(value[name])==ASSET, 'P01_BATCH_EXACT_PUBLIC_ASSET')
    if 'export_error' in value:need(set(value['export_error'])=={'type','code'}, 'P01_BATCH_STATIC_EXPORT_ERROR_ONLY')
    for name in ('qualification_log_copy_failed','worker_log_copy_failed','review_log_copy_failed'):
        if name in value:need(type(value[name]) is bool, 'P01_BATCH_LOG_STATUS_BOOLEAN')
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);pending=path.with_suffix('.partial')
    with pending.open('w',encoding='utf8',newline='\n') as stream:
        stream.write(json.dumps(value,sort_keys=True,indent=2)+'\n');stream.flush();os.fsync(stream.fileno())
    os.replace(pending,path)


def preserve_qualification(receipt, root, path, key, request):
    stop=receipt['qualification_worker']
    need(stop['stopped'] is True and stop['exit_code']==0 and not stop['oom_killed'], 'P01_BATCH_ONLY_SUCCESSFUL_STOPPED_QUALIFIER')
    root=Path(root)
    required={'spec.json','request.json','source-bindings.json','source-map.json'}|{
        'qualification/'+n for n in (*QUALIFICATION_FILES,'worker-inspect.json')}
    actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    optional={'qualification/worker.log','qualification/log-copy-failure.json'}
    need(required<=actual and actual<=required|optional
         and ('qualification/worker.log' in actual or 'qualification/log-copy-failure.json' in actual)
         and receipt.get('qualification_log_copy_failed',False)==('qualification/log-copy-failure.json' in actual)
         and not any(p.is_symlink() for p in root.rglob('*'))
         and sum(p.stat().st_size for p in root.rglob('*') if p.is_file())<=128*1024**2,
         'P01_BATCH_QUALIFIER_PROOFS_ONLY_NO_DISPOSABLE_BOOK')
    proof=json.loads((root/'qualification/qualification-summary.json').read_bytes())
    need(proof['status']=='OWN526_GROUPED_FACTUAL_INPUT_AND_RUNTIME_QUALIFIED'
         and proof['financial_authority'] is False and proof['financial_predecessor_authorized'] is False
         and proof['source_epoch_boundary_reemitted'] is False and proof['component_transitions']==2,
         'P01_BATCH_ACTUAL_NONFINANCIAL_QUALIFICATION')
    receipt['qualification_encrypted_output']=sealed(root,Path(path).parent/'p01-factual-batch-qualification.tar.crseal',
        key,request,stage=QUALIFICATION_STAGE)
    receipt['qualification_exported']=True;write_receipt(path,receipt)


def finish(receipt, root, path, key, request, *, known):
    receipt['encrypted_output_exported']=False;write_receipt(path,receipt)
    if known:
        need(receipt['status']!='ACTIVE_WRITER_STOP_UNKNOWN_NO_MUTABLE_SNAPSHOT', 'P01_BATCH_UNKNOWN_WRITER_NO_SNAPSHOT')
        try:
            receipt['encrypted_output']=sealed(root,Path(path).parent/'p01-factual-batch-financial.tar.crseal',key,request)
            receipt['encrypted_output_exported']=True
        except Exception as error:
            code=str(error)
            receipt['export_error']=dict(type=type(error).__name__,code=code if re.fullmatch('REFUSED_[A-Z0-9_]+',code) else 'EXPORT_OPERATION_FAILED')
            receipt['status']='KNOWN_STOP_EXPORT_FAILED_NO_PLAINTEXT_FALLBACK'
    write_receipt(path,receipt)
